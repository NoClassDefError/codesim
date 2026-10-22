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
    def __init__(self, system: Any = None, outputDirectory: str | Path | None = None) -> None:
        """[shared] Initialize stdout streaming state and snapshot storage state."""
        self.system = system
        self.requestId: Any = None
        self.sequence = 0
        self.streaming = False
        self.chunkSize = 200
        self.latestSimulation: dict[str, Any] = {}
        self.latestSmallSignal: dict[str, Any] = {}
        self.latestInteractionAnalysis: dict[str, Any] = {}
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
        if isinstance(value, (list, tuple)):
            return [OutputJsonFactory.jsonSafe(item) for item in value]
        if callable(value):
            return getattr(value, "__name__", repr(value))
        return value

    def beginSimulation(self, requestId: Any) -> None:
        """[stdout] Start associating streamed chunks with one request."""
        self.requestId = requestId
        self.sequence = 0
        self.streaming = True

    def endSimulation(self) -> None:
        """[stdout] Stop simulation chunk streaming."""
        self.streaming = False
        self.requestId = None

    def writeSimulationChunk(self, time_s: Any, state: Any, signals: dict[str, Any]) -> None:
        """[stdout] Serialize states and calculated signals as one streamed chunk."""
        if not self.streaming:
            return
        self.writeStdout({
            "type": "simulation.chunk",
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

    def getDescriptor(self, simulation: dict[str, Any] | None = None) -> dict[str, Any]:
        """[snapshot] Build the complete frontend descriptor in memory."""
        simulation = simulation or {}
        if self.system.smallSignal.latestAnalysis:
            self.latestSmallSignal = self.serializeSmallSignal(self.system.smallSignal.latestAnalysis)
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
        systemParameters = [
            {**self._parameter(name, name, self.system.parameters[name], "", "System"), "editable": True}
            for name in self.system.parameterNames
        ]
        return {
            "schemaVersion": 1,
            "system": {
                "id": re.sub(r"[^a-zA-Z0-9_-]", "-", self.system.name).lower(),
                "name": self.system.name,
                "className": f"{self.system.__class__.__module__}.{self.system.__class__.__name__}",
                "parameterNames": self.system.parameterNames, "parameters": systemParameters,
                "source": source,
            },
            "components": components, "connections": connections,
            "signals": self.buildSignals(simulation, busIds),
            "smallSignal": self.latestSmallSignal,
            "interactionAnalysis": self.latestInteractionAnalysis,
        }

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
        payload = json.dumps(self.jsonSafe(descriptor), ensure_ascii=False, indent=2, allow_nan=False)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.outputDirectory, delete=False) as handle:
            handle.write(payload); temporary = Path(handle.name)
        os.replace(temporary, snapshotFile)
        return snapshotFile, descriptor

    def mergeSnapshot(self, descriptor: dict[str, Any], existing: dict[str, Any]):
        """[snapshot] Preserve compatible results and layout from an existing file."""
        existing = existing.get("frontendDescriptor", existing)
        if existing.get("system", {}).get("id") != descriptor.get("system", {}).get("id"):
            return descriptor
        if not descriptor.get("signals") and existing.get("signals"):
            descriptor["signals"] = existing["signals"]
        if not descriptor.get("layout") and existing.get("layout"):
            descriptor["layout"] = existing["layout"]
        smallSignal = descriptor.get("smallSignal", {})
        existingSmallSignal = existing.get("smallSignal", {})
        if not (smallSignal.get("available") and smallSignal.get("modes")) and (
            existingSmallSignal.get("available") and existingSmallSignal.get("modes")
        ):
            descriptor["smallSignal"] = existing["smallSignal"]
        interaction = descriptor.get("interactionAnalysis", {})
        existingInteraction = existing.get("interactionAnalysis", {})
        if not (interaction.get("available") and interaction.get("matrices")) and (
            existingInteraction.get("available") and existingInteraction.get("matrices")
        ):
            descriptor["interactionAnalysis"] = existing["interactionAnalysis"]
        return descriptor

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
        grid = self.system.rlGrid
        return {
            "available": True, "normalizedTime": True,
            "unstablePoleCount": int(np.sum(poles.real > tolerance)),
            "poleTolerance": tolerance, "modes": modes,
            "symbolicExpressions": {
                "aSymLatex": sp.latex(grid.A_sym),
                "fLatex": sp.latex(grid.f),
                "gLatex": sp.latex(grid.g),
            },
        }

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
            "parameterValue": float(analysis.get("gridParameterValue", np.nan)),
            "partition": partition.tolist(),
            "partitionStateNames": partitionStateNames,
            "blockStarts": blockStarts.tolist(), "blocks": blocks,
            "maskedRows": list(maskRows), "maskedColumns": list(maskColumns),
            "estimatedShift": self.complexPoint(
                analysis["estimatedShiftMode12FromModes7And8"]
            ),
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
        plotDefinitions = (
            ("busVoltageMagnitude", "|V|", "pu", "component"),
            ("lineCurrentMagnitude", "I", "pu", "connection"),
            ("activePower", "P", "pu", "component"),
            ("reactivePower", "Q", "pu", "component"),
            ("busVoltageAngleDeg", "theta", "deg", "component"),
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
                elif column < len(busNames) and busNames[column] in originalNames:
                    ownerName = busNames[column]
                    owner = busIds[originalNames.index(ownerName)]
                else:
                    continue
                signals.append(self.makeSignal(
                    owner, ownerKind, 
                    f"{label}-{ownerName}", unit, time, matrix[:, column],
                ))

        systemId = re.sub(r"[^a-zA-Z0-9_-]", "-", self.system.name).lower()
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
        if "load" in name: return "load", "load"
        return "generic", "device"
