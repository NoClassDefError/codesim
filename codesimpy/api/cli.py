"""Resident line-delimited JSON service for the VS Code extension."""

import json
import sys
from typing import Any

import numpy as np

from ..core import SmallSignalAnalyzer
from .output_json_factory import OutputJsonFactory
from .system_factory import SystemFactory


class CLI:
    def __init__(self) -> None:
        self.outputJsonFactory = OutputJsonFactory()
        self.system = None
        self.systemName = ""
        self.parameters: dict[str, Any] = {}
        self.options: dict[str, Any] = {}
        self.modelKey = ""
        self.operatingPoint = None
        self.running = True

    @classmethod
    def run(cls) -> None:
        cls().serve()

    def serve(self) -> None:
        for line in sys.stdin:
            if not self.running:
                break
            request = None
            try:
                request = json.loads(line)
                self.dispatch(request)
                if not self.running:
                    break
            except Exception as error:
                self.outputJsonFactory.writeError(
                    request.get("id") if isinstance(request, dict) else None,
                    error,
                )

    def dispatch(self, request: dict[str, Any]) -> None:
        requestId = request.get("id")
        method = request["method"]
        params = request.get("params", {})
        if method == "getSystems":
            self.outputJsonFactory.writeResponse(requestId, SystemFactory.systemNames)
        elif method == "model.load":
            snapshotFile, descriptor = self.loadModel(params)
            self.outputJsonFactory.writeResponse(requestId, {
                "systemName": self.systemName,
                "parameters": self.parameters,
                "options": self.options,
                "descriptor": descriptor,
                "snapshotFile": str(snapshotFile),
            })
        elif method == "model.reset":
            self.resetModel()
            self.outputJsonFactory.writeResponse(requestId, {"reset": True})
        elif method == "simulation.start":
            self.runSimulation(requestId, params)
        elif method == "smallSignal.run":
            self.runSmallSignal(requestId, params)
        elif method == "interaction.run":
            self.runInteraction(requestId, params)
        elif method == "server.shutdown":
            self.outputJsonFactory.writeResponse(requestId, {"shutdown": True})
            self.running = False
        else:
            raise KeyError(f"unknown method: {method}")

    def loadModel(self, params: dict[str, Any]):
        systemName = params.get("systemName", self.systemName)
        parameters = params.get("parameters", {})
        options = params.get("options", {})
        modelOptions = {
            name: value for name, value in options.items()
            if name not in ("RunTimeDomain", "RunSmallSignal", "RunInteractionAnalysis")
        }
        modelKey = json.dumps(
            self.outputJsonFactory.jsonSafe({
                "systemName": systemName,
                "parameters": parameters,
                "options": modelOptions,
            }), sort_keys=True,
        )
        if self.system is None or modelKey != self.modelKey:
            self.system, self.parameters, self.options = SystemFactory.create(
                systemName, parameters, modelOptions,
            )
            self.system.outputJsonFactory.preserveExisting = True
            self.systemName = systemName
            self.modelKey = modelKey
            self.operatingPoint = None
        return self.system.outputJsonFactory.saveSnapshot({})

    def resetModel(self) -> None:
        self.system = None
        self.systemName = ""
        self.parameters = {}
        self.options = {}
        self.modelKey = ""
        self.operatingPoint = None

    def getOperatingPoint(self):
        if self.operatingPoint is None:
            self.operatingPoint = self.system.initialize(
                self.options["StartTime_s"],
                ResidualTolerance=self.options["ResidualTolerance"],
            )
        return self.operatingPoint

    def runSimulation(self, requestId: Any, params: dict[str, Any]) -> None:
        self.loadModel(params)
        operatingPoint = self.getOperatingPoint()
        time_s = np.arange(
            self.options["StartTime_s"], self.options["EndTime_s"],
            self.options["OutputStep_s"], dtype=float,
        )
        time_s = np.unique(np.r_[
            time_s, self.options["EndTime_s"],
            np.asarray(self.options["Breakpoints_s"], dtype=float),
        ])
        time_s = time_s[
            (time_s >= self.options["StartTime_s"])
            & (time_s <= self.options["EndTime_s"])
        ]
        self.system.outputJsonFactory.beginSimulation(requestId)
        self.outputJsonFactory.writeEvent(
            "simulation.started", requestId,
            systemName=self.systemName, sampleCount=time_s.size,
        )
        try:
            if self.systemName in ("VSGSMIBSystem", "VSGSMIBAVCSystem"):
                simulation = self.system.simulateFault(
                    time_s, operatingPoint["state"], saveSnapshot=False,
                )
            elif self.systemName == "CIGREMV14System":
                simulation = self.system.simulateFault(
                    self.options["FaultMode"], operatingPoint["state"],
                    saveSnapshot=False,
                )
            else:
                simulation = self.system.simulate(
                    time_s, InitialState=operatingPoint["state"],
                    MaxStep_s=self.options["MaxStep_s"],
                    Breakpoints_s=self.options["Breakpoints_s"],
                    saveSnapshot=False,
                )
            simulation["initialization"] = operatingPoint["initialization"]
            snapshotFile, descriptor = self.system.outputJsonFactory.saveSnapshot(simulation)
            self.outputJsonFactory.writeEvent(
                "simulation.completed", requestId,
                systemName=self.systemName,
            )
            self.outputJsonFactory.writeResponse(requestId, {
                "descriptor": descriptor, "snapshotFile": str(snapshotFile),
            })
        finally:
            self.system.outputJsonFactory.endSimulation()

    def runSmallSignal(self, requestId: Any, params: dict[str, Any]) -> None:
        self.loadModel(params)
        analysis = self.system.smallSignal.analyze(self.getOperatingPoint())
        snapshotFile, descriptor = self.system.outputJsonFactory.saveSnapshot({})
        self.outputJsonFactory.writeResponse(requestId, {
            "descriptor": descriptor,
            "snapshotFile": str(snapshotFile),
            "unstablePoleCount": analysis["unstablePoleCount"],
        })

    def runInteraction(self, requestId: Any, params: dict[str, Any]) -> None:
        self.loadModel(params)
        self.system.smallSignal.analyze(self.getOperatingPoint())
        self.runInteractionAnalysis()
        snapshotFile, descriptor = self.system.outputJsonFactory.saveSnapshot({})
        self.outputJsonFactory.writeResponse(requestId, {
            "descriptor": descriptor, "snapshotFile": str(snapshotFile),
        })

    def runInteractionAnalysis(self):
        if self.systemName != "HybridSystem" or not self.system.devices.get("gfl"):
            raise ValueError("interaction analysis requires HybridSystem with GFL enabled")
        vsgIndices = [
            self.system.stateNames.index(str(symbol)) + 1
            for symbol in self.system.devices["vsg"].x
        ]
        gflIndices = [
            self.system.stateNames.index(str(symbol)) + 1
            for symbol in self.system.devices["gfl"].x
        ]
        used = set(vsgIndices + gflIndices)
        networkIndices = [
            index for index in range(1, len(self.system.stateNames) + 1)
            if index not in used
        ]
        partition = vsgIndices + gflIndices + networkIndices
        blockStarts = [1, 1 + len(vsgIndices), 1 + len(vsgIndices) + len(gflIndices)]
        maskedIndices = ([7, 8], [11, 12])
        modalMatrix, stateMatrix, partitionedMatrix, reconstructedMatrix = (
            self.system.smallSignal.partitionSubsystem(
                partition, blockStarts, maskedIndices,
            )
        )
        analysis = {
            "partition": partition,
            "dIdx": blockStarts,
            "blockNames": ["GFM", "GFL", "Network / source"],
            "maskedIdx": maskedIndices,
            "gridParameterName": str(self.system.rlGrid.Lsym[0]),
            "gridParameterValue": self.system.parameters["Lg"],
            "DAll": modalMatrix,
            "AOriginal": stateMatrix,
            "APartitioned": partitionedMatrix,
            "ABack": reconstructedMatrix,
            "estimatedShiftMode12FromModes7And8": SmallSignalAnalyzer.estimateShift(
                modalMatrix, 12, [7, 8],
            ),
            "shiftTable": self.system.smallSignal.listEigenvalueShift(
                maskedIndices, partition, blockStarts,
            ),
            "modalTable": SmallSignalAnalyzer.analyzeModes(
                stateMatrix,
                self.system.stateNames,
                [str(index) for index in range(1, len(self.system.stateNames) + 1)],
            )["modeTable"],
        }
        self.system.outputJsonFactory.latestInteractionAnalysis = (
            self.system.outputJsonFactory.serializeInteractionAnalysis(analysis)
        )
        return analysis


if __name__ == "__main__":
    CLI.run()
