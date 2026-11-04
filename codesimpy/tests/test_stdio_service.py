import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from codesimpy.api.cli import CLI
from codesimpy.systems import GFLLVRTSystem, VSGSMIBSystem


class StdioServiceTests(unittest.TestCase):
    def test_model_load_exposes_only_editable_parameters(self):
        service = CLI()
        request = {"systemName": "GFLLVRTSystem", "parameters": {}, "options": {}}
        with tempfile.TemporaryDirectory() as directory:
            service.loadModel(request, saveSnapshot=False)
            service.system.outputJsonFactory.outputDirectory = Path(directory)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                service.dispatch({"id": 1, "method": "model.load", "params": request})
            result = json.loads(output.getvalue())["result"]

        hidden = {"wBase", "Rg", "Lg", "breakpoints_s", "gridVoltage"}
        self.assertFalse(hidden & result["parameters"].keys())
        self.assertFalse(hidden & set(result["descriptor"]["system"]["parameterNames"]))
        self.assertEqual(
            set(result["parameters"]),
            {row["id"] for row in result["descriptor"]["system"]["parameters"]},
        )
        self.assertTrue({"K1", "Id2"} <= result["parameters"].keys())
        self.assertTrue(
            {"Kad", "wAD", "Klvrt"}.isdisjoint(result["parameters"])
        )

    def test_resident_protocol_lists_systems_and_shuts_down(self):
        process = subprocess.Popen(
            [sys.executable, "-u", "-m", "codesimpy.api.cli"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        process.stdin.write('{"id":1,"method":"getSystems","params":{}}\n')
        process.stdin.write('{"id":2,"method":"server.shutdown","params":{}}\n')
        process.stdin.flush()
        systems = json.loads(process.stdout.readline())
        shutdown = json.loads(process.stdout.readline())
        self.assertIn("VSGSMIBSystem", systems["result"])
        self.assertTrue(shutdown["result"]["shutdown"])
        self.assertEqual(process.wait(timeout=10), 0)

    def test_integrator_streams_calculated_signal_chunks(self):
        system = VSGSMIBSystem(VSGSMIBSystem.defaultParameters())
        point = system.initialize()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            system.outputJsonFactory.beginSimulation(7)
            system.simulate(
                np.array([0, 1e-4, 2e-4]), InitialState=point["state"], saveSnapshot=False,
            )
            system.outputJsonFactory.endSimulation()
        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(messages[0]["type"], "simulation.chunk")
        self.assertEqual(messages[0]["requestId"], 7)
        self.assertTrue(messages[0]["signals"])
        signals = messages[0]["signals"]
        firstState = next(i for i, signal in enumerate(signals) if signal.get("category") == "state")
        self.assertTrue(all(signal.get("category") != "state" for signal in signals[:firstState]))
        self.assertTrue(all(signal.get("category") == "state" for signal in signals[firstState:]))
        outputLabels = {signal["label"].split("-")[0] for signal in signals[:firstState]}
        self.assertTrue({"|V|", "I", "P", "Q", "theta"} <= outputLabels)
        stateSignals = [
            signal for signal in signals
            if signal.get("category") == "state"
        ]
        self.assertEqual(len(stateSignals), len(system.stateNames))
        self.assertIn("delta", {signal["label"].split("_")[0] for signal in stateSignals})
        self.assertNotIn("dot_delta", {signal["label"] for signal in signals})

    def test_simulation_endpoint_streams_and_saves_final_snapshot(self):
        request = {
            "systemName": "VSGSMIBSystem", "parameters": {},
            "options": {"EndTime_s": 2e-4, "OutputStep_s": 1e-4},
        }
        service = CLI()
        service.loadModel(request)
        with tempfile.TemporaryDirectory() as directory:
            service.system.outputJsonFactory.outputDirectory = Path(directory)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                service.dispatch({"id": 3, "method": "simulation.start", "params": request})
            messages = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertIn("simulation.started", [item.get("type") for item in messages])
            self.assertIn("simulation.chunk", [item.get("type") for item in messages])
            response = next(item for item in messages if item.get("id") == 3)
            self.assertTrue(response["ok"])
            self.assertTrue(Path(response["result"]["snapshotFile"]).exists())
            self.assertIn("system", response["result"]["descriptor"])

    def test_transient_voltage_reuses_simulated_model_after_parameter_edit(self):
        request = {
            "systemName": "VSGSMIBSystem", "parameters": {},
            "options": {"EndTime_s": 2e-4, "OutputStep_s": 1e-4},
        }
        service = CLI()
        service.loadModel(request)
        with tempfile.TemporaryDirectory() as directory:
            service.system.outputJsonFactory.outputDirectory = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                service.runSimulation(1, request)
                service.runTransientVoltage(2, {
                    **request, "parameters": {"Pref": 1.0},
                    "slowStateNames": ["delta_vsg"], "maxSamples": 2,
                })
            self.assertTrue(service.system.outputJsonFactory.latestSimulation)
            self.assertEqual(
                len(service.system.outputJsonFactory.latestTransientVoltage["time_s"]), 2,
            )
            snapshot = next(Path(directory).glob("*-snapshot.json"))
            originalSignals = json.loads(snapshot.read_text(encoding="utf-8"))["signals"]
            restarted = CLI()
            restarted.loadModel(request, saveSnapshot=False)
            restarted.system.outputJsonFactory.outputDirectory = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                restarted.runTransientVoltage(3, {
                    **request, "slowStateNames": ["delta_vsg"], "maxSamples": 2,
                })
            self.assertEqual(
                len(restarted.system.outputJsonFactory.latestTransientVoltage["time_s"]), 2,
            )
            saved = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertEqual(saved["signals"], originalSignals)
            reopened = CLI()
            reopened.loadModel(request, saveSnapshot=False)
            reopened.system.outputJsonFactory.outputDirectory = Path(directory)
            _, descriptor = reopened.loadModel(request)
            self.assertTrue(descriptor["transientVoltage"]["available"])
            self.assertEqual(descriptor["signals"], originalSignals)
            saved.pop("simulationData")
            snapshot.write_text(json.dumps(saved), encoding="utf-8")
            legacy = CLI()
            legacy.loadModel(request, saveSnapshot=False)
            legacy.systemName = "VSGSMIBSystem"
            legacy.system.outputJsonFactory.outputDirectory = Path(directory)
            self.assertIsNotNone(legacy.system.outputJsonFactory.loadSimulationFromSnapshot())
            incompatibleParameters = VSGSMIBSystem.defaultParameters({
                "Pref": 0.75, "validationTime_s": 2e-4, "outputStep_s": 1e-4,
            })
            incompatible = VSGSMIBSystem(incompatibleParameters)
            incompatible.outputJsonFactory.outputDirectory = Path(directory)
            with self.assertRaisesRegex(ValueError, "does not match"):
                incompatible.outputJsonFactory.loadSimulationFromSnapshot()
            before = snapshot.read_bytes()
            incompatibleService = CLI()
            incompatibleRequest = {**request, "parameters": {"Pref": 0.75}}
            incompatibleService.loadModel(incompatibleRequest, saveSnapshot=False)
            incompatibleService.system.outputJsonFactory.outputDirectory = Path(directory)
            with self.assertRaisesRegex(ValueError, "does not match"):
                incompatibleService.runTransientVoltage(4, {
                    **incompatibleRequest,
                    "slowStateNames": ["delta_vsg"], "maxSamples": 2,
                })
            self.assertEqual(snapshot.read_bytes(), before)
            incompatible.outputJsonFactory.saveSnapshot()
            self.assertFalse(json.loads(snapshot.read_text(encoding="utf-8"))["signals"])


if __name__ == "__main__":
    unittest.main()
