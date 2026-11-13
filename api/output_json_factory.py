"""Convert simulation and analysis results to the frontend JSON schema."""

from __future__ import annotations

import json
import inspect
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import sympy as sp


class OutputJsonFactory:
    NON_EDITABLE_SYSTEM_PARAMETERS = frozenset({
        "wBase", "Rg", "Lg", "breakpoints_s", "gridVoltage", "Zbase_ohm",
    })

    def __init__(self, system: Any = None, outputDirectory: str | Path | None = None) -> None:
        """[shared] Initialize stdout streaming state and snapshot storage state."""
        self.system = system
        self.requestId: Any = None
        self.sequence = 0
        self.streaming = False
        # Event prefix of streamed chunks: "simulation" (EMT) or "rms".
        self.streamKind = "simulation"
        # Keep live plots responsive even for simulations with only a few
        # hundred output samples.  Larger chunks made short runs emit their
        # first waveform update only when integration was nearly complete.
        self.chunkSize = 50
        self.latestSimulation: dict[str, Any] = {}
        self.latestSmallSignal: dict[str, Any] = {}
        # The analysis object behind latestSmallSignal; snapshots re-serialize
        # only when a new analysis replaced it.
        self._serializedAnalysis: Any = None
        # (simulation, busIds, signals) of the last buildSignals call in getDescriptor.
        self._signalsCache: tuple[Any, list[str], list[dict[str, Any]]] | None = None
        self.latestInteractionAnalysis: dict[str, Any] = {}
        self.latestRMS: dict[str, Any] = {}
        self.outputDirectory = Path(outputDirectory) if outputDirectory else Path(__file__).resolve().parents[2] / "codegen"
        self.preserveExisting = True

    @staticmethod
    def _parameter(parameterId: str, label: str, value: Any, unit: str = "", group: str = ""):
        """[snapshot] Convert one model parameter to the snapshot schema."""
        return {"id": parameterId, "label": label, "value": OutputJsonFactory.jsonSafe(value), "unit": unit, "group": group}

    @staticmethod
    def jsonSafe(value: Any) -> Any:
        """[shared] Convert Python and NumPy values to JSON-safe values."""
        if isinstance(value, np.ndarray):
            if np.iscomplexobj(value):
                return {
                    "real": OutputJsonFactory.jsonSafe(value.real),
                    "imaginary": OutputJsonFactory.jsonSafe(value.imag),
                    "magnitude": OutputJsonFactory.jsonSafe(np.abs(value)),
                }
            return OutputJsonFactory.jsonSafe(value.tolist())
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, float) and not np.isfinite(value):
            return None
        if isinstance(value, complex):
            return {"real": value.real, "imaginary": value.imag, "magnitude": abs(value)}
        if isinstance(value, dict):
            return {str(key): OutputJsonFactory.jsonSafe(item) for key, item in value.items()}
        if isinstance(value, list) and value and type(value[0]) is float:
            # Fast path for signal traces: a flat list of finite floats is
            # already JSON-safe (walking millions of items one by one is slow).
            try:
                array = np.asarray(value, dtype=float)
            except (TypeError, ValueError):
                array = None
            if array is not None and array.ndim == 1 and np.isfinite(array).all():
                return value
        if isinstance(value, (list, tuple)):
            return [OutputJsonFactory.jsonSafe(item) for item in value]
        if callable(value):
            return getattr(value, "__name__", repr(value))
        return value

    def beginSimulation(self, requestId: Any, kind: str = "simulation") -> None:
        """[stdout] Start associating streamed chunks with one request.

        ``kind`` prefixes the chunk events: ``simulation.chunk`` for EMT runs,
        ``rms.chunk`` for RMS runs.
        """
        self.requestId = requestId
        self.sequence = 0
        self.streaming = True
        self.streamKind = kind

    def endSimulation(self) -> None:
        """[stdout] Stop simulation chunk streaming."""
        self.streaming = False
        self.requestId = None
        self.streamKind = "simulation"

    def writeSimulationChunk(self, time_s: Any, state: Any, signals: dict[str, Any]) -> None:
        """[stdout] Serialize states and calculated signals as one streamed chunk."""
        if not self.streaming:
            return
        self.writeStdout({
            "type": f"{self.streamKind}.chunk",
            "requestId": self.requestId,
            "sequence": self.sequence,
            "signals": self.buildSignals({
                "time_s": time_s,
                "state": state,
                "stateNames": self.system.stateNames,
                "signals": signals,
            }),
        })
        self.sequence += 1

    def writeResponse(self, requestId: Any, result: Any = None) -> None:
        """[stdout] Write a successful request response."""
        self.writeStdout({"id": requestId, "ok": True, "result": result})

    def writeError(self, requestId: Any, error: Exception | str) -> None:
        """[stdout] Write a failed request response."""
        self.writeStdout({"id": requestId, "ok": False, "error": str(error)})

    def writeEvent(self, eventType: str, requestId: Any, **payload: Any) -> None:
        """[stdout] Write an asynchronous backend event."""
        self.writeStdout({"type": eventType, "requestId": requestId, **payload})

    def writeStdout(self, value: Any) -> None:
        """[stdout] Emit one line-delimited JSON message and flush it immediately."""
        sys.stdout.write(json.dumps(self.jsonSafe(value), ensure_ascii=False, allow_nan=False) + "\n")
        sys.stdout.flush()

    def describeDevice(self, device: Any) -> dict[str, Any]:
        """[snapshot] Describe one device for the frontend model graph."""
        className = f"{device.__class__.__module__}.{device.__class__.__name__}"
        shortName = device.__class__.__name__
        kind, icon = self.deviceAppearance(shortName)
        parameters = [
            self._parameter(name, name, parameter["num"], "", shortName)
            for name, parameter in device.p.items()
        ]
        index = str(device.index).lstrip("_")
        source = {"file": inspect.getsourcefile(device.__class__) or "", "line": 1, "column": 1}
        return {
            "id": re.sub(r"[^a-zA-Z0-9_-]", "-", f"{shortName}-{index}").lower(),
            "name": f"{shortName} {index}", "className": className,
            "kind": kind, "icon": icon, "portType": device.type,
            "parameters": parameters,
            "classSource": source, "instanceSource": source,
        }

    def editableParameterNames(self) -> list[str]:
        """Return only model inputs that can be represented and edited by the UI."""
        hidden = self.NON_EDITABLE_SYSTEM_PARAMETERS | set(
            getattr(self.system, "nonEditableParameterNames", ())
        )
        return [
            name for name in self.system.parameterNames
            if name in self.system.parameters
            and name not in hidden
            and not callable(self.system.parameters[name])
        ]

    def editableParameters(self) -> dict[str, Any]:
        """Return the editable parameter values exposed by the backend protocol."""
        return {
            name: self.system.parameters[name]
            for name in self.editableParameterNames()
        }

    def getDescriptor(self, simulation: dict[str, Any] | None = None) -> dict[str, Any]:
        """[snapshot] Build the complete frontend descriptor in memory."""
        simulation = simulation or {}
        analysis = self.system.smallSignal.latestAnalysis
        if analysis and analysis is not self._serializedAnalysis:
            self.latestSmallSignal = self.serializeSmallSignal(analysis)
            self._serializedAnalysis = analysis
        A = np.asarray(self.system.network["A"])
        busNames = list(self.system.network["busNames"])
        R = np.asarray(self.system.network["R"]).reshape(-1)
        L = np.asarray(self.system.network["L"]).reshape(-1)
        Vdev = list(self.system.devices["Vdev"])
        Idev = list(self.system.devices["Idev"])
        source = {
            "file": inspect.getsourcefile(self.system.__class__) or "",
            "line": 1, "column": 1,
        }
        components, connections = [], []
        busIds = [f"bus-{i + 1}" for i in range(A.shape[0])]
        for i, (busId, busName) in enumerate(zip(busIds, busNames)):
            components.append({
                "id": busId, "name": str(busName), "className": "codesim.Bus",
                "kind": "bus", "icon": "bus", "portType": "", "parameters": [],
                "classSource": source, "instanceSource": source,
            })
            for device in (Vdev[i], Idev[i]):
                if device is None or device.__class__.__name__ == "ZeroCurrent":
                    continue
                descriptor = self.describeDevice(device)
                components.append(descriptor)
                connections.append({
                    "id": f"{descriptor['id']}-terminal-{i + 1}", "name": "Terminal",
                    "source": busId, "target": descriptor["id"], "sourceHandle": "bottom",
                    "targetHandle": "top", "parameters": [], "sourceReference": source,
                })
        for i in range(A.shape[1]):
            endpoints = np.flatnonzero(A[:, i])
            if endpoints.size < 2:
                continue
            positive = np.flatnonzero(A[:, i] > 0)
            negative = np.flatnonzero(A[:, i] < 0)
            start = int(positive[0] if positive.size else endpoints[0])
            stop = int(negative[0] if negative.size else endpoints[-1])
            connections.append({
                "id": f"branch-{i + 1}", "name": f"Branch {i + 1}",
                "source": busIds[start], "target": busIds[stop],
                "sourceHandle": "right", "targetHandle": "left",
                "parameters": [self._parameter("R", "Resistance", R[i], "pu", "Line"),
                               self._parameter("L", "Inductance", L[i], "pu", "Line")],
                "sourceReference": source,
            })
        editableParameterNames = self.editableParameterNames()
        systemParameters = [
            {**self._parameter(name, name, self.system.parameters[name], "", "System"), "editable": True}
            for name in editableParameterNames
        ]
        return {
            "schemaVersion": 1,
            "system": {
                "id": re.sub(r"[^a-zA-Z0-9_-]", "-", self.system.name).lower(),
                "name": self.system.name,
                "className": f"{self.system.__class__.__module__}.{self.system.__class__.__name__}",
                "parameterNames": editableParameterNames, "parameters": systemParameters,
                "source": source,
            },
            "components": components, "connections": connections,
            "signals": self.cachedSignals(simulation, busIds),
            "simulationData": ({
                "time_s": self.jsonSafe(simulation["time_s"]),
                "referenceNames": simulation.get("referenceNames", self.system.referenceNames),
                "referenceTrace": self.jsonSafe(simulation["referenceTrace"]),
            } if "state" in simulation and "referenceTrace" in simulation else {}),
            "smallSignal": self.latestSmallSignal,
            "interactionAnalysis": self.latestInteractionAnalysis,
            "rmsSimulation": self.latestRMS,
        }

    def cachedSignals(self, simulation: dict[str, Any], busIds: list[str]) -> list[dict[str, Any]]:
        """``buildSignals`` for the descriptor, reused while the simulation is unchanged."""
        cached = self._signalsCache
        if cached is not None and cached[0] is simulation and cached[1] == busIds:
            return cached[2]
        signals = self.buildSignals(simulation, busIds)
        if simulation:
            self._signalsCache = (simulation, list(busIds), signals)
        return signals

    def saveSnapshot(self, simulation: dict[str, Any] | None = None):
        """[snapshot] Atomically write the latest frontend descriptor to disk."""
        if simulation is not None:
            self.latestSimulation = simulation
        descriptor = self.getDescriptor(self.latestSimulation)
        self.outputDirectory.mkdir(parents=True, exist_ok=True)
        modelName = re.sub(r'[<>:"/\\|?*]', "-", self.system.name)
        snapshotFile = self.outputDirectory / f"{modelName}-snapshot.json"
        if self.preserveExisting and snapshotFile.exists():
            try:
                existing = json.loads(snapshotFile.read_text(encoding="utf-8"))
                descriptor = self.mergeSnapshot(descriptor, existing)
            except (OSError, json.JSONDecodeError):
                pass
        payload = json.dumps(self.jsonSafe(descriptor), ensure_ascii=False, allow_nan=False)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.outputDirectory, delete=False) as handle:
            handle.write(payload); temporary = Path(handle.name)
        os.replace(temporary, snapshotFile)
        return snapshotFile, descriptor

    def mergeSnapshot(self, descriptor: dict[str, Any], existing: dict[str, Any]):
        """[snapshot] Preserve compatible results and layout from an existing file."""
        existing = existing.get("frontendDescriptor", existing)
        if existing.get("system", {}).get("id") != descriptor.get("system", {}).get("id"):
            return descriptor
        savedParameters = {row["id"]: row["value"] for row in existing["system"].get("parameters", [])}
        currentParameters = {row["id"]: row["value"] for row in descriptor["system"].get("parameters", [])}
        compatible = savedParameters == currentParameters
        newSimulation = bool(descriptor.get("signals"))
        if compatible and not newSimulation and existing.get("signals"):
            descriptor["signals"] = existing["signals"]
        if compatible and not descriptor.get("simulationData") and existing.get("simulationData"):
            descriptor["simulationData"] = existing["simulationData"]
        if not descriptor.get("layout") and existing.get("layout"):
            descriptor["layout"] = existing["layout"]
        smallSignal = descriptor.get("smallSignal", {})
        existingSmallSignal = existing.get("smallSignal", {})
        if compatible and not (smallSignal.get("available") and smallSignal.get("modes")) and (
            existingSmallSignal.get("available") and existingSmallSignal.get("modes")
        ):
            descriptor["smallSignal"] = existing["smallSignal"]
        interaction = descriptor.get("interactionAnalysis", {})
        existingInteraction = existing.get("interactionAnalysis", {})
        if compatible and not (interaction.get("available") and interaction.get("matrices")) and (
            existingInteraction.get("available") and existingInteraction.get("matrices")
        ):
            descriptor["interactionAnalysis"] = existing["interactionAnalysis"]
        rms = descriptor.get("rmsSimulation", {})
        existingRMS = existing.get("rmsSimulation", {})
        if compatible and not rms.get("available") and existingRMS.get("available"):
            descriptor["rmsSimulation"] = existingRMS
        return descriptor

    def serializeRMS(
        self, rms: dict[str, Any], corrected: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """[snapshot] Serialize an RMS run and its optional RMS+Delta correction.

        The corrected signals keep the RMS label prefix (so default plots group
        them with the RMS traces) and get an ``[RMS+Δ]`` suffix and a distinct id.
        """
        signals = self.buildSignals(rms)
        if corrected is not None:
            for signal in self.buildSignals(corrected):
                signals.append({
                    **signal,
                    "id": f"{signal['id']}-rms-delta",
                    "label": f"{signal['label']} [RMS+Δ]",
                })
        residual = np.asarray(rms.get("algebraicResidual", []), dtype=float)
        result = {
            "available": True,
            "model": corrected["model"] if corrected is not None else rms.get("model", "RMS"),
            "simulationTime_s": rms.get("simulationTime_s"),
            "differentialStateNames": list(rms.get("differentialStateNames", [])),
            "algebraicStateNames": list(rms.get("algebraicStateNames", [])),
            "time_s": self.jsonSafe(np.asarray(rms["time_s"], dtype=float)),
            "algebraicResidual": self.jsonSafe(residual),
            "maxAlgebraicResidual": float(residual.max()) if residual.size else 0.0,
            "signals": signals,
        }
        if corrected is not None:
            quasiStatic = np.asarray(corrected.get("quasiStaticModeCount", []), dtype=int)
            result.update({
                "cutoff_Hz": corrected.get("cutoff_Hz"),
                "correctionTime_s": corrected.get("simulationTime_s"),
                "quasiStaticModeCount": self.jsonSafe(quasiStatic),
                "maxQuasiStaticModeCount": int(quasiStatic.max()) if quasiStatic.size else 0,
            })
        return result

    def serializeSmallSignal(self, analysis: dict[str, Any]) -> dict[str, Any]:
        """[snapshot] Serialize small-signal modes and symbolic expressions."""
        poles = np.asarray(analysis["poles"], dtype=complex).reshape(-1)
        tolerance = float(analysis.get("poleTolerance", 1e-7))
        table = analysis.get("modeTable", [])
        modes = []
        for index, pole in enumerate(poles):
            row = table[index] if index < len(table) else {}
            modes.append({
                "mode": index + 1,
                "realPart": float(pole.real),
                "imaginaryPart": float(pole.imag),
                "frequencyHz": float(row.get(
                    "Frequency_Hz", abs(pole.imag) * self.system.base["frequency_Hz"]
                )),
                "dampingRatio": float(row.get(
                    "DampingRatio", -pole.real / max(abs(pole), np.finfo(float).eps)
                )),
                "stability": row.get(
                    "Stability",
                    "Unstable" if pole.real > tolerance else
                    "Marginal" if abs(pole.real) <= tolerance else "Stable",
                ),
                "dominantState": row.get("DominantState", ""),
                "dominantParticipation": float(row.get("DominantParticipation", 0)),
            })
        return {
            "available": True, "normalizedTime": True,
            "unstablePoleCount": int(np.sum(poles.real > tolerance)),
            "poleTolerance": tolerance, "modes": modes,
            "symbolicModel": self.serializeSymbolicModel(),
        }

    def serializeSymbolicModel(self) -> dict[str, Any]:
        """[snapshot] Symbolic EMT and RMS models, organised in blocks for the frontend.

        Equations are sent row by row and Jacobians as their nonzero entries in
        CSE form (``cseJacobian``) with the intermediates they use, so the
        frontend renders one block at a time instead of a multi-MB matrix. The
        result depends only on the model structure and is cached with it.
        """
        grid = self.system.rlGrid
        differential = tuple(grid.getRMSDifferentialIndices())
        key = ("symbolicDescriptor", differential)
        if key in grid._modelEntry:
            return grid._modelEntry[key]
        latex = sp.latex
        stateNames = [str(symbol) for symbol in grid.x]
        partition, blockStarts, blockNames = self.system.smallSignal.devicePartition()
        stops = list(blockStarts[1:]) + [len(partition) + 1]
        stateBlocks = [
            {"name": name, "indices": [index - 1 for index in partition[start - 1:stop - 1]]}
            for name, start, stop in zip(blockNames, blockStarts, stops)
        ]
        blockOf = {index: number for number, block in enumerate(stateBlocks) for index in block["indices"]}
        branchRows, busRows = 2 * grid.b, 2 * grid.n
        # Bus names may contain spaces and underscores: render them as text.
        busNames = [str(name).replace("_", r"\_") for name in self.system.busNames]
        outputLabels = (
            [latex(symbol) for symbol in grid.ibsym]
            + [rf"v_{{\text{{{name}}},{axis}}}" for name in busNames for axis in "dq"]
            + [rf"i_{{\text{{dev}},\text{{{name}}},{axis}}}" for name in busNames for axis in "dq"]
        )
        outputGroups = [
            {"name": name, "indices": list(range(start, start + count))}
            for name, start, count in (
                ("Branch currents", 0, branchRows),
                ("Bus voltages", branchRows, busRows),
                ("Device currents", branchRows + busRows, busRows),
            ) if count
        ]
        stateLatex = [latex(symbol) for symbol in grid.x]
        rms = grid.rms
        isDifferential = set(int(index) for index in rms["differentialIndices"])

        def rows(matrix, lhs):
            return [{"lhs": lhs[i], "latex": latex(matrix[i])} for i in range(matrix.rows)]

        def jacobian(identifier, label, replacements, matrix, columnGroups):
            symbols = [symbol for symbol, _ in replacements]
            index = {symbol: number for number, symbol in enumerate(symbols)}

            def uses(expression):
                return sorted(index[symbol] for symbol in expression.free_symbols if symbol in index)

            return {
                "id": identifier, "label": label,
                "rowGroups": "states", "columnGroups": columnGroups,
                "shape": [matrix.rows, matrix.cols],
                "entries": [
                    [i, j, latex(matrix[i, j]), uses(matrix[i, j])]
                    for i in range(matrix.rows) for j in range(matrix.cols) if matrix[i, j] != 0
                ],
                "intermediates": [
                    {"name": latex(symbol), "latex": latex(expression), "uses": uses(expression)}
                    for symbol, expression in replacements
                ],
            }

        dotted = [rf"\dot{{{name}}}" for name in stateLatex]
        descriptor = {
            "states": [
                {"name": name, "latex": stateLatex[i], "block": blockOf.get(i, len(stateBlocks) - 1),
                 "rms": "differential" if i in isDifferential else "algebraic"}
                for i, name in enumerate(stateNames)
            ],
            "inputs": [{"name": str(symbol), "latex": latex(symbol)} for symbol in grid.u],
            "stateBlocks": stateBlocks,
            "outputGroups": outputGroups,
            "models": [
                {
                    "id": "emt", "label": "EMT",
                    "description": "Stationary alpha-beta frame; time in per unit (tau = w_b t).",
                    "equations": [
                        {"id": "f", "label": "State equation f", "rowGroups": "states",
                         "rows": rows(grid.f, dotted)},
                        {"id": "g", "label": "Output equation g", "rowGroups": "outputs",
                         "rows": rows(grid.g, outputLabels)},
                    ],
                    "jacobians": [jacobian(
                        "A", "State matrix A = \u2202f/\u2202x (operating frame)",
                        *grid.A_cse, "states",
                    )],
                },
                {
                    "id": "rms", "label": "RMS",
                    "description": "Phasor model in the DQ frame rotating at 1 pu: differential rows "
                                   "dx_d/dtau = F_d, algebraic rows 0 = F_a.",
                    "equations": [
                        {"id": "F", "label": "RMS equations F", "rowGroups": "states",
                         "rows": rows(rms["F_sym"], [dotted[i] if i in isDifferential else "0"
                                                     for i in range(len(stateNames))])},
                    ],
                    "jacobians": [
                        jacobian("A_RMS", "A_RMS = \u2202F/\u2202x", *rms["A_cse"], "states"),
                        jacobian("B_RMS", "B_RMS = \u2202F/\u2202u", *rms["B_cse"], "inputs"),
                    ],
                },
            ],
        }
        grid._modelEntry[key] = descriptor
        return descriptor

    def serializeInteractionAnalysis(self, analysis: dict[str, Any]) -> dict[str, Any]:
        """[snapshot] Serialize subsystem interaction analysis results."""
        partition = np.asarray(analysis["partition"], dtype=int).reshape(-1)
        blockStarts = np.asarray(analysis["dIdx"], dtype=int).reshape(-1)
        partitionIndices = partition - 1 if partition.min() >= 1 else partition
        partitionStateNames = [self.system.stateNames[index] for index in partitionIndices]
        blockStops = np.r_[blockStarts[1:] - 1, partition.size]
        blockNames = analysis.get(
            "blockNames", [f"Subsystem {index + 1}" for index in range(blockStarts.size)]
        )
        blocks = [
            {
                "name": str(blockNames[index]),
                "startMode": int(blockStarts[index]),
                "endMode": int(blockStops[index]),
                "stateNames": partitionStateNames[
                    blockStarts[index] - 1:blockStops[index]
                ],
            }
            for index in range(blockStarts.size)
        ]
        maskRows, maskColumns = analysis["maskedIdx"]
        shiftTable = analysis["shiftTable"]
        modeShifts = []
        for index, row in enumerate(shiftTable):
            modeShifts.append({
                "mode": index + 1,
                "relatedState": row["related_state"],
                "localEigenvalue": row["local_lambda"],
                "fullEigenvalue": row["full_lambda"],
                "reducedEigenvalue": row["reduced_lambda"],
                "deltaEigenvalue": row["delta_lambda"],
                "localPoint": self.complexPoint(row["local_value"]),
                "fullPoint": self.complexPoint(row["full_value"]),
                "reducedPoint": self.complexPoint(row["reduced_value"]),
                "deltaPoint": self.complexPoint(row["delta_value"]),
            })
        localModes = [
            {
                "mode": index + 1, "label": str(row["idx"]),
                "eigenvalue": str(row["eig"]),
                "naturalFrequency": float(row["wn"]),
                "dampingRatio": float(row["zeta"]),
                "dominantState": str(row["dominantStates"]),
            }
            for index, row in enumerate(analysis["modalTable"])
        ]
        labels = [str(index + 1) for index in range(partition.size)]
        matrices = {
            "dAll": self.serializeComplexMatrix(analysis["DAll"], labels, labels),
            "aOriginal": self.serializeComplexMatrix(
                analysis["AOriginal"], self.system.stateNames, self.system.stateNames
            ),
            "aPartitioned": self.serializeComplexMatrix(
                analysis["APartitioned"], partitionStateNames, partitionStateNames
            ),
            "aBack": self.serializeComplexMatrix(
                analysis["ABack"], partitionStateNames, partitionStateNames
            ),
        }
        return {
            "available": True,
            "parameterName": str(analysis.get("gridParameterName", "")),
            "parameterValue": (float(analysis["gridParameterValue"])
                               if "gridParameterValue" in analysis else None),
            "partition": partition.tolist(),
            "partitionStateNames": partitionStateNames,
            "blockStarts": blockStarts.tolist(), "blocks": blocks,
            "maskedRows": list(maskRows), "maskedColumns": list(maskColumns),
            "estimatedShift": (self.complexPoint(analysis["estimatedShift"])
                               if "estimatedShift" in analysis else None),
            "reconstructionErrorFro": float(np.linalg.norm(
                np.asarray(analysis["APartitioned"]) - np.asarray(analysis["ABack"])
            )),
            "modeShifts": modeShifts, "localModes": localModes,
            "matrices": matrices,
        }

    @staticmethod
    def complexPoint(value: complex) -> dict[str, float]:
        """[snapshot] Represent one complex value for plots and tables."""
        return {
            "realPart": float(np.real(value)),
            "imaginaryPart": float(np.imag(value)),
            "magnitude": float(np.abs(value)),
        }

    @staticmethod
    def serializeComplexMatrix(matrix: Any, rowLabels: Any, columnLabels: Any):
        """[snapshot] Represent one complex matrix for the frontend."""
        matrix = np.asarray(matrix, dtype=complex)
        return {
            "rowLabels": list(map(str, rowLabels)),
            "columnLabels": list(map(str, columnLabels)),
            "real": matrix.real.tolist(), "imaginary": matrix.imag.tolist(),
            "magnitude": np.abs(matrix).tolist(),
        }

    def buildSignals(self, simulation: dict[str, Any], busIds: list[str] | None = None):
        """[shared] Serialize the four plot groups followed by every state variable."""
        if not simulation:
            return []
        values = simulation.get("signals", simulation)
        time = simulation.get("time_s", simulation.get("outputTime_s"))
        if time is None:
            return []
        time = np.asarray(time, dtype=float).reshape(-1)
        signals: list[dict[str, Any]] = []
        if busIds is None:
            busIds = [f"bus-{i + 1}" for i in range(np.asarray(self.system.network["A"]).shape[0])]
        busNames = list(values.get("busNames", self.system.busNames))
        originalNames = list(self.system.network["busNames"])
        systemId = re.sub(r"[^a-zA-Z0-9_-]", "-", self.system.name).lower()
        plotDefinitions = (
            ("busVoltageMagnitude", "|V|", "pu", "component"),
            ("lineCurrentMagnitude", "I", "pu", "connection"),
            ("activePower", "P", "pu", "component"),
            ("reactivePower", "Q", "pu", "component"),
            ("busVoltageAngleDeg", "theta", "deg", "component"),
            ("pccVoltage", "PCC voltage", "pu", "system"),
            ("lvrtMode", "LVRT mode", "", "system"),
        )
        for field, label, unit, ownerKind in plotDefinitions:
            if field not in values:
                continue
            matrix = np.asarray(values[field])
            if matrix.ndim == 1:
                matrix = matrix[:, None]
            if matrix.shape[0] != time.size and matrix.shape[1] == time.size:
                matrix = matrix.T
            for column in range(matrix.shape[1]):
                if ownerKind == "connection":
                    owner, ownerName = f"branch-{column + 1}", f"Branch {column + 1}"
                elif ownerKind == "system":
                    owner, ownerName = systemId, self.system.name
                elif column < len(busNames) and busNames[column] in originalNames:
                    ownerName = busNames[column]
                    owner = busIds[originalNames.index(ownerName)]
                else:
                    continue
                signals.append(self.makeSignal(
                    owner, ownerKind, 
                    f"{label}-{ownerName}", unit, time, matrix[:, column],
                ))
        if "state" in simulation:
            state = np.asarray(simulation["state"])
            stateNames = list(map(str, simulation.get("stateNames", self.system.stateNames)))
            if state.ndim == 1:
                state = state[None, :] if time.size == 1 else state[:, None]
            if state.shape[0] != time.size and state.shape[1] == time.size:
                state = state.T
            stateOwners: dict[str, str] = {}
            for device in [*self.system.devices["Vdev"], *self.system.devices["Idev"]]:
                if device is None:
                    continue
                shortName = device.__class__.__name__
                index = str(device.index).lstrip("_")
                deviceId = re.sub(r"[^a-zA-Z0-9_-]", "-", f"{shortName}-{index}").lower()
                stateOwners.update({str(symbol): deviceId for symbol in device.x})
            for column, stateName in enumerate(stateNames[:state.shape[1]]):
                owner = stateOwners.get(stateName, systemId)
                ownerKind = "component" if stateName in stateOwners else "system"
                signals.append(self.makeSignal(
                    owner, ownerKind, stateName, "",
                    time, state[:, column], "state",
                ))
        return signals

    @staticmethod
    def makeSignal(ownerId: str, ownerKind: str, label: str, unit: str,
                   time: Any, values: Any, category: str = "output"):
        """[shared] Build one frontend signal for stdout or a snapshot file."""
        return {
            "id": re.sub(r"[^a-zA-Z0-9_-]", "-", f"{ownerId}-{label}").lower(),
            "componentId": ownerId, "ownerId": ownerId, "ownerKind": ownerKind,
            "category": category, "label": label, "unit": unit,
            "time": np.asarray(time, dtype=float).reshape(-1).tolist(),
            "values": np.real(np.asarray(values)).reshape(-1).astype(float).tolist(),
        }

    @staticmethod
    def deviceAppearance(className: str) -> tuple[str, str]:
        """[snapshot] Map a device class to frontend kind and icon names."""
        name = className.lower()
        if name == "infbus": return "grid", "grid"
        if "vsg" in name or "gfm" in name: return "gfm", "converter"
        if "gfl" in name or "pll" in name: return "gfl", "converter"
        if "generator" in name or name.startswith("sg"): return "generator", "generator"
        if "motor" in name: return "motor", "motor"
        if "capacitor" in name: return "capacitor", "capacitor"
        if "load" in name or name in ("zip", "cpl"): return "load", "load"
        return "generic", "device"
