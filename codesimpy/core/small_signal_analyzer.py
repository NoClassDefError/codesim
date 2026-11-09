"""Small-signal and modal-interaction analysis without plotting code."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import sympy as sp
from scipy.linalg import block_diag, eig

# Synchronous-frame rotation operator, J v = [-vq, vd].
_J = np.array([[0.0, -1.0], [1.0, 0.0]])


class SmallSignalAnalyzer:
    def __init__(self, system: Any) -> None:
        self.system = system
        self.latestAnalysis: dict[str, Any] = {}
        self._deviceJacobianCache: dict[int, tuple[Any, Any]] = {}

    # ------------------------------------------------------------------
    # Frequency-domain port models
    # ------------------------------------------------------------------
    def device_admittance(
        self, device: Any, operatingPoint: dict[str, Any], frequency_Hz: Any, *,
        frozenStateNames: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Linearized dq output admittance/impedance of one device.

        The device is linearized at ``operatingPoint`` (from
        ``system.initialize``) with its port input as the only input, which
        follows the convention of ``rlGrid.analyzeSmallSignal``: the alpha-beta
        frame at the operating point is the synchronous dq frame, and each
        device uses its own local rotating frame internally.

        Conventions, system base, per unit:

        * ``frequency_Hz`` is the dq-frame (baseband) frequency. A dq
          frequency f corresponds to f +/- f0 in the stationary frame.
          ``s_pu = j 2 pi f / wBase``.
        * Output admittance ``Y`` and impedance ``Z = Y^-1`` follow the
          slide convention ``delta i_out = -Y delta v``. Here ``i_out`` is
          the current injected into the network, so a passive device has a
          positive-real ``Y``. A voltage-type device has the Thevenin form
          ``delta v = -Z delta i_out``.
        * ``frozenStateNames`` removes states from the linear model (held
          at their operating values), e.g. ``delta``/``theta``/``xPLL``
          for the frozen-slow-state EMT model. States with all-zero rows in
          both A and B (reference-driven frame angles) are frozen
          automatically.

        Returns ``(nf, 2, 2)`` dq matrices, their complex-vector (sequence)
        forms, the device state-space model and its open-loop poles (pu,
        the same units as ``rlGrid.analyzeSmallSignal``).
        """
        system, grid = self.system, self.system.rlGrid
        node = self._deviceNode(device)
        state = np.asarray(operatingPoint["state"], dtype=float).reshape(-1)
        reference = np.asarray(operatingPoint["reference"], dtype=float).reshape(-1)
        grid.refreshParameters()
        branch, voltage, current = grid.g_numeric(state, reference)
        pair = slice(2 * node, 2 * node + 2)
        if device.type == "Current":
            portInput = np.asarray(voltage, dtype=float)[pair]
        else:
            networkCurrent = np.kron(grid.A, np.eye(2)) @ np.asarray(branch, dtype=float)
            portInput = networkCurrent[pair] - np.asarray(current, dtype=float)[pair]
        x0 = state[[system.stateNames.index(str(symbol)) for symbol in device.x]]
        u0 = reference[[system.referenceNames.index(str(symbol)) for symbol in device.uref]]
        jacobian = self._deviceJacobians(device)
        values = np.r_[x0, device.Inputscale * portInput, u0, self._deviceParameterValues(device)]
        A, B, C, D = (np.atleast_2d(np.asarray(item, dtype=float)) for item in jacobian(*values))
        A, B = A.reshape(device.n, device.n), B.reshape(device.n, 2)
        C, D = C.reshape(2, device.n), D.reshape(2, 2)
        B, C, D = B * device.Inputscale, C * device.Outputscale, D * device.Inputscale * device.Outputscale

        names = [str(symbol) for symbol in device.x]
        frozen = set(frozenStateNames)
        unknown = frozen - set(names)
        if unknown:
            raise ValueError(f"unknown device states: {sorted(unknown)}")
        keep = [i for i, name in enumerate(names) if name not in frozen
                and (np.any(A[i] != 0) or np.any(B[i] != 0))]
        A, B, C = A[np.ix_(keep, keep)], B[keep], C[:, keep]
        keptNames = [names[i] for i in keep]

        frequency_Hz = np.atleast_1d(np.asarray(frequency_Hz, dtype=float))
        s = 1j * 2 * np.pi * frequency_Hz / (2 * np.pi * system.base["frequency_Hz"])
        if keep:
            identity = np.eye(len(keep))
            resolvent = np.linalg.solve(s[:, None, None] * identity - A, np.broadcast_to(B, (s.size, *B.shape)))
            transfer = C @ resolvent + D
        else:
            transfer = np.broadcast_to(D.astype(complex), (s.size, 2, 2)).copy()
        if device.type == "Current":
            admittance = -transfer
            impedance = self._safeInverse(admittance)
        else:
            impedance = -transfer
            admittance = self._safeInverse(impedance)
        return {
            "device": device.index, "type": device.type, "node": node,
            "busName": system.busNames[node],
            "frequency_Hz": frequency_Hz, "s_pu": s,
            "admittance": admittance, "impedance": impedance,
            "admittanceSequence": self.dqToSequence(admittance),
            "impedanceSequence": self.dqToSequence(impedance),
            "stateSpace": {"A": A, "B": B, "C": C, "D": D, "stateNames": keptNames},
            "poles": np.linalg.eigvals(A) if keep else np.zeros(0, complex),
            "portInput": portInput,
        }

    def grid_impedance(
        self, bus: str | int, frequency_Hz: Any, *,
        operatingPoint: dict[str, Any] | None = None,
        includeDevices: Iterable[Any] = (),
        groundedBuses: Iterable[str | int] | None = None,
        includeShunts: bool = True,
    ) -> dict[str, Any]:
        """Driving-point dq impedance of the network seen from ``bus``.

        The RL branches of ``rlGrid`` (after Kron reduction, system base)
        form the nodal admittance matrix. ``groundedBuses`` are ideal voltage
        sources with zero small-signal voltage; by default these are the
        ``Infbus`` nodes. Other converter devices are open circuits unless
        they are listed in ``includeDevices``. Listed devices are added with
        their linearized output admittance from :meth:`device_admittance`,
        which needs ``operatingPoint``. With ``includeShunts`` the
        ``Capacitor`` devices (line charging) are included as
        ``Gd + C (s + w J)``.

        Frequencies and conventions are the same as in
        :meth:`device_admittance`. ``R_th``/``X_th``/``SCR`` are taken at
        s = 0 and refer to the system base.
        """
        system, grid = self.system, self.system.rlGrid
        busIndex = self._busIndex(bus)
        if groundedBuses is None:
            grounded = [i for i, device in enumerate(grid.Vdev) if type(device).__name__ == "Infbus"]
        else:
            grounded = [self._busIndex(item) for item in groundedBuses]
        if busIndex in grounded:
            raise ValueError("the observed bus cannot be grounded")
        if not grounded:
            raise ValueError("at least one grounded (source) bus is required")
        devices = [system.devices[item] if isinstance(item, str) else item for item in includeDevices]
        if devices and operatingPoint is None:
            raise ValueError("includeDevices requires operatingPoint")

        frequency_Hz = np.atleast_1d(np.asarray(frequency_Hz, dtype=float))
        wBase = 2 * np.pi * system.base["frequency_Hz"]
        s = np.r_[0.0, 1j * 2 * np.pi * frequency_Hz / wBase]
        identity, n = np.eye(2), grid.n
        Y = np.zeros((s.size, 2 * n, 2 * n), complex)
        for branch in range(grid.b):
            z = grid.R[branch] * identity + grid.L[branch] * (s[:, None, None] * identity + _J)
            y = np.linalg.inv(z)
            incidence = np.kron(grid.A[:, branch].reshape(-1, 1), identity)
            Y += incidence @ y @ incidence.T
        if includeShunts:
            for node, device in enumerate(grid.Vdev):
                if type(device).__name__ == "Capacitor":
                    C, Gd, w = (float(device.p[name]["num"]) for name in ("C", "Gd", "w"))
                    block = slice(2 * node, 2 * node + 2)
                    Y[:, block, block] += Gd * identity + C * (s[:, None, None] * identity + w * _J)
        for device in devices:
            node = self._deviceNode(device)
            if node in grounded:
                continue
            portModel = self.device_admittance(device, operatingPoint, np.r_[0.0, frequency_Hz])
            admittance = np.nan_to_num(portModel["admittance"])
            block = slice(2 * node, 2 * node + 2)
            Y[:, block, block] += admittance

        keepNodes = [i for i in range(n) if i not in grounded]
        keep = np.ravel([[2 * i, 2 * i + 1] for i in keepNodes])
        Zbus = self._safeInverse(Y[:, keep][:, :, keep])
        position = keepNodes.index(busIndex)
        Z = Zbus[:, 2 * position:2 * position + 2, 2 * position:2 * position + 2]
        Z0, Z = Z[0], Z[1:]
        R_th, X_th = float(Z0[0, 0].real), float(Z0[1, 0].real)
        return {
            "bus": system.busNames[busIndex], "groundedBuses": [system.busNames[i] for i in grounded],
            "frequency_Hz": frequency_Hz, "s_pu": s[1:],
            "impedance": Z, "admittance": self._safeInverse(Z),
            "impedanceSequence": self.dqToSequence(Z),
            "R_th": R_th, "X_th": X_th, "RX": R_th / X_th if X_th else np.inf,
            "SCR": 1 / np.hypot(R_th, X_th),
        }

    @staticmethod
    def dqToSequence(matrix: Any) -> dict[str, np.ndarray]:
        """Complex-vector form of dq matrices: ``y = M+ x + M- conj(x)``."""
        M = np.asarray(matrix, dtype=complex)
        dd, dq, qd, qq = M[..., 0, 0], M[..., 0, 1], M[..., 1, 0], M[..., 1, 1]
        return {"positive": ((dd + qq) + 1j * (qd - dq)) / 2,
                "negative": ((dd - qq) + 1j * (qd + dq)) / 2}

    @staticmethod
    def _safeInverse(matrix: np.ndarray) -> np.ndarray:
        matrix = np.asarray(matrix, dtype=complex)
        result = np.full_like(matrix, np.nan)
        for index in np.ndindex(matrix.shape[:-2]):
            block = matrix[index]
            if np.isfinite(block).all() and np.linalg.cond(block) < 1e12:
                result[index] = np.linalg.inv(block)
        return result

    def _busIndex(self, bus: str | int) -> int:
        names = self.system.busNames
        if isinstance(bus, str):
            if bus not in names:
                raise ValueError(f"unknown bus {bus!r}; available: {names}")
            return names.index(bus)
        index = int(bus)
        if not 0 <= index < len(names):
            raise ValueError("bus index out of range")
        return index

    def _deviceNode(self, device: Any) -> int:
        if isinstance(device, str):
            device = self.system.devices[device]
        grid = self.system.rlGrid
        for node, (voltageDevice, currentDevice) in enumerate(zip(grid.Vdev, grid.Idev)):
            if device is voltageDevice or device is currentDevice:
                return node
        raise ValueError("device is not connected to this system")

    @staticmethod
    def _deviceParameterValues(device: Any) -> np.ndarray:
        values: list[float] = []
        for parameter in device.p.values():
            values.extend(np.asarray(parameter["num"], dtype=float).reshape(-1, order="F"))
        return np.asarray(values, dtype=float)

    def _deviceJacobians(self, device: Any):
        """Compiled ``(A, B, C, D)`` of one device, cached per device object."""
        cached = self._deviceJacobianCache.get(id(device))
        if cached is not None and cached[0] is device:
            return cached[1]
        x, u = sp.Matrix(device.x), sp.Matrix(device.u)
        f = sp.Matrix(device.f) if len(device.f) else sp.zeros(0, 1)
        g = sp.Matrix(device.g)
        parameters: list[Any] = []
        for parameter in device.p.values():
            parameters.extend(np.asarray(parameter["sym"], dtype=object).reshape(-1, order="F"))
        matrices = [
            f.jacobian(x) if device.n else sp.zeros(0, 0),
            f.jacobian(u) if device.n else sp.zeros(0, 2),
            g.jacobian(x) if device.n else sp.zeros(2, 0),
            g.jacobian(u),
        ]
        arguments = list(device.x) + list(device.u) + list(device.uref) + parameters
        function = sp.lambdify(arguments, matrices, modules="numpy", cse=True, docstring_limit=0)

        def evaluate(*values):
            return [np.asarray(item, dtype=float) for item in function(*values)]

        self._deviceJacobianCache[id(device)] = (device, evaluate)
        return evaluate

    def analyze(self, operatingPoint: dict[str, Any]) -> dict[str, Any]:
        analysis = self.system.rlGrid.analyzeSmallSignal(
            operatingPoint["state"], operatingPoint["reference"],
            2 * np.pi * self.system.base["frequency_Hz"],
        )
        self.latestAnalysis = analysis
        return analysis

    @staticmethod
    def analyzeModes(
        stateMatrix: Any, stateNames: Iterable[str], modeLabels: Iterable[str] | None = None
    ) -> dict[str, Any]:
        A = np.asarray(stateMatrix, dtype=float)
        names = list(map(str, stateNames))
        labels = list(map(str, modeLabels)) if modeLabels is not None else [str(i + 1) for i in range(len(names))]
        eigenvalues, leftVectors, rightVectors = eig(A, left=True, right=True)
        for i in range(len(eigenvalues)):
            pairProduct = np.vdot(leftVectors[:, i], rightVectors[:, i])
            if abs(pairProduct) > 1e-10:
                leftVectors[:, i] /= np.conj(pairProduct)
        participation = np.abs(rightVectors * np.conj(leftVectors))
        participation /= np.maximum(participation.sum(axis=0, keepdims=True), np.finfo(float).eps)
        naturalFrequency = np.abs(eigenvalues)
        dampingRatio = -eigenvalues.real / np.maximum(naturalFrequency, np.finfo(float).eps)
        dominantIndices = participation.argmax(axis=0)
        modeTable = [
            {
                "idx": labels[i], "eig": eigenvalues[i], "wn": naturalFrequency[i],
                "zeta": dampingRatio[i], "dominantStates": names[dominantIndices[i]],
            }
            for i in range(len(eigenvalues))
        ]
        return {
            "eigenvalues": eigenvalues, "rightEigenvectors": rightVectors,
            "leftEigenvectors": leftVectors, "participation": participation,
            "modeTable": modeTable,
        }

    def _partitionModalTransform(self, partition: Any, blockStarts: Any):
        stateCount = len(self.system.stateNames)
        partition = np.asarray(partition, dtype=int).reshape(-1)
        blockStarts = np.asarray(blockStarts, dtype=int).reshape(-1)
        # Accept MATLAB's one-based indices at the public boundary.
        if set(partition.tolist()) == set(range(1, stateCount + 1)):
            partition = partition - 1
        if blockStarts.size and blockStarts[0] == 1:
            blockStarts = blockStarts - 1
        point = self.system.initialize()
        stateMatrix = self.system.rlGrid.getStateMatrix(point["state"], point["reference"])
        partitionedMatrix = stateMatrix[np.ix_(partition, partition)]
        stops = np.r_[blockStarts[1:], stateCount]
        rightBlocks, leftBlocks = [], []
        for start, stop in zip(blockStarts, stops):
            _, right = eig(partitionedMatrix[start:stop, start:stop])
            if np.linalg.matrix_rank(right) != right.shape[0]:
                raise ValueError("subsystem has a singular modal basis")
            rightBlocks.append(right)
            leftBlocks.append(np.linalg.inv(right).conj().T)
        return stateMatrix, partitionedMatrix, block_diag(*rightBlocks), block_diag(*leftBlocks)

    def partitionSubsystem(self, partition: Any, blockStarts: Any, maskedIndices: Any = None):
        stateMatrix, partitionedMatrix, rightBasis, leftBasis = self._partitionModalTransform(partition, blockStarts)
        modalMatrix = leftBasis.conj().T @ partitionedMatrix @ rightBasis
        if maskedIndices:
            rows, columns = (np.asarray(v, dtype=int).reshape(-1) for v in maskedIndices)
            if rows.size and rows.min() >= 1 and columns.size and columns.min() >= 1:
                rows, columns = rows - 1, columns - 1
            modalMatrix[np.ix_(rows, columns)] = 0
        reconstructedMatrix = rightBasis @ modalMatrix @ leftBasis.conj().T
        return modalMatrix, stateMatrix, partitionedMatrix, reconstructedMatrix

    # Devices that belong to the network/source block of an interaction analysis.
    NETWORK_DEVICE_TYPES = ("Infbus", "Capacitor", "ZeroCurrent")

    def devicePartition(self, devices: Iterable[Any] | None = None):
        """One block per unit device plus one ``Network / source`` block.

        ``devices`` defaults to every device of the RL grid that has states and is
        not an ``Infbus``, ``Capacitor`` or ``ZeroCurrent``; their states form one
        block each, in grid order. All other states (branch currents, line
        capacitors, sources) form the last block. Returns the one-based
        ``partition`` and ``blockStarts`` expected by :meth:`partitionSubsystem`
        and the block names.
        """
        names, grid = self.system.stateNames, self.system.rlGrid
        if devices is None:
            devices = [device for device in list(grid.Vdev) + list(grid.Idev)
                       if type(device).__name__ not in self.NETWORK_DEVICE_TYPES and len(device.x)]
        blocks, used = [], set()
        for device in devices:
            indices = [names.index(str(symbol)) for symbol in device.x]
            blocks.append((f"{type(device).__name__} {str(device.index).lstrip('_')}", indices))
            used.update(indices)
        rest = [index for index in range(len(names)) if index not in used]
        if rest:
            blocks.append(("Network / source", rest))
        partition = [index + 1 for _, indices in blocks for index in indices]
        blockStarts = list(np.cumsum([1] + [len(indices) for _, indices in blocks[:-1]]))
        return partition, [int(start) for start in blockStarts], [name for name, _ in blocks]

    def interactionAnalysis(self, maskedIndices: Any = None, devices: Iterable[Any] | None = None,
                            estimateShift: tuple[int, Any] | None = None) -> dict[str, Any]:
        """Modal interaction analysis of any system, partitioned by :meth:`devicePartition`.

        The local eigenvalues are those of the diagonal blocks of the state matrix (each
        device with the rest of the system frozen at the operating point); the full
        eigenvalues are those of the whole state matrix. ``maskedIndices`` (one-based
        modal rows, columns) removes selected couplings for the reduced eigenvalues;
        ``estimateShift = (target, interactions)`` adds the shift estimate of
        :meth:`estimateShift`.
        """
        partition, blockStarts, blockNames = self.devicePartition(devices)
        masked = maskedIndices if maskedIndices is not None else ([], [])
        modalMatrix, stateMatrix, partitionedMatrix, reconstructedMatrix = (
            self.partitionSubsystem(partition, blockStarts, masked))
        analysis = {
            "partition": partition, "dIdx": blockStarts, "blockNames": blockNames,
            "maskedIdx": masked, "DAll": modalMatrix, "AOriginal": stateMatrix,
            "APartitioned": partitionedMatrix, "ABack": reconstructedMatrix,
            "shiftTable": self.listEigenvalueShift(masked, partition, blockStarts),
            "modalTable": self.analyzeModes(
                stateMatrix, self.system.stateNames,
                [str(index) for index in range(1, len(self.system.stateNames) + 1)],
            )["modeTable"],
        }
        if estimateShift is not None:
            analysis["estimatedShift"] = self.estimateShift(modalMatrix, *estimateShift)
        return analysis

    def eigenvalueShift(self, partition: Any, blockStarts: Any, maskedIndices: Any = None):
        modalMatrix, *_ = self.partitionSubsystem(partition, blockStarts, maskedIndices)
        return np.linalg.eigvals(modalMatrix), np.diag(modalMatrix)

    def listEigenvalueShift(self, maskedIndices: Any, partition: Any, blockStarts: Any):
        localMatrix, _, partitionedMatrix, _ = self.partitionSubsystem(partition, blockStarts)
        reducedMatrix, *_ = self.partitionSubsystem(partition, blockStarts, maskedIndices)
        fullEigenvalues, leftVectors, rightVectors = eig(partitionedMatrix, left=True, right=True)
        participation = np.abs(rightVectors * np.conj(leftVectors))
        dominant = participation.argmax(axis=0)
        order = np.asarray(partition, dtype=int).reshape(-1)
        if order.size and order.min() >= 1:
            order -= 1
        names = np.asarray(self.system.stateNames, dtype=object)[order]
        local = self.matchEigenvalues(fullEigenvalues, np.diag(localMatrix))
        reduced = self.matchEigenvalues(fullEigenvalues, np.diag(reducedMatrix))
        return [
            {
                "related_state": str(names[dominant[i]]),
                "local_lambda": f"{local[i].real:.1e}{local[i].imag:+.1e}j",
                "full_lambda": f"{fullEigenvalues[i].real:.1e}{fullEigenvalues[i].imag:+.1e}j",
                "reduced_lambda": f"{reduced[i].real:.1e}{reduced[i].imag:+.1e}j",
                "delta_lambda": f"{(fullEigenvalues[i] - reduced[i]).real:.1e}{(fullEigenvalues[i] - reduced[i]).imag:+.1e}j",
                "local_value": local[i], "full_value": fullEigenvalues[i],
                "reduced_value": reduced[i], "delta_value": fullEigenvalues[i] - reduced[i],
            }
            for i in range(len(fullEigenvalues))
        ]

    @staticmethod
    def estimateShift(modalMatrix: Any, targetIndex: int, interactionIndices: Any) -> complex:
        matrix = np.asarray(modalMatrix, dtype=complex)
        target = targetIndex - 1 if targetIndex >= 1 else targetIndex
        interactions = np.asarray(interactionIndices, dtype=int).reshape(-1)
        if interactions.size and interactions.min() >= 1:
            interactions -= 1
        delta = 0j
        for index in interactions:
            denominator = matrix[target, target] - matrix[index, index]
            if abs(denominator) <= np.finfo(float).eps:
                raise ValueError("cannot estimate a shift between repeated local modes")
            product = matrix[target, index] * matrix[index, target]
            ratio = product / denominator**2
            if abs(1 - ratio) <= np.finfo(float).eps:
                raise ValueError("modal shift correction is singular")
            delta += (-product / denominator) / (1 - ratio)
        return delta

    @staticmethod
    def matchEigenvalues(reference: Any, candidates: Any) -> np.ndarray:
        reference = np.asarray(reference, dtype=complex).reshape(-1)
        candidates = np.asarray(candidates, dtype=complex).reshape(-1)
        available = np.ones(candidates.size, dtype=bool)
        matched = np.empty_like(reference)
        for i, value in enumerate(reference):
            distance = np.where(available, np.abs(candidates - value), np.inf)
            index = int(distance.argmin())
            matched[i] = candidates[index]
            available[index] = False
        return matched
