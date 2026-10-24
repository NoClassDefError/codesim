"""Shared construction, initialization, and time-domain workflow."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from time import perf_counter
from typing import Any

import numpy as np
import sympy as sp
from scipy.integrate import solve_ivp
from scipy.optimize import root

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
        if "clearTime_s" in self.parameters:
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

    @abstractmethod
    def eventHandler(self, time_s: float, state: np.ndarray) -> float:
        """Return the model-specific zero-crossing value."""
        raise NotImplementedError

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
