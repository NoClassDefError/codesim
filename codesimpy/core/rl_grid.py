"""Symbolic assembly and numerical solution of an RL multi-infeed grid."""

from __future__ import annotations

from collections import OrderedDict
from functools import cached_property
from typing import Any, Iterable

import numpy as np
import sympy as sp
from scipy.linalg import eig
from scipy.optimize import least_squares, root

# Symbolic models keyed by RLGrid._structureKey(); oldest entries are evicted first.
_MODEL_CACHE: "OrderedDict[tuple, dict[str, Any]]" = OrderedDict()
_MODEL_CACHE_SIZE = 8


class RLGrid:
    """Interconnect voltage/current devices in stationary alpha-beta axes.

    Unlike the MATLAB implementation this class compiles SymPy expressions to
    NumPy callables in memory. There are no generated source files, cache hashes,
    path manipulation, or toolbox-specific derivative cleanup passes.
    """

    def __init__(
        self, A: Any, L: Any, R: Any, Vb: float, Sb: float,
        Vdev: Iterable[Any], Idev: Iterable[Any], systemName: str = "default",
    ) -> None:
        A = np.asarray(A, dtype=float)
        L = np.asarray(L, dtype=float).reshape(-1)
        R = np.asarray(R, dtype=float).reshape(-1)
        Vdev, Idev = list(Vdev), list(Idev)
        emptyNodes = [i for i, device in enumerate(Vdev) if device is None]
        if emptyNodes != [i for i, device in enumerate(Idev) if device is None]:
            raise ValueError("each passive node must have both device ports empty")
        A, L, R = self.kronReduction(A, L, R, emptyNodes)

        self.systemName = str(systemName or "default")
        self.Vb, self.Sb = float(Vb), float(Sb)
        self.A, self.L, self.R = A, L, R
        self.Vdev = [device for device in Vdev if device is not None]
        self.Idev = [device for device in Idev if device is not None]
        self.n, self.b = A.shape
        for device in self.Vdev + self.Idev:
            if device.Vb != self.Vb or device.Sb != self.Sb:
                device.convertToAnotherBase(self.Vb, self.Sb)

        self.p: dict[str, Any] = {}
        self.Lsym = tuple(sp.Symbol(f"Lg{i + 1}", real=True) for i in range(self.b))
        self.Rsym = tuple(sp.Symbol(f"Rg{i + 1}", real=True) for i in range(self.b))
        for i in range(self.b):
            self.p[str(self.Lsym[i])] = {"num": self.L[i], "sym": self.Lsym[i]}
            self.p[str(self.Rsym[i])] = {"num": self.R[i], "sym": self.Rsym[i]}
        self.ibsym = tuple(
            symbol for i in range(self.b)
            for symbol in (sp.Symbol(f"iga{i + 1}", real=True), sp.Symbol(f"igb{i + 1}", real=True))
        )
        self.x = list(self.ibsym)
        self.u: list[sp.Symbol] = []
        for voltageDevice, currentDevice in zip(self.Vdev, self.Idev):
            self.u.extend(voltageDevice.uref)
            self.u.extend(currentDevice.uref)
            self.x.extend(voltageDevice.x)
            self.x.extend(currentDevice.x)
        self.y: list[sp.Symbol] = []
        self.vnsym: tuple[sp.Symbol, ...] = ()
        self.refreshParameters(rebuild=True)
        self._buildSymbolicModel()

    def getStateAndOutputEquationsSym(self) -> tuple[sp.Matrix, sp.Matrix]:
        Abar = (
            sp.kronecker_product(sp.Matrix(self.A), sp.eye(2))
            if self.b else sp.zeros(2 * self.n, 0)
        )
        ib = sp.Matrix(self.ibsym) if self.b else sp.zeros(0, 1)
        networkCurrent = Abar * ib
        vn = sp.zeros(2 * self.n, 1)
        deviceCurrent = sp.zeros(2 * self.n, 1)
        for i, (Vdev, Idev) in enumerate(zip(self.Vdev, self.Idev)):
            indices = [2 * i, 2 * i + 1]
            voltageSubs = dict(zip(Vdev.u, [Vdev.Inputscale * networkCurrent[j] for j in indices]))
            voltage = Vdev.Outputscale * Vdev.g.subs(voltageSubs, simultaneous=True)
            vn[indices[0]], vn[indices[1]] = voltage[0], voltage[1]
            currentSubs = dict(zip(Idev.u, [Idev.Inputscale * vn[j] for j in indices]))
            current = Idev.Outputscale * Idev.g.subs(currentSubs, simultaneous=True)
            deviceCurrent[indices[0]], deviceCurrent[indices[1]] = current[0], current[1]

        if self.b:
            Ldiag = sp.diag(*[value for item in self.Lsym for value in (item, item)])
            Rdiag = sp.diag(*[value for item in self.Rsym for value in (item, item)])
            branchDerivative = Ldiag.inv() * (Abar.T * vn - Rdiag * ib)
        else:
            branchDerivative = sp.zeros(0, 1)
        stateParts: list[sp.Matrix] = [branchDerivative]
        for i, (Vdev, Idev) in enumerate(zip(self.Vdev, self.Idev)):
            indices = [2 * i, 2 * i + 1]
            voltageInput = [networkCurrent[j] - deviceCurrent[j] for j in indices]
            voltageSubs = dict(zip(Vdev.u, [Vdev.Inputscale * item for item in voltageInput]))
            currentSubs = dict(zip(Idev.u, [Idev.Inputscale * vn[j] for j in indices]))
            stateParts.extend([
                Vdev.f.subs(voltageSubs, simultaneous=True),
                Idev.f.subs(currentSubs, simultaneous=True),
            ])
        return sp.Matrix.vstack(*stateParts), sp.Matrix.vstack(ib, vn, deviceCurrent)

    def _structureKey(self) -> tuple:
        """Fingerprint everything that enters the symbolic model, but no numeric values.

        Parameter values (``p[...]["num"]``, ``L``, ``R``) are passed to the compiled
        functions at call time, so grids that differ only in those values share one
        cached model. Anything written into the equations as a number (per-unit scales,
        values substituted inside a device) is part of ``f``/``g``/``getFInit`` or the
        scales below, so changing it gives a different key.
        """
        def matrix(value: Any) -> sp.ImmutableMatrix:
            return sp.ImmutableMatrix(sp.Matrix(value) if len(value) else sp.zeros(0, 1))

        devices = tuple(
            (
                f"{type(device).__module__}.{type(device).__qualname__}",
                device.index, device.type,
                float(device.Inputscale), float(device.Outputscale),
                tuple(device.x), tuple(device.u), tuple(device.uref),
                matrix(device.f), matrix(device.g), matrix(device.getFInit()),
            )
            for device in self.Vdev + self.Idev
        )
        return (
            self.A.shape, self.A.tobytes(), devices,
            tuple(self.x), tuple(self.u),
            tuple(self.parameterMap["parameterSymbols"]),
        )

    def _buildSymbolicModel(self) -> None:
        """Attach the symbolic model, reusing a cached build when the structure matches."""
        key = self._structureKey()
        entry = _MODEL_CACHE.get(key)
        if entry is None:
            entry = self._buildSymbolicEntry()
            _MODEL_CACHE[key] = entry
            while len(_MODEL_CACHE) > _MODEL_CACHE_SIZE:
                _MODEL_CACHE.popitem(last=False)
        else:
            _MODEL_CACHE.move_to_end(key)
        self._modelEntry = entry
        self.__dict__.pop("A_sym", None)
        self.__dict__.pop("A_core", None)

        self.f, self.g = entry["f"], entry["g"]
        self.f_init_sym = entry["f_init_sym"]
        self._f_init_residual = entry["f_init_residual"]
        self.fInitStateIndices = entry["fInitStateIndices"]
        # Wrap per grid: the wrappers read this grid's parameter values.
        self.f_core = self._wrap(entry["fFunction"])
        self.g_core = self._wrap(entry["gFunction"])
        self.f_init_core = self._wrap(entry["fInitFunction"])
        self.f_numeric = self.f_core
        self.f_init = self.f_init_core

        def g_numeric(state: Any, *reference: Any):
            value = self.g_core(state, *reference)
            branchStop = 2 * self.b
            voltageStop = branchStop + 2 * self.n
            return value[:branchStop], value[branchStop:voltageStop], value[voltageStop:]
        self.g_numeric = g_numeric

    def _buildSymbolicEntry(self) -> dict[str, Any]:
        """Derive and compile the symbolic model (slow; result is shared via the cache)."""
        f, g = self.getStateAndOutputEquationsSym()
        if self.b:
            Jbar = sp.kronecker_product(sp.eye(self.b), sp.Matrix([[0, -1], [1, 0]]))
            branchInit = f[: 2 * self.b, :] - Jbar * sp.Matrix(self.ibsym)
        else:
            branchInit = sp.zeros(0, 1)
        f_init_sym = sp.MutableDenseMatrix(f)
        f_init_sym[: 2 * self.b, :] = branchInit

        Abar = (
            sp.kronecker_product(sp.Matrix(self.A), sp.eye(2))
            if self.b else sp.zeros(2 * self.n, 0)
        )
        branchState = sp.Matrix(self.ibsym) if self.b else sp.zeros(0, 1)
        networkCurrent = Abar * branchState
        voltageStart = 2 * self.b
        currentStart = voltageStart + 2 * self.n
        nodeVoltage = g[voltageStart:currentStart, :]
        deviceCurrent = g[currentStart:currentStart + 2 * self.n, :]
        residualParts: list[sp.Matrix] = [branchInit]
        residualStateIndices = list(range(2 * self.b))
        stateOffset = 2 * self.b
        for i, (Vdev, Idev) in enumerate(zip(self.Vdev, self.Idev)):
            indices = [2 * i, 2 * i + 1]
            voltageInput = [networkCurrent[j] - deviceCurrent[j] for j in indices]
            substitutions = dict(zip(Vdev.u, [Vdev.Inputscale * item for item in voltageInput]))
            substitutions.update(dict(zip(Idev.u, [Idev.Inputscale * nodeVoltage[j] for j in indices])))
            voltageInit, currentInit = Vdev.getFInit(), Idev.getFInit()
            voltageInit = sp.Matrix(voltageInit) if len(voltageInit) else sp.zeros(0, 1)
            currentInit = sp.Matrix(currentInit) if len(currentInit) else sp.zeros(0, 1)
            residualStateIndices.extend(
                stateOffset + index for index in Vdev.getFInitStateIndices()
            )
            stateOffset += len(Vdev.x)
            residualStateIndices.extend(
                stateOffset + index for index in Idev.getFInitStateIndices()
            )
            stateOffset += len(Idev.x)
            residualParts.extend([
                voltageInit.subs(substitutions, simultaneous=True),
                currentInit.subs(substitutions, simultaneous=True),
            ])
        f_init_residual = sp.Matrix.vstack(*residualParts)
        fInitStateIndices = np.asarray(residualStateIndices, dtype=int)
        if fInitStateIndices.size != f_init_residual.rows:
            raise ValueError("initialization residual/state mapping is inconsistent")
        fInitStateIndices.setflags(write=False)
        # Cached objects are shared between grids, so store them immutable.
        # The state Jacobian is not built here: it dominates construction time
        # and is only needed for linear analyses (see A_sym / A_core).
        return {
            "f": sp.ImmutableMatrix(f), "g": sp.ImmutableMatrix(g),
            "f_init_sym": sp.ImmutableMatrix(f_init_sym),
            "f_init_residual": sp.ImmutableMatrix(f_init_residual),
            "fInitStateIndices": fInitStateIndices,
            "fFunction": self._lambdify(f),
            "gFunction": self._lambdify(g),
            "fInitFunction": self._lambdify(f_init_residual),
        }

    @cached_property
    def A_sym(self) -> sp.Matrix:
        """Symbolic state Jacobian, derived on first use and shared via the model cache."""
        if "A_sym" not in self._modelEntry:
            jacobian = self.f_init_sym.jacobian(self.x)
            if jacobian.has(sp.Derivative):
                raise ValueError("state Jacobian contains unresolved symbolic derivatives")
            self._modelEntry["A_sym"] = sp.ImmutableMatrix(jacobian)
        return self._modelEntry["A_sym"]

    @cached_property
    def A_core(self):
        """Numeric state Jacobian, compiled on first use and shared via the model cache."""
        if "AFunction" not in self._modelEntry:
            self._modelEntry["AFunction"] = self._lambdify(self.A_sym)
        return self._wrap(self._modelEntry["AFunction"], matrix=True)

    def _lambdify(self, expression: sp.Matrix):
        """Compile an expression; arguments are states, references, then parameters."""
        arguments = list(self.x) + list(self.u) + list(self.parameterMap["parameterSymbols"])
        return sp.lambdify(arguments, expression, modules="numpy", cse=True, docstring_limit=0)

    def _compile(self, expression: sp.Matrix, matrix: bool = False):
        return self._wrap(self._lambdify(expression), matrix=matrix)

    def _wrap(self, function: Any, matrix: bool = False):
        """Bind a compiled function to this grid's current parameter values."""
        def numeric(state: Any, *reference: Any):
            stateValues = np.asarray(state, dtype=float).reshape(-1)
            if len(reference) == 1 and np.asarray(reference[0]).size == len(self.u):
                referenceValues = np.asarray(reference[0], dtype=float).reshape(-1)
            else:
                referenceValues = np.asarray(reference, dtype=float).reshape(-1)
            values = np.r_[stateValues, referenceValues, self.parameterMap["parameterValues"]]
            result = np.asarray(function(*values), dtype=float)
            return result if matrix else result.reshape(-1)
        numeric.generatedFunction = function
        return numeric

    def enableNumba(self, *, FastMath: bool = False) -> bool:
        """JIT-compile the time-domain derivative when Numba is available."""
        if hasattr(self, "_numbaDerivative"):
            return True
        try:
            from numba import njit
        except ImportError:
            return False

        compiled = njit(self.f_core.generatedFunction, fastmath=FastMath)

        def f_numeric(state: Any, *reference: Any):
            stateValues = np.asarray(state, dtype=float).reshape(-1)
            if len(reference) == 1 and np.asarray(reference[0]).size == len(self.u):
                referenceValues = np.asarray(reference[0], dtype=float).reshape(-1)
            else:
                referenceValues = np.asarray(reference, dtype=float).reshape(-1)
            values = np.r_[stateValues, referenceValues, self.parameterMap["parameterValues"]]
            return np.asarray(compiled(*values), dtype=float).reshape(-1)

        self.f_numeric = f_numeric
        self._numbaDerivative = compiled
        return True

    def refreshParameters(self, rebuild: bool = False) -> None:
        symbols: list[Any] = list(self.Lsym) + list(self.Rsym)
        values: list[float] = list(self.L) + list(self.R)
        for devices in (self.Vdev, self.Idev):
            for device in devices:
                for parameter in device.p.values():
                    symbols.extend(np.asarray(parameter["sym"], dtype=object).reshape(-1, order="F"))
                    values.extend(np.asarray(parameter["num"], dtype=float).reshape(-1, order="F"))
        valuesArray = np.asarray(values, dtype=float)
        self.parameterMap = {"parameterSymbols": tuple(symbols), "parameterValues": valuesArray}

    def getStateMatrix(self, x0: Any, uref: Any) -> np.ndarray:
        self.refreshParameters()
        return np.asarray(self.A_core(x0, uref), dtype=float)

    def analyzeSmallSignal(self, x0: Any, uref: Any, wBase: float) -> dict[str, Any]:
        A = self.getStateMatrix(x0, uref)
        poles, leftVectors, rightVectors = eig(A, left=True, right=True)
        for i in range(len(poles)):
            pairProduct = np.vdot(leftVectors[:, i], rightVectors[:, i])
            if abs(pairProduct) > 1e-10:
                leftVectors[:, i] /= np.conj(pairProduct)
        participation = np.abs(rightVectors * np.conj(leftVectors))
        participation /= np.maximum(participation.sum(axis=0, keepdims=True), np.finfo(float).eps)
        order = np.argsort(poles.real)[::-1]
        poles, participation = poles[order], participation[:, order]
        rightVectors, leftVectors = rightVectors[:, order], leftVectors[:, order]
        stateNames = [str(symbol) for symbol in self.x]
        dominant = participation.argmax(axis=0)
        tolerance = 1e-7
        modeTable = []
        for i, pole in enumerate(poles):
            stability = "Unstable" if pole.real > tolerance else "Marginal" if abs(pole.real) <= tolerance else "Stable"
            modeTable.append({
                "Mode": i + 1, "Eigenvalue": pole,
                "Frequency_Hz": abs(pole.imag) * wBase / (2 * np.pi),
                "DampingRatio": -pole.real / max(abs(pole), np.finfo(float).eps),
                "Stability": stability, "DominantState": stateNames[dominant[i]],
                "DominantParticipation": participation[dominant[i], i],
                "RealPart": pole.real, "ImaginaryPart": pole.imag,
            })
        return {
            "A": A, "poles": poles, "participation": participation,
            "stateNames": stateNames, "modeTable": modeTable,
            "unstablePoleCount": int(np.sum(poles.real > tolerance)),
            "poleTolerance": tolerance, "rightEigenvectors": rightVectors,
            "leftEigenvectors": leftVectors, "leadingModeTable": modeTable[:12],
        }

    def solvePowerFlow(self, vPref: Any) -> tuple[np.ndarray, dict[str, Any]]:
        vPref = np.asarray(vPref, dtype=float).reshape(-1)
        devices = self.Vdev + self.Idev
        deviceNode = np.r_[np.arange(self.n), np.arange(self.n)]
        Z = self.R + 1j * self.L
        Y = self.A @ np.diag(1 / Z) @ self.A.T
        P, Q, V, theta = sp.symbols("P Q V theta", real=True)
        deviceFunctions = []
        for device in devices:
            powerScale = device.Outputscale / device.Inputscale
            localVoltage = V / device.Outputscale if device.type == "Voltage" else device.Inputscale * V
            equation = sp.Matrix(device.getPowerFlowEquations(
                localVoltage, theta, P / powerScale, Q / powerScale
            ))
            equation = equation.subs({symbol: vPref[self.u.index(symbol)] for symbol in device.uref})
            deviceFunctions.append(sp.lambdify((P, Q, V, theta), equation, "numpy"))
        nd = len(devices)

        def residual(z: np.ndarray) -> np.ndarray:
            magnitude, angle = z[:self.n], z[self.n:2 * self.n]
            active = z[2 * self.n:2 * self.n + nd]
            reactive = z[2 * self.n + nd:]
            voltage = magnitude * np.exp(1j * angle)
            networkPower = voltage * np.conj(Y @ voltage)
            activeNode = np.bincount(deviceNode, weights=active, minlength=self.n)
            reactiveNode = np.bincount(deviceNode, weights=reactive, minlength=self.n)
            parts = [networkPower.real - activeNode, networkPower.imag - reactiveNode]
            for d, function in enumerate(deviceFunctions):
                parts.append(np.asarray(
                    function(active[d], reactive[d], magnitude[deviceNode[d]], angle[deviceNode[d]]),
                    dtype=float,
                ).reshape(-1))
            return np.concatenate(parts)

        z0 = np.r_[np.ones(self.n), np.zeros(self.n + 2 * nd)]
        solution = root(residual, z0, method="hybr", options={"xtol": 1e-10})
        z = solution.x
        magnitude, angle = z[:self.n], z[self.n:2 * self.n]
        active = z[2 * self.n:2 * self.n + nd]
        reactive = z[2 * self.n + nd:]
        busVoltage = magnitude * np.exp(1j * angle)
        info = {
            "exitflag": 1 if solution.success else -1, "success": bool(solution.success),
            "output": {"message": solution.message, "nfev": solution.nfev},
            "residualInfNorm": float(np.linalg.norm(residual(z), np.inf)),
            "busVoltage": busVoltage, "branchCurrent": (self.A.T @ busVoltage) / Z,
            "V": magnitude, "theta": angle, "Pdevice": active, "Qdevice": reactive,
            "deviceNode": deviceNode,
        }
        return z, info

    def getOperatingPoints(self, vPref: Any) -> tuple[np.ndarray, dict[str, Any]]:
        xPowerFlow, powerFlowInfo = self.solvePowerFlow(vPref)
        V = xPowerFlow[:self.n]
        theta = xPowerFlow[self.n:2 * self.n]
        active = xPowerFlow[2 * self.n:4 * self.n]
        reactive = xPowerFlow[4 * self.n:6 * self.n]
        busVoltage = V * np.exp(1j * theta)
        branchCurrent = (self.A.T @ busVoltage) / (self.R + 1j * self.L)
        xInit = np.zeros(len(self.x))
        xInit[:2 * self.b] = np.column_stack((branchCurrent.real, branchCurrent.imag)).reshape(-1)
        nextState = 2 * self.b
        for i, (Vdev, Idev) in enumerate(zip(self.Vdev, self.Idev)):
            for device, offset in ((Vdev, 0), (Idev, self.n)):
                powerScale = device.Outputscale / device.Inputscale
                localV = V[i] / device.Outputscale if device.type == "Voltage" else device.Inputscale * V[i]
                deviceState = np.asarray(device.initFromPowerFlow(
                    localV, theta[i], active[i + offset] / powerScale,
                    reactive[i + offset] / powerScale,
                ), dtype=float).reshape(-1)
                xInit[nextState:nextState + len(device.x)] = deviceState
                nextState += len(device.x)
        self.refreshParameters()
        solution = least_squares(
            lambda state: self.f_init(state, vPref), xInit,
            method="lm" if self._f_init_residual.rows >= len(xInit) else "trf",
            max_nfev=50_000, ftol=1e-11, xtol=1e-11, gtol=1e-11,
        )
        info = {
            "powerFlow": powerFlowInfo, "initialState": xInit,
            "exitflag": 1 if solution.success else -1,
            "output": {"message": solution.message, "nfev": solution.nfev},
            "residualInfNorm": float(np.linalg.norm(solution.fun, np.inf)),
        }
        return solution.x, info

    @staticmethod
    def kronReduction(A: Any, L: Any, R: Any, emptyNodes: Iterable[int]):
        A = np.asarray(A, dtype=float).copy()
        L = np.asarray(L, dtype=float).reshape(-1).copy()
        R = np.asarray(R, dtype=float).reshape(-1).copy()
        for node in sorted(emptyNodes, reverse=True):
            branches = np.flatnonzero(A[node] != 0)
            degree = branches.size
            if degree == 0:
                A = np.delete(A, node, axis=0)
                continue
            neighbors = [int(np.flatnonzero((A[:, branch] != 0) & (np.arange(A.shape[0]) != node))[0]) for branch in branches]
            newColumns, newL, newR = [], [], []
            if degree == 2:
                if neighbors[0] != neighbors[1]:
                    column = np.zeros(A.shape[0]); column[neighbors[0]] = 1; column[neighbors[1]] = -1
                    newColumns.append(column); newL.append(L[branches].sum()); newR.append(R[branches].sum())
            elif degree > 2:
                impedance = R[branches] + 1j * L[branches]
                admittanceSum = np.sum(1 / impedance)
                for i in range(degree - 1):
                    for j in range(i + 1, degree):
                        equivalent = impedance[i] * impedance[j] * admittanceSum
                        column = np.zeros(A.shape[0]); column[neighbors[i]] = 1; column[neighbors[j]] = -1
                        newColumns.append(column); newR.append(equivalent.real); newL.append(equivalent.imag)
            A = np.delete(A, branches, axis=1); L = np.delete(L, branches); R = np.delete(R, branches)
            if newColumns:
                A = np.column_stack((A, *newColumns)); L = np.r_[L, newL]; R = np.r_[R, newR]
            A = np.delete(A, node, axis=0)
        return A, L, R
