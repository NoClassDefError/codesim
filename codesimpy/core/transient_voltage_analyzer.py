import sys
from collections.abc import Iterable, Mapping
from typing import Any, Callable

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares


class TransientVoltageAnalyzer:
    """Split bus voltage into QSS, first-order, and EMT components."""

    _TOLERANCE = 1e-3
    _QSS_RESIDUAL_TOLERANCE = 1e-8
    _SOLVER_TOLERANCE = 1e-12

    def __init__(self, system: Any) -> None:
        self.system = system

    def decompose(
        self,
        result: Mapping[str, Any],
        slowStateNames: Iterable[str],
        *,
        angleStateName: str | None = None,
        angleRate_rad_s: float | Iterable[float] | None = None,
        busNames: str | Iterable[str] | None = None,
        maxSamples: int | None = None,
    ) -> dict[str, Any]:
        """Decompose every sample of a simulated voltage trajectory.

        result: returned by system.simulation
        slowStateNames: string array

        """
        # Preprocessing parameters, get busIndex, slowRates, slow and fast state indices.
        state = np.asarray(result["state"], dtype=float)
        time = np.asarray(result["time_s"], dtype=float).reshape(-1)
        if time.size == 0 or np.any(np.diff(time) <= 0) or state.shape != (time.size, len(self.system.stateNames)):
            raise ValueError("state and time must have matching dimensions and increasing time")
        requestedSlowNames = ([slowStateNames] if isinstance(slowStateNames, str)
                              else list(slowStateNames))
        requiredSlowNames = list(getattr(
            self.system, "qssRequiredSlowStateNames", (),
        ))
        slowNames = requestedSlowNames + [
            name for name in requiredSlowNames if name not in requestedSlowNames
        ]
        if (not requestedSlowNames or len(set(slowNames)) != len(slowNames)
                or any(n not in self.system.stateNames for n in slowNames)):
            raise ValueError("slowStateNames must contain unique, known states")
        slow = np.array([self.system.stateNames.index(n) for n in slowNames])
        held = sorted(set(slow) | (set(range(state.shape[1])) - set(self.system.rlGrid.fInitStateIndices)))
        fast = np.array([i for i in range(state.shape[1]) if i not in held], dtype=int)
        if not fast.size:
            raise ValueError("at least one state must remain fast")
        angleStateName = angleStateName or next((n for n in slowNames if n.lower().startswith("delta")), slowNames[0])
        if angleStateName not in slowNames:
            raise ValueError("angleStateName must be one of slowStateNames")
        selectedBuses = list(self.system.busNames) if busNames is None else ([busNames] if isinstance(busNames, str) else list(busNames))
        if not selectedBuses or any(n not in self.system.busNames for n in selectedBuses):
            raise ValueError("busNames must contain known buses")
        buses = [self.system.busNames.index(n) for n in selectedBuses]
        references = np.asarray(result.get("referenceTrace", []), dtype=float)
        if references.shape != (time.size, len(self.system.referenceNames)):
            references = np.asarray([self.system.getReference(t) for t in time], dtype=float)
        wBase = 2 * np.pi * self.system.base["frequency_Hz"]
        rates = np.asarray([wBase * self.system.rlGrid.f_numeric(x, u)[slow]
                            for x, u in zip(state, references)])
        angleColumn = slowNames.index(angleStateName)
        if angleRate_rad_s is not None:
            rate = np.asarray(angleRate_rad_s, dtype=float)
            rates[:, angleColumn] = rate if rate.ndim else float(rate)
        if maxSamples is not None and maxSamples < 1:
            raise ValueError("maxSamples must be positive")
        sampleIndices = (np.arange(time.size) if maxSamples is None or maxSamples >= time.size
                         else np.linspace(0, time.size - 1, maxSamples, dtype=int))
        slowColumns = {index: column for column, index in enumerate(slow)}

        sampleCount = sampleIndices.size
        progressStep = max(1, int(np.ceil(sampleCount / 20)))

        def reportProgress(message: str) -> None:
            print(f"[transient voltage] {message}", file=sys.stderr, flush=True)

        reportProgress(
            f"starting decomposition of {sampleCount}/{time.size} samples"
        )

        def voltage(x, u):
            flat = np.asarray(self.system.rlGrid.g_numeric(x, u)[1], dtype=float)
            return (flat[::2] + 1j * flat[1::2])[buses]
        # Start solving the 3 components
        stop = sampleIndices[-1] + 1
        lastEmtPercent = -1

        def reportEmtProgress(fraction: float) -> None:
            nonlocal lastEmtPercent
            percent = min(100, max(0, int(fraction * 20) * 5))
            if percent > lastEmtPercent:
                reportProgress(f"running EMT replay ({percent}%)")
                lastEmtPercent = percent

        reportEmtProgress(0.0)
        emtState = self._emt(
            state[:stop], time[:stop], wBase, fast, references[:stop],
            progress=reportEmtProgress,
        )[sampleIndices]
        reportEmtProgress(1.0)
        reportProgress("EMT replay complete; solving QSS samples")
        qssState, firstState = [], []
        actual, qss, firstOrder, emt = [], [], [], []
        residualNorm, condition, available, converged = [], [], [], []
        guess = None
        heldNames = [self.system.stateNames[i] for i in held]
        for completed, (index, emtSample) in enumerate(
            zip(sampleIndices, emtState), start=1,
        ):
            sample, reference = state[index], references[index]
            heldRates = np.array([rates[index, slowColumns[i]] / wBase if i in slowColumns else 0.0 for i in held])
            try:
                zero, first = self._qss(sample, fast, reference, guess, heldRates)
            except (RuntimeError, ValueError, np.linalg.LinAlgError):
                missingState = np.full_like(sample, np.nan)
                missingVoltage = np.full(len(buses), np.nan + 1j * np.nan)
                qssState.append(missingState)
                firstState.append(missingState.copy())
                actual.append(voltage(sample, reference))
                qss.append(missingVoltage)
                firstOrder.append(missingVoltage.copy())
                emt.append(missingVoltage.copy())
                residualNorm.append(np.inf)
                condition.append(np.inf)
                available.append(False)
                converged.append(False)
                if completed % progressStep == 0 or completed == sampleCount:
                    reportProgress(
                        f"processed {completed}/{sampleCount} QSS samples "
                        f"({100 * completed // sampleCount}%)"
                    )
                continue
            converged.append(True)
            guess = zero
            zeroState, correctedState = sample.copy(), sample.copy()
            zeroState[fast], correctedState[fast] = zero, first
            qssState.append(zeroState)
            firstState.append(correctedState)
            actualVoltage, qssVoltage = voltage(sample, reference), voltage(zeroState, reference)
            correction = voltage(correctedState, reference) - qssVoltage
            f1, _, jacobian, _ = self.get_functions(zeroState, reference, heldNames)
            linearization = self.system.rlGrid.getStateMatrix(zeroState, reference)
            usable = np.isfinite(linearization).all() and np.isfinite(jacobian).all()
            cond = float(np.linalg.cond(jacobian)) if usable else np.inf
            available.append(bool(np.isfinite(cond)))
            condition.append(cond)
            residualNorm.append(float(np.linalg.norm(f1, ord=np.inf)))
            if not available[-1]:
                correction = np.full(len(buses), np.nan + 1j * np.nan)
            actual.append(actualVoltage)
            qss.append(qssVoltage)
            firstOrder.append(correction)
            emt.append(voltage(emtSample, reference) - qssVoltage - correction)
            if completed % progressStep == 0 or completed == sampleCount:
                reportProgress(
                    f"processed {completed}/{sampleCount} QSS samples "
                    f"({100 * completed // sampleCount}%)"
                )
        actual, qss, firstOrder, emt = map(np.asarray, (actual, qss, firstOrder, emt))
        reconstructed = qss + firstOrder + emt
        decomposition = {
            "time_s": time[sampleIndices], "sourceSampleCount": time.size,
            "sampleIndices": sampleIndices, "busNames": selectedBuses,
            "requestedSlowStateNames": requestedSlowNames,
            "slowStateNames": slowNames,
            "fastStateNames": [self.system.stateNames[i] for i in fast],
            "angleStateName": angleStateName,
            "angleRate_rad_s": rates[sampleIndices, angleColumn],
            "slowStateRates_per_s": rates[sampleIndices],
            "actualVoltage": actual, "qssVoltage": qss,
            "firstOrderError": firstOrder, "emtVoltage": emt,
            "reconstructedVoltage": reconstructed,
            "reconstructionError": actual - reconstructed,
            "emtState": emtState, "qssState": np.asarray(qssState),
            "firstOrderState": np.asarray(firstState),
            "qssConverged": np.asarray(converged),
            "qssResidualNorm": np.asarray(residualNorm),
            "fastJacobianCondition": np.asarray(condition),
            "firstOrderAvailable": np.asarray(available),
        }
        self.latestDecomposition = decomposition
        reportProgress(
            f"complete; {sum(converged)}/{sampleCount} QSS samples converged"
        )
        return decomposition

    def _emt(
        self,
        state,
        time,
        wBase,
        fast,
        referenceTrace=None,
        progress: Callable[[float], None] | None = None,
    ):
        """Replay fast states using piecewise-linear held-state inputs."""
        state, time = np.asarray(state, dtype=float), np.asarray(time, dtype=float)
        fast = np.asarray(fast, dtype=int)
        fastSet = set(fast)
        held = np.asarray(
            [i for i in range(state.shape[1]) if i not in fastSet], dtype=int,
        )
        references = (np.asarray(referenceTrace, dtype=float) if referenceTrace is not None
                      else np.asarray([self.system.getReference(t) for t in time]))
        emtState = state.copy()
        if time.size > 1:
            # Prepare the line segments once. At each solver evaluation, locate
            # one interval and interpolate every held state/reference together.
            # This avoids a separate scalar interpolation for every input column.
            duration = np.diff(time)
            heldValues = state[:, held]
            heldSlopes = np.diff(heldValues, axis=0) / duration[:, None]
            referenceSlopes = np.diff(references, axis=0) / duration[:, None]
            sample = np.empty(state.shape[1])

            def derivative(t, x):
                if progress is not None:
                    progress((t - time[0]) / (time[-1] - time[0]))
                interval = min(
                    max(int(np.searchsorted(time, t, side="right")) - 1, 0),
                    time.size - 2,
                )
                offset = t - time[interval]
                sample[fast] = x
                sample[held] = heldValues[interval] + offset * heldSlopes[interval]
                reference = references[interval] + offset * referenceSlopes[interval]
                return wBase * np.asarray(
                    self.system.rlGrid.f_numeric(sample, reference), dtype=float,
                )[fast]

            solution = solve_ivp(
                derivative, (time[0], time[-1]), state[0, fast], t_eval=time,
                max_step=5e-3 / wBase, rtol=1e-6, atol=1e-9,
            )
            if not solution.success:
                raise RuntimeError(f"EMT simulation failed: {solution.message}")
            emtState[:, fast] = solution.y.T
        return emtState

    def qss_map(
        self,
        operatingPoint: Mapping[str, Any],
        scanStates: Mapping[str, Iterable[float]],
        *,
        heldStateNames: Iterable[str] = (),
        offsets: Mapping[str, float] | None = None,
        busNames: str | Iterable[str] | None = None,
        modeFunctions: Mapping[str, Callable[[np.ndarray, np.ndarray], bool]] | None = None,
        returnStates: bool = False,
    ) -> dict[str, Any]:
        """Zeroth-order QSS voltage map over a grid of frozen slow states.

        For every point of the Cartesian grid ``scanStates`` (e.g.
        ``{"delta_vsg": d, "theta_gfl": t}``), the scanned states are set to
        ``value + offsets[name]``. They are held together with
        ``heldStateNames``, ``system.qssRequiredSlowStateNames`` and every
        state without an initialization residual (frame angles). The
        remaining fast states are solved from ``f_fast = 0``. This is the
        model-based ``v_t = f(delta, theta)`` of the zeroth-order QSS model.

        ``operatingPoint`` supplies the base ``state`` and ``reference``, for
        example from ``system.initialize`` or one simulation sample. Use
        ``offsets`` to express the scan in grid-relative angles. For a
        ``VSGCC`` the grid-relative internal angle is
        ``delta + theta_vsg - theta_grid``, and for a PLL it is
        ``theta_pll - theta_grid``.

        ``modeFunctions`` maps a label to ``f(state, reference) -> bool``.
        By default it detects converter current limiting (``|iref| > Imax``
        on devices with ``irefd``/``irefq`` states) and GFL FRT
        (``|v_bus| < Vth`` on current devices with a ``Vth`` parameter).
        ``modeCode`` packs these as 0 normal, 1 FRT, 2 limiting, 3 both.
        """
        system, grid = self.system, self.system.rlGrid
        names = list(scanStates)
        axes = [np.asarray(scanStates[name], dtype=float).reshape(-1) for name in names]
        offsets = dict(offsets or {})
        if not names or any(name not in system.stateNames for name in names):
            raise ValueError("scanStates must name known states")
        if set(offsets) - set(names):
            raise ValueError("offsets may only refer to scanned states")
        baseState = np.asarray(operatingPoint["state"], dtype=float).reshape(-1).copy()
        reference = np.asarray(operatingPoint["reference"], dtype=float).reshape(-1)

        requested = names + [n for n in heldStateNames if n not in names]
        slowNames = requested + [
            n for n in getattr(system, "qssRequiredSlowStateNames", ()) if n not in requested
        ]
        if any(n not in system.stateNames for n in slowNames):
            raise ValueError("heldStateNames must contain known states")
        slow = {system.stateNames.index(n) for n in slowNames}
        held = slow | (set(range(baseState.size)) - set(grid.fInitStateIndices))
        fast = np.array([i for i in range(baseState.size) if i not in held], dtype=int)
        if not fast.size:
            raise ValueError("at least one state must remain fast")
        heldNames = [system.stateNames[i] for i in sorted(held)]
        scanIndices = [system.stateNames.index(n) for n in names]

        selectedBuses = (list(system.busNames) if busNames is None
                         else [busNames] if isinstance(busNames, str) else list(busNames))
        if any(n not in system.busNames for n in selectedBuses):
            raise ValueError("busNames must contain known buses")
        buses = [system.busNames.index(n) for n in selectedBuses]
        if modeFunctions is None:
            modeFunctions = self._defaultModeFunctions()

        shape = tuple(axis.size for axis in axes)
        voltage = np.full((*shape, len(buses)), np.nan + 1j * np.nan)
        converged = np.zeros(shape, dtype=bool)
        residual = np.full(shape, np.inf)
        flags = {label: np.zeros(shape, dtype=bool) for label in modeFunctions}
        states = np.full((*shape, baseState.size), np.nan) if returnStates else None
        solutions: dict[tuple[int, ...], np.ndarray] = {}
        grid.refreshParameters()
        baselineFast = baseState[fast].copy()
        previous = None
        for index in self._serpentine(shape):
            candidate = baseState.copy()
            for axisNumber, stateIndex in enumerate(scanIndices):
                name = names[axisNumber]
                candidate[stateIndex] = axes[axisNumber][index[axisNumber]] + offsets.get(name, 0.0)

            def functions(x, candidate=candidate):
                candidate[fast] = x
                return self.get_functions(candidate, reference, heldNames)

            seeds = [seed for seed in (
                previous,
                solutions.get((index[0] - 1, *index[1:])) if index[0] else None,
                baselineFast,
            ) if seed is not None]
            try:
                solution, pointResidual = self._solveZeroOrder(functions, seeds)
            except RuntimeError:
                previous = None
                continue
            candidate[fast] = solution
            solutions[index] = previous = solution
            converged[index], residual[index] = True, pointResidual
            flat = np.asarray(grid.g_numeric(candidate, reference)[1], dtype=float)
            voltage[index] = (flat[::2] + 1j * flat[1::2])[buses]
            for label, function in modeFunctions.items():
                flags[label][index] = bool(function(candidate, reference))
            if states is not None:
                states[index] = candidate

        frt = np.zeros(shape, dtype=bool)
        limit = np.zeros(shape, dtype=bool)
        for label, values in flags.items():
            if label.startswith("frt"):
                frt |= values
            elif label.startswith("currentLimit"):
                limit |= values
        modeCode = np.where(converged, frt.astype(int) + 2 * limit.astype(int), -1)
        result = {
            "scanStateNames": names, "axes": axes, "offsets": offsets,
            "busNames": selectedBuses, "heldStateNames": heldNames,
            "fastStateNames": [system.stateNames[i] for i in fast],
            "voltage": voltage, "voltageMagnitude": np.abs(voltage),
            "converged": converged, "residualNorm": residual,
            "modeFlags": flags, "modeCode": modeCode,
            "modeLabels": ["normal", "frt", "limit", "both"],
        }
        if states is not None:
            result["state"] = states
        self.latestQssMap = result
        return result

    def _defaultModeFunctions(self) -> dict[str, Callable[[np.ndarray, np.ndarray], bool]]:
        system, grid = self.system, self.system.rlGrid
        functions: dict[str, Callable[[np.ndarray, np.ndarray], bool]] = {}
        for node, (voltageDevice, currentDevice) in enumerate(zip(grid.Vdev, grid.Idev)):
            for device in (voltageDevice, currentDevice):
                stateNames = [str(symbol) for symbol in device.x]
                limitStates = [f"irefd{device.index}", f"irefq{device.index}"]
                if "Imax" in device.p and all(n in stateNames for n in limitStates):
                    indices = [system.stateNames.index(n) for n in limitStates]
                    functions[f"currentLimit{device.index}"] = (
                        lambda state, reference, i=indices, d=device:
                        np.hypot(state[i[0]], state[i[1]]) > float(d.p["Imax"]["num"])
                    )
                if device.type == "Current" and "Vth" in device.p:
                    def frt(state, reference, node=node, d=device):
                        flat = np.asarray(grid.g_numeric(state, reference)[1], dtype=float)
                        magnitude = d.Inputscale * np.hypot(flat[2 * node], flat[2 * node + 1])
                        return magnitude < float(d.p["Vth"]["num"])
                    functions[f"frt{device.index}"] = frt
        return functions

    @staticmethod
    def _serpentine(shape: tuple[int, ...]):
        """Visit grid indices so consecutive points are neighbours (warm starts)."""
        if len(shape) == 1:
            yield from ((i,) for i in range(shape[0]))
            return
        for outer in np.ndindex(shape[:-1]):
            inner = range(shape[-1]) if sum(outer) % 2 == 0 else range(shape[-1] - 1, -1, -1)
            for i in inner:
                yield (*outer, i)

    def _solveZeroOrder(self, functions, seeds) -> tuple[np.ndarray, float]:
        """Solve ``f_fast = 0`` from several seeds; return the first acceptable root."""
        unique: list[np.ndarray] = []
        for seed in seeds:
            seed = np.asarray(seed, dtype=float)
            if not any(np.array_equal(seed, other) for other in unique):
                unique.append(seed)
        zero = None
        bestResidual = np.inf
        for seed in unique:
            try:
                trial = least_squares(
                    lambda x: functions(x)[0], seed,
                    jac=lambda x: functions(x)[2],
                    xtol=self._SOLVER_TOLERANCE,
                    ftol=self._SOLVER_TOLERANCE,
                    gtol=self._SOLVER_TOLERANCE,
                )
            except (FloatingPointError, ValueError, np.linalg.LinAlgError):
                continue
            residual = float(np.linalg.norm(trial.fun, ord=np.inf))
            if residual < bestResidual:
                zero, bestResidual = trial, residual
            if np.isfinite(residual) and residual <= self._QSS_RESIDUAL_TOLERANCE:
                break
        if (zero is None or not np.isfinite(bestResidual)
                or bestResidual > self._QSS_RESIDUAL_TOLERANCE):
            raise RuntimeError("zero-order QSS solve failed")
        return zero.x, bestResidual

    def get_functions(self, state, reference, slowStateNames):
        """
        Get f1 f2 by system.rlGrid.f_init.
        Get (partial f_1/partial x_2) and (partial f_1/partial x_1) symbolically, and substitude values
        """
        grid = self.system.rlGrid
        names = [slowStateNames] if isinstance(slowStateNames, str) else list(slowStateNames)
        if not names or len(set(names)) != len(names) or any(n not in self.system.stateNames for n in names):
            raise ValueError("slowStateNames must contain unique, known states")
        slow = [self.system.stateNames.index(n) for n in names]
        fast = [i for i in range(len(grid.x)) if i not in slow]
        if not fast:
            raise ValueError("at least one state must remain fast")

        grid.refreshParameters()
        cache = getattr(self, "_functionCache", {})
        key = tuple(slow)
        if key not in cache:
            # Restore dynamic rows omitted by the compiled initialization residual.
            equations = grid.f_init_sym.as_mutable()
            for index, residual in zip(grid.fInitStateIndices, grid._f_init_residual):
                equations[index] = residual
            jacobian = equations.extract(fast, [0]).jacobian(grid.x)
            cache[key] = (grid._compile(equations), grid._compile(jacobian, matrix=True))
            self._functionCache = cache
        equation, derivative = cache[key]
        values = equation(state, reference)
        jacobian = derivative(state, reference)
        return values[fast], values[slow], jacobian[:, fast], jacobian[:, slow]

    def _qss(
        self,
        state: np.ndarray,
        fast: np.ndarray,
        reference: np.ndarray,
        guess: np.ndarray | None,
        slowRates: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Consider a state space equation set, dot{x}_1 = f1(x1, x2), dot{x}_2 = f2(x1, x2)
        x1 is fast and x2 is slow, both are vectors.

        Given the traj of x2(t), and dot{x}_2(t), get the zero-order QSS traj of x1_zero and the first-order QSS traj of x1_first.

        First solve the usual QSS equation:

        f_1(x_1,x_2)=0.

        then x1_zero is solved.

        To include the first-order effect of the slow motion dot{x}_2, use the implicit equation

        f_1(x_1,x_2)+   ((partial f_1/partial x_2)/(partial f_1/partial x_1))dot{x}_2 = 0
        At each time point, insert the known x_2(t) and dot{x}_2(t), then solve this equation for x_1(t).
        """

        fast = np.asarray(fast, dtype=int).reshape(-1)
        slowNames = [name for i, name in enumerate(self.system.stateNames) if i not in fast]
        candidate = np.asarray(state, dtype=float).copy()
        simulatedFastState = candidate[fast].copy()
        slowRate = (self.get_functions(candidate, reference, slowNames)[1]
                    if slowRates is None else np.asarray(slowRates, dtype=float))

        def functions(x):
            candidate[fast] = x
            return self.get_functions(candidate, reference, slowNames)

        # Continuation from the previous QSS point is normally the quickest and
        # most consistent seed. Across a limiter transition it can remain on a
        # stale piecewise branch, so retry from the simulated EMT state before
        # declaring that no equilibrium exists.
        seeds = [simulatedFastState] if guess is None else [
            np.asarray(guess, dtype=float), simulatedFastState,
        ]
        x1_zero, _ = self._solveZeroOrder(functions, seeds)

        def firstResidual(x):
            f1, _, pf1x1, pf1x2 = functions(x)
            return f1 + np.linalg.solve(pf1x1, pf1x2 @ slowRate)

        try:
            first = least_squares(firstResidual, x1_zero, xtol=self._TOLERANCE)
        except (np.linalg.LinAlgError, ValueError):
            first = None
        if first is not None and first.success and np.linalg.norm(first.fun, ord=np.inf) <= self._TOLERANCE:
            x1_first = first.x
        else:
            _, _, pf1x1, pf1x2 = functions(x1_zero)
            slope = np.linalg.lstsq(pf1x1, pf1x2 @ slowRate, rcond=None)[0]
            x1_first = x1_zero - np.linalg.lstsq(pf1x1, slope, rcond=None)[0]
        return x1_zero, x1_first
