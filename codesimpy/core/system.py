"""Shared construction, initialization, and time-domain workflow."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from time import perf_counter
from typing import Any

import numpy as np
import sympy as sp
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares, root

from .rl_grid import RLGrid
from .small_signal_analyzer import SmallSignalAnalyzer
from .transient_voltage_analyzer import TransientVoltageAnalyzer


class System(ABC):
    """Base class for a complete CodeSim network model.

    Public time values are seconds; ``RLGrid`` equations use normalized time
    ``tau = wBase * t``. Python dictionaries replace MATLAB structs/maps/tables.
    """

    def __init__(
        self, name: str, network: Mapping[str, Any], devices: Mapping[str, Any],
        base: Mapping[str, Any],
        referenceMap: Mapping[str, float | Callable[[float], float]],
    ) -> None:
        A = np.asarray(network["A"], dtype=float)
        L = np.asarray(network["L"], dtype=float).reshape(-1)
        R = np.asarray(network["R"], dtype=float).reshape(-1)
        Vdev, Idev = list(devices["Vdev"]), list(devices["Idev"])
        busNames = list(network["busNames"])
        self.name = str(name)
        self.network = network
        self.devices = devices
        self.base = dict(base)
        self.solverSettings = {
            "method": "RK45",
            "max_step": 5e-3 / (2 * np.pi * self.base["frequency_Hz"]),
            "rtol": 1e-6,
            "atol": 1e-9,
        }
        self.parameters: dict[str, Any] = {}
        self.parameterNames: list[str] = []
        self.eventStartTime_s: float | None = None  # None disables event detection.
        self.eventDirection = 0.0  # -1: falling, 0: either, +1: rising crossing.
        self.eventName = "event"  # Label recorded in the simulation result.
        self.eventTime_s = np.inf  # Exact detected time; inf means not triggered.
        self.retainedNodeIndices = [i for i, device in enumerate(Vdev) if device is not None]
        self.busNames = [str(busNames[i]) for i in self.retainedNodeIndices]
        self.rlGrid = RLGrid(
            A, L, R, self.base["Vbase"], self.base["Sbase"],
            Vdev, Idev, self.name,
        )
        self.referenceNames = [str(symbol) for symbol in self.rlGrid.u]
        self.stateNames = [str(symbol) for symbol in self.rlGrid.x]
        self.referenceMap = dict(referenceMap)
        self.getReference()
        self.smallSignal = SmallSignalAnalyzer(self)
        self.transientVoltage = TransientVoltageAnalyzer(self)
        from ..api.output_json_factory import OutputJsonFactory
        self.outputJsonFactory = OutputJsonFactory(self)

    def setReference(self, name: str, value: float | Callable[[float], float]) -> None:
        self.referenceMap[name] = value

    def getReference(self, time_s: float | None = None, source: Any = None):
        source = self.referenceMap if source is None else source
        if isinstance(source, Mapping):
            entries = [source[name] for name in self.referenceNames]
        else:
            entries = list(source)
        if time_s is None:
            return entries
        return np.asarray([entry(time_s) if callable(entry) else entry for entry in entries], dtype=float)

    def initialize(
        self, time_s: float = 0.0, *, Reference: Any = None,
        ResidualTolerance: float = 1e-4,
    ) -> dict[str, Any]:
        reference = self.getReference(time_s) if Reference is None else np.asarray(Reference, dtype=float)
        self.rlGrid.refreshParameters()
        state, info = self.rlGrid.getOperatingPoints(reference)
        if info["exitflag"] <= 0 or info["residualInfNorm"] >= ResidualTolerance or not np.isfinite(state).all():
            raise RuntimeError(
                f"initialization failed: exitflag={info['exitflag']}, residual={info['residualInfNorm']:.3e}"
            )
        powerFlow = info.get("powerFlow")
        if powerFlow and (powerFlow["exitflag"] <= 0 or powerFlow["residualInfNorm"] >= ResidualTolerance):
            raise RuntimeError("power-flow initialization failed")
        return {
            "state": np.real(state).reshape(-1), "reference": np.asarray(reference).reshape(-1),
            "time_s": float(time_s), "initialization": info,
        }

    def scanPQ(
        self, branchIndex: int, voltage_pu: Any, delta_deg: Any, *,
        Direction: str = "from", Time_s: float = 0.0, Reference: Any = None,
        ResidualTolerance: float = 1e-4,
    ) -> dict[str, Any]:
        """Scan the line-facing subsystem power surface.

        ``branchIndex`` remains one-based to match existing CodeSim models.
        """
        started = perf_counter()
        A = np.asarray(self.network["A"], dtype=float)
        branch = int(branchIndex) - 1
        voltage_pu = np.asarray(voltage_pu, dtype=float).reshape(-1)
        delta_deg = np.asarray(delta_deg, dtype=float).reshape(-1)
        direction = Direction.lower()
        incidence = A[:, branch]
        positive, negative = np.flatnonzero(incidence > 0), np.flatnonzero(incidence < 0)
        if np.count_nonzero(incidence) != 2 or not positive.size or not negative.size:
            raise ValueError("the scanned branch must join one from bus and one to bus")
        fromNode, toNode = int(positive[0]), int(negative[0])
        systemNode, scanNode = {
            "from": (fromNode, toNode), "to": (toNode, fromNode)
        }[direction]

        remaining = np.delete(A, branch, axis=1)
        component = np.zeros(A.shape[0], dtype=bool); component[systemNode] = True
        while True:
            touched = np.any(remaining[component] != 0, axis=0)
            adjacent = np.any(remaining[:, touched] != 0, axis=1) if touched.any() else component.copy()
            expanded = component | adjacent
            if np.array_equal(expanded, component): break
            component = expanded
        if component[scanNode]:
            raise ValueError("the scanned branch must separate two subsystems when removed")
        componentNodes = np.flatnonzero(component)
        systemLocalIndex = int(np.flatnonzero(componentNodes == systemNode)[0])
        internalBranches = np.asarray([
            i for i in range(A.shape[1]) if i != branch and np.any(A[component, i] != 0)
        ], dtype=int)
        Z = np.asarray(self.network["R"], dtype=float).reshape(-1) + 1j * np.asarray(self.network["L"], dtype=float).reshape(-1)
        componentA = A[np.ix_(componentNodes, internalBranches)]
        Y = componentA @ np.diag(1 / Z[internalBranches]) @ componentA.T

        reference = self.getReference(Time_s) if Reference is None else np.asarray(Reference, dtype=float).reshape(-1)
        operatingPoint = self.initialize(Time_s, Reference=reference, ResidualTolerance=ResidualTolerance)
        powerFlow = operatingPoint["initialization"]["powerFlow"]
        originalVdev, originalIdev = list(self.devices["Vdev"]), list(self.devices["Idev"])
        activeNodes = np.asarray([i for i, device in enumerate(originalVdev) if device is not None], dtype=int)
        deviceCells = [originalVdev[i] for i in activeNodes] + [originalIdev[i] for i in activeNodes]
        deviceNodes = np.r_[activeNodes, activeNodes]
        deviceIndices = np.arange(len(deviceCells))
        keep = component[deviceNodes]
        deviceCells = [device for device, retained in zip(deviceCells, keep) if retained]
        deviceNodes, deviceIndices = deviceNodes[keep], deviceIndices[keep]
        nodeLookup = {node: i for i, node in enumerate(componentNodes)}
        deviceLocalNodes = np.asarray([nodeLookup[int(node)] for node in deviceNodes], dtype=int)
        P, Q, V, theta = sp.symbols("P Q V theta", real=True)
        deviceFunctions = []
        for device in deviceCells:
            powerScale = device.Outputscale / device.Inputscale
            localVoltage = V / device.Outputscale if device.type == "Voltage" else device.Inputscale * V
            equation = sp.Matrix(device.getPowerFlowEquations(localVoltage, theta, P / powerScale, Q / powerScale))
            equation = equation.subs({symbol: reference[self.rlGrid.u.index(symbol)] for symbol in device.uref})
            deviceFunctions.append(sp.lambdify((P, Q, V, theta), equation, "numpy"))

        nodeCount, deviceCount = componentNodes.size, len(deviceCells)
        initialVoltage, initialTheta = np.ones(nodeCount), np.zeros(nodeCount)
        retainedLookup = {node: i for i, node in enumerate(self.retainedNodeIndices)}
        for local, original in enumerate(componentNodes):
            if int(original) in retainedLookup:
                index = retainedLookup[int(original)]
                initialVoltage[local], initialTheta[local] = powerFlow["V"][index], powerFlow["theta"][index]
        initialGuess = np.r_[initialVoltage, initialTheta,
                             powerFlow["Pdevice"][deviceIndices], powerFlow["Qdevice"][deviceIndices]]

        def subsystemResidual(z: np.ndarray, scanVoltage: complex) -> np.ndarray:
            magnitude, angle = z[:nodeCount], z[nodeCount:2 * nodeCount]
            active = z[2 * nodeCount:2 * nodeCount + deviceCount]
            reactive = z[2 * nodeCount + deviceCount:]
            voltage = magnitude * np.exp(1j * angle)
            current = Y @ voltage
            current[systemLocalIndex] += (voltage[systemLocalIndex] - scanVoltage) / Z[branch]
            devicePower = np.zeros(nodeCount, complex)
            np.add.at(devicePower, deviceLocalNodes, active + 1j * reactive)
            mismatch = voltage * np.conj(current) - devicePower
            parts = [mismatch.real, mismatch.imag]
            for i, function in enumerate(deviceFunctions):
                node = deviceLocalNodes[i]
                parts.append(np.asarray(function(active[i], reactive[i], magnitude[node], angle[node]), dtype=float).reshape(-1))
            return np.concatenate(parts)

        deltaGrid, voltageGrid = np.meshgrid(delta_deg, voltage_pu)
        power = np.full(voltageGrid.shape, np.nan + 1j * np.nan)
        exitflag = np.zeros(voltageGrid.shape, dtype=int)
        residualInfNorm = np.full(voltageGrid.shape, np.inf)
        guess = initialGuess.copy()
        for index in np.ndindex(voltageGrid.shape):
            scanVoltage = voltageGrid[index] * np.exp(1j * np.deg2rad(deltaGrid[index]))
            solution = root(lambda z: subsystemResidual(z, scanVoltage), guess, method="hybr", options={"xtol": 1e-10, "maxfev": 20_000})
            norm = float(np.linalg.norm(solution.fun, np.inf))
            residualInfNorm[index] = norm; exitflag[index] = 1 if solution.success else -1
            if solution.success and norm < ResidualTolerance and np.isfinite(solution.x).all():
                magnitude, angle = solution.x[:nodeCount], solution.x[nodeCount:2 * nodeCount]
                componentVoltage = magnitude * np.exp(1j * angle)
                lineCurrent = (componentVoltage[systemLocalIndex] - scanVoltage) / Z[branch]
                power[index] = scanVoltage * np.conj(lineCurrent); guess = solution.x
            else:
                guess = initialGuess.copy()
        busNames = list(self.network["busNames"])
        return {
            "branchIndex": branchIndex, "direction": direction,
            "systemBus": str(busNames[systemNode]), "scanBus": str(busNames[scanNode]),
            "systemBusIndices": (componentNodes + 1).tolist(),
            "systemBusNames": [str(busNames[i]) for i in componentNodes],
            "voltage_pu": voltageGrid, "delta_deg": deltaGrid,
            "activePower_pu": power.real, "reactivePower_pu": power.imag,
            "converged": np.isfinite(power), "exitflag": exitflag,
            "residualInfNorm": residualInfNorm, "reference": reference,
            "time_s": Time_s, "initialization": operatingPoint["initialization"],
            "scanTime_s": perf_counter() - started,
        }

    def simulate(
        self, time_s: Any, *, InitialState: Any = None,
        SolverSettings: Mapping[str, Any] | None = None,
        Breakpoints_s: Any = (),
        ReferenceMap: Any = None, saveSnapshot: bool = True,
    ) -> dict[str, Any]:
        started = perf_counter()
        time_s = np.asarray(time_s, dtype=float).reshape(-1)
        if self.eventStartTime_s is not None:
            self.eventTime_s = np.inf
        references = self.getReference(source=ReferenceMap)
        initialization = None
        if InitialState is None:
            point = self.initialize(time_s[0], Reference=self.getReference(time_s[0], references))
            InitialState, initialization = point["state"], point["initialization"]
        solverSettings = dict(self.solverSettings)
        solverSettings.update(SolverSettings or {})
        reserved = {"args", "dense_output", "events", "t_eval"} & solverSettings.keys()
        if reserved:
            raise ValueError(
                f"solver settings managed by System: {', '.join(sorted(reserved))}"
            )
        self.rlGrid.refreshParameters()
        state, time_s, events = self.integrate(
            time_s, InitialState, references, solverSettings, Breakpoints_s,
        )
        networkSignals = self.calculateNetworkSignals(time_s, state, references)
        signals = self.calculateSignals(time_s, state, networkSignals)
        result = {
            "time_s": time_s, "state": state, "stateNames": self.stateNames,
            "signals": signals, "referenceNames": self.referenceNames,
            "referenceTrace": networkSignals["referenceTrace"],
            "initialization": initialization, "events": events,
            "parameters": self.parameters,
            "simulationTime_s": perf_counter() - started,
        }
        if self.eventName == "faultClearing":
            result["clearingTime_s"] = self.eventTime_s
        if saveSnapshot:
            _, result["frontendDescriptor"] = self.outputJsonFactory.saveSnapshot(result)
        return result

    def integrate(
        self, time_s: Any, initialState: Any, references: Any,
        solverSettings: Mapping[str, Any], breakpoints_s: Any = (),
    ):
        time_s = np.asarray(time_s, dtype=float).reshape(-1)
        initialState = np.asarray(initialState, dtype=float).reshape(-1)
        breakpoints = np.unique(np.asarray(breakpoints_s, dtype=float).reshape(-1))
        breakpoints = breakpoints[
            np.isfinite(breakpoints)
            & (breakpoints > time_s[0])
            & (breakpoints < time_s[-1])
        ]
        state = np.empty((time_s.size, initialState.size)); state[0] = initialState
        currentState, currentTime = initialState.copy(), time_s[0]
        events = {"name": [], "time_s": [], "state": []}
        chunkStart = 0
        wBase = 2 * np.pi * self.base["frequency_Hz"]

        def derivative(t: float, value: np.ndarray) -> np.ndarray:
            reference = self.getReference(t, references)
            return wBase * np.asarray(
                self.rlGrid.f_numeric(value, reference), dtype=float
            )

        def emitChunk(start: int, stop: int) -> None:
            chunkTime = time_s[start:stop]
            chunkState = state[start:stop]
            networkSignals = self.calculateNetworkSignals(
                chunkTime, chunkState, references
            )
            signals = self.calculateSignals(chunkTime, chunkState, networkSignals)
            self.outputJsonFactory.writeSimulationChunk(
                chunkTime, chunkState, signals
            )

        eventPending = self.eventStartTime_s is not None
        eventStart = [] if self.eventStartTime_s is None else [self.eventStartTime_s]
        boundaries = np.r_[breakpoints, eventStart, time_s[-1]]
        if self.outputJsonFactory.streaming:
            chunkSize = max(1, int(self.outputJsonFactory.chunkSize))
            chunkEnds = np.arange(chunkSize - 1, time_s.size, chunkSize)
            boundaries = np.r_[boundaries, time_s[chunkEnds]]
        boundaries = np.unique(boundaries)
        boundaries = boundaries[
            np.isfinite(boundaries)
            & (boundaries > currentTime)
            & (boundaries <= time_s[-1])
        ]
        nextOutput = 1

        for boundary in boundaries:
            while currentTime < boundary:
                eventActive = (
                    eventPending and self.eventStartTime_s <= currentTime
                )
                scipyEvent = None
                if eventActive:
                    def scipyEvent(t, value):
                        return self.eventHandler(t, value)
                    scipyEvent.terminal = True
                    scipyEvent.direction = self.eventDirection

                solution = solve_ivp(
                    derivative, (currentTime, float(boundary)), currentState,
                    dense_output=True, events=scipyEvent, **solverSettings,
                )
                if not solution.success:
                    raise RuntimeError(
                        f"simulation integration failed at {solution.t[-1]:.9g} s: "
                        f"{solution.message}"
                    )
                if not np.isfinite(solution.y).all():
                    raise FloatingPointError(
                        f"simulation produced nonfinite states at {solution.t[-1]:.9g} s"
                    )

                currentTime = float(solution.t[-1])
                currentState = solution.y[:, -1]
                stopOutput = int(np.searchsorted(time_s, currentTime, side="right"))
                if stopOutput > nextOutput:
                    targets = time_s[nextOutput:stopOutput]
                    state[nextOutput:stopOutput] = solution.sol(targets).T
                    nextOutput = stopOutput

                if not eventActive or not solution.t_events[0].size:
                    break
                currentTime = float(solution.t_events[0][0])
                currentState = solution.y_events[0][0]
                self.eventTime_s = currentTime
                eventPending = False
                events["name"].append(self.eventName)
                events["time_s"].append(currentTime)
                events["state"].append(currentState.copy())

            if self.outputJsonFactory.streaming:
                available = nextOutput
                while available - chunkStart >= chunkSize:
                    emitChunk(chunkStart, chunkStart + chunkSize)
                    chunkStart += chunkSize

        if self.outputJsonFactory.streaming and chunkStart < time_s.size:
            emitChunk(chunkStart, time_s.size)
        return state, time_s, events

    # ------------------------------------------------------------------ RMS
    _RMS_ALGEBRAIC_TOLERANCE = 1e-10

    def _solveRMSAlgebraic(self, rms, state, reference, guesses) -> tuple[np.ndarray, float]:
        """Solve ``F_a(x_a, x_d) = 0`` for the algebraic states (Newton, then least squares)."""
        a = rms["algebraicIndices"]
        candidate = np.asarray(state, dtype=float).copy()

        def residual(xa):
            candidate[a] = xa
            return rms["F"](candidate, reference)[a]

        def jacobian(xa):
            candidate[a] = xa
            return rms["A"](candidate, reference)[np.ix_(a, a)]

        best, bestNorm = None, np.inf
        for guess in guesses:
            xa = np.asarray(guess, dtype=float).copy()
            try:
                value = residual(xa)
                norm = np.linalg.norm(value, np.inf)
                for _ in range(40):
                    if norm <= self._RMS_ALGEBRAIC_TOLERANCE:
                        break
                    step = np.linalg.solve(jacobian(xa), value)
                    scale = 1.0
                    while scale > 1e-4:  # backtracking line search
                        trial = xa - scale * step
                        trialValue = residual(trial)
                        trialNorm = np.linalg.norm(trialValue, np.inf)
                        if np.isfinite(trialNorm) and trialNorm < (1 - 1e-4 * scale) * norm:
                            break
                        scale /= 2
                    else:
                        break
                    xa, value, norm = trial, trialValue, trialNorm
            except (np.linalg.LinAlgError, FloatingPointError, ValueError):
                norm = np.inf
            if norm <= self._RMS_ALGEBRAIC_TOLERANCE:
                return xa, float(norm)
            if norm < bestNorm:
                best, bestNorm = xa, norm
        for guess in ([best] if best is not None else []) + list(guesses):
            solution = least_squares(residual, guess, jac=jacobian, xtol=1e-14, ftol=1e-14, gtol=1e-14)
            norm = float(np.linalg.norm(solution.fun, np.inf))
            if norm < bestNorm:
                best, bestNorm = solution.x, norm
            if norm <= 1e3 * self._RMS_ALGEBRAIC_TOLERANCE:
                break
        return best, float(bestNorm)

    def simulateRMS(
        self, time_s: Any, *, InitialState: Any = None,
        SolverSettings: Mapping[str, Any] | None = None,
        Breakpoints_s: Any = (), ReferenceMap: Any = None,
        ResidualTolerance: float = 1e-6,
    ) -> dict[str, Any]:
        """Simulate the RMS (phasor) model in the global DQ frame rotating at 1 pu.

        Differential states (frame angles and each device's
        ``rmsDynamicStateNames``) are integrated; all other states are solved
        from ``0 = F_a`` at every step (index-1 DAE by elimination). The
        initial state is the EMT operating point: at ``t = 0`` the DQ and
        alpha-beta frames coincide. States are DQ-frame quantities, and frame
        angles are measured relative to the DQ frame; magnitudes, powers and
        relative angles are directly comparable with :meth:`simulate`.
        """
        started = perf_counter()
        time_s = np.asarray(time_s, dtype=float).reshape(-1)
        if self.eventStartTime_s is not None:
            raise NotImplementedError("simulateRMS does not support state-triggered events")
        references = self.getReference(source=ReferenceMap)
        initialization = None
        if InitialState is None:
            point = self.initialize(time_s[0], Reference=self.getReference(time_s[0], references))
            InitialState, initialization = point["state"], point["initialization"]
        self.rlGrid.refreshParameters()
        rms = self.rlGrid.rms
        d, a = rms["differentialIndices"], rms["algebraicIndices"]
        wBase = 2 * np.pi * self.base["frequency_Hz"]
        x0 = np.asarray(InitialState, dtype=float).reshape(-1).copy()
        x0[a], norm0 = self._solveRMSAlgebraic(
            rms, x0, self.getReference(time_s[0], references), [x0[a]])
        if norm0 > ResidualTolerance:
            raise RuntimeError(f"RMS initialization failed: residual {norm0:.3e}")
        initialAlgebraic = x0[a].copy()
        last = {"xa": x0[a].copy()}

        def fullState(t, xd):
            reference = self.getReference(t, references)
            state = x0.copy(); state[d] = xd
            xa, norm = self._solveRMSAlgebraic(
                rms, state, reference, [last["xa"], initialAlgebraic])
            if norm > ResidualTolerance:
                raise RuntimeError(f"RMS algebraic solve failed at t = {t:.6g} s (residual {norm:.3e})")
            state[a] = xa; last["xa"] = xa
            return state, reference

        def derivative(t, xd):
            state, reference = fullState(t, xd)
            return wBase * rms["F"](state, reference)[d]

        settings = {"method": "RK45", "max_step": 1e-3, "rtol": 1e-7, "atol": 1e-9}
        settings.update(SolverSettings or {})
        breakpoints = np.unique(np.asarray(Breakpoints_s, dtype=float).reshape(-1))
        boundaries = np.r_[time_s[0], breakpoints[(breakpoints > time_s[0]) & (breakpoints < time_s[-1])], time_s[-1]]
        state = np.empty((time_s.size, x0.size))
        residualNorm = np.zeros(time_s.size)
        xd = x0[d].copy()
        for start, stop in zip(boundaries[:-1], boundaries[1:]):
            solution = solve_ivp(derivative, (start, stop), xd, dense_output=True, **settings)
            if not solution.success:
                raise RuntimeError(f"RMS integration failed at {solution.t[-1]:.9g} s: {solution.message}")
            xd = solution.y[:, -1]
            inside = np.flatnonzero((time_s >= start) & (time_s <= stop))
            last["xa"] = state[inside[0] - 1, a] if inside.size and inside[0] > 0 else last["xa"]
            for k in inside:
                sample, reference = fullState(time_s[k], solution.sol(time_s[k]))
                state[k] = sample
                residualNorm[k] = np.linalg.norm(rms["F"](sample, reference)[a], np.inf)
        networkSignals = self.calculateNetworkSignals(time_s, state, references)
        signals = self.calculateSignals(time_s, state, networkSignals)
        return {
            "model": "RMS", "time_s": time_s, "state": state, "stateNames": self.stateNames,
            "signals": signals, "referenceNames": self.referenceNames,
            "referenceTrace": networkSignals["referenceTrace"],
            "initialization": initialization, "parameters": self.parameters,
            "differentialStateNames": [self.stateNames[i] for i in d],
            "algebraicStateNames": [self.stateNames[i] for i in a],
            "algebraicResidual": residualNorm,
            "simulationTime_s": perf_counter() - started,
        }

    def correctRMS(
        self, rmsResult: Mapping[str, Any], *, cutoff_Hz: float = 1000.0,
        eigenvalueSamples: int = 200,
    ) -> dict[str, Any]:
        """First-order (LTV) correction of an RMS trajectory, in the DQ frame.

        With the RMS states ``x_RMS(t)`` and ``Delta x = x_EMT - x_RMS``, the
        algebraic (electrical) states obey the EMT equations ``dx_a/dtau =
        F_a``. Linearized along the RMS trajectory, where ``F_a = 0``::

            dDelta_a/dtau = A_aa(t) Delta_a - dx_a,RMS/dtau,
            dx_a,RMS/dtau = -A_aa^-1 (A_ad dx_d/dtau + B_a du/dtau),

        with ``Delta_d = 0``: the slow states are those of the RMS model.
        ``A_aa`` holds the dynamic network/filter operators and the limiter,
        FRT and frame-rotation Jacobians.

        Integration is modal and exact for each output interval: ``A_aa`` is
        frozen at the interval midpoint and diagonalized, the forcing is linear
        in time (``u`` piecewise linear; include breakpoints in the grid).
        Modes with ``|lambda| <= 2 pi cutoff_Hz`` are integrated with the
        exponential integrator. Faster modes (line-charging LC resonances,
        ideal-source dynamics) keep their quasi-static forced response
        ``z = -g / lambda``: they are first-order singular perturbations of the
        correction itself, and a weakly unstable high-frequency mode cannot
        grow without the EMT nonlinearities that bound it. ``cutoff_Hz=inf``
        integrates every mode (plain LTV model).
        """
        started = perf_counter()
        time_s = np.asarray(rmsResult["time_s"], dtype=float)
        stateRMS = np.asarray(rmsResult["state"], dtype=float)
        references = np.asarray(rmsResult["referenceTrace"], dtype=float)
        self.rlGrid.refreshParameters()
        rms = self.rlGrid.rms
        d, a = rms["differentialIndices"], rms["algebraicIndices"]
        wBase = 2 * np.pi * self.base["frequency_Hz"]
        tau = wBase * time_s
        na, count = a.size, time_s.size
        Aaa = np.empty((count, na, na))
        Ead = np.empty((count, na, d.size))  # A_aa^-1 A_ad
        Eau = np.empty((count, na, references.shape[1]))  # A_aa^-1 B_a
        xdRate = np.empty((count, d.size))
        for k in range(count):
            A = rms["A"](stateRMS[k], references[k])
            B = rms["B"](stateRMS[k], references[k]).reshape(len(self.stateNames), -1)
            Aaa[k] = A[np.ix_(a, a)]
            Ead[k] = np.linalg.solve(Aaa[k], A[np.ix_(a, d)])
            Eau[k] = np.linalg.solve(Aaa[k], B[a])
            xdRate[k] = rms["F"](stateRMS[k], references[k])[d]

        def forcing(k, referenceRate):
            return Ead[k] @ xdRate[k] + Eau[k] @ referenceRate  # = -dx_a,RMS/dtau

        def phi(x, order):
            """phi_1(x) = (e^x - 1)/x, phi_2(x) = (e^x - 1 - x)/x^2 (series near 0)."""
            small = np.abs(x) < 1e-6
            safe = np.where(small, 1.0, x)
            if order == 1:
                return np.where(small, 1 + x / 2, np.expm1(safe) / safe)
            return np.where(small, 0.5 + x / 6, (np.expm1(safe) - safe) / safe**2)

        cutoff = 2 * np.pi * cutoff_Hz / wBase  # pu (per tau)
        delta = np.zeros((count, na))
        current = np.zeros(na, dtype=complex)
        quasiStaticCount = np.zeros(count, dtype=int)
        for k in range(count - 1):
            h = tau[k + 1] - tau[k]
            referenceRate = (references[k + 1] - references[k]) / h
            r0, r1 = forcing(k, referenceRate), forcing(k + 1, referenceRate)
            poles, vectors = np.linalg.eig(0.5 * (Aaa[k] + Aaa[k + 1]))
            z0 = np.linalg.solve(vectors, current)
            g0, g1 = np.linalg.solve(vectors, r0), np.linalg.solve(vectors, r1)
            x = poles * h
            dynamic = np.abs(poles) <= cutoff
            z1 = np.where(
                dynamic,
                np.exp(x) * z0 + h * phi(x, 1) * g0 + h * phi(x, 2) * (g1 - g0),
                -g1 / poles,
            )
            current = vectors @ z1
            quasiStaticCount[k + 1] = int(np.count_nonzero(~dynamic))
            delta[k + 1] = current.real
        state = stateRMS.copy()
        state[:, a] += delta
        networkSignals = self.calculateNetworkSignals(time_s, state, self.getReference())
        networkSignals["referenceTrace"] = references
        signals = self.calculateSignals(time_s, state, networkSignals)
        sampleIndices = np.unique(np.linspace(0, count - 1, min(eigenvalueSamples, count)).astype(int))
        return {
            "model": "RMS+Delta", "time_s": time_s, "state": state, "stateNames": self.stateNames,
            "signals": signals, "referenceNames": self.referenceNames, "referenceTrace": references,
            "parameters": self.parameters, "delta": delta, "cutoff_Hz": cutoff_Hz,
            "quasiStaticModeCount": quasiStaticCount,
            "algebraicStateNames": [self.stateNames[i] for i in a],
            "eigenvalueTime_s": time_s[sampleIndices],
            "fastEigenvalues_per_s": np.asarray([wBase * np.linalg.eigvals(Aaa[k]) for k in sampleIndices]),
            "simulationTime_s": perf_counter() - started,
        }

    def rmsSmallSignal(self, operatingPoint: Mapping[str, Any]) -> dict[str, Any]:
        """Linearized RMS model: ``A_red = A_dd - A_da A_aa^-1 A_ad`` and the fast ``A_aa`` (pu, per tau)."""
        self.rlGrid.refreshParameters()
        rms = self.rlGrid.rms
        d, a = rms["differentialIndices"], rms["algebraicIndices"]
        A = rms["A"](operatingPoint["state"], operatingPoint["reference"])
        Aaa = A[np.ix_(a, a)]
        reduced = A[np.ix_(d, d)] - A[np.ix_(d, a)] @ np.linalg.solve(Aaa, A[np.ix_(a, d)])
        return {
            "A": A, "reducedA": reduced, "fastA": Aaa,
            "reducedPoles": np.linalg.eigvals(reduced), "fastPoles": np.linalg.eigvals(Aaa),
            "differentialStateNames": [self.stateNames[i] for i in d],
            "algebraicStateNames": [self.stateNames[i] for i in a],
        }

    def eventHandler(self, time_s: float, state: np.ndarray) -> float:
        """Return a nonzero value for systems without state-triggered events."""
        return 1.0

    def calculateNetworkSignals(self, time_s: Any, state: Any, references: Any) -> dict[str, Any]:
        state, time_s = np.asarray(state), np.asarray(time_s)
        sampleCount, grid = state.shape[0], self.rlGrid
        voltage = np.zeros((sampleCount, grid.n), complex)
        branch = np.zeros((sampleCount, grid.b), complex)
        current = np.zeros((sampleCount, grid.n), complex)
        referenceTrace = np.zeros((sampleCount, len(references)))
        for sampleIndex in range(sampleCount):
            referenceTrace[sampleIndex] = self.getReference(time_s[sampleIndex], references)
            branchValue, voltageValue, currentValue = grid.g_numeric(state[sampleIndex], referenceTrace[sampleIndex])
            branch[sampleIndex] = branchValue.reshape(-1, 2)[:, 0] + 1j * branchValue.reshape(-1, 2)[:, 1]
            voltage[sampleIndex] = voltageValue.reshape(-1, 2)[:, 0] + 1j * voltageValue.reshape(-1, 2)[:, 1]
            current[sampleIndex] = currentValue.reshape(-1, 2)[:, 0] + 1j * currentValue.reshape(-1, 2)[:, 1]
        injection = branch @ grid.A.T
        voltageDeviceCurrent = injection - current
        return {
            "busNames": self.busNames, "busVoltage": voltage,
            "branchCurrent": branch, "busCurrent": injection,
            "currentDeviceCurrent": current, "voltageDeviceCurrent": voltageDeviceCurrent,
            "busPower": voltage * np.conj(injection),
            "currentDevicePower": voltage * np.conj(current),
            "voltageDevicePower": voltage * np.conj(voltageDeviceCurrent),
            "referenceTrace": referenceTrace,
        }

    def busSignals(self, networkSignals: dict[str, Any], indices: Any, referenceIndex: int):
        indices = np.asarray(indices, dtype=int).reshape(-1)
        voltage = networkSignals["busVoltage"][:, indices]
        power = networkSignals["busPower"][:, indices]
        relativeVoltage = voltage / networkSignals["busVoltage"][:, [referenceIndex]]
        angleDegrees = np.rad2deg(np.unwrap(np.angle(relativeVoltage), axis=0))
        names = [self.busNames[i] for i in indices]
        return {
            "busNames": names, "busVoltageMagnitude": np.abs(voltage),
            "busVoltageAngleDeg": angleDegrees, "activePower": power.real,
            "reactivePower": power.imag,
            "lineCurrentMagnitude": np.abs(networkSignals["branchCurrent"]),
            "finalValues": [
                {"Bus": name, "Voltage_pu": abs(voltage[-1, i]), "Angle_deg": angleDegrees[-1, i],
                 "P_injection_pu": power[-1, i].real, "Q_injection_pu": power[-1, i].imag}
                for i, name in enumerate(names)
            ],
        }

    @abstractmethod
    def calculateSignals(self, time_s: Any, state: Any, networkSignals: dict[str, Any]):
        """Return system-specific output signals."""
