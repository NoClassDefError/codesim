import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from codesimpy.api import SystemFactory
from codesimpy.api.cli import CLI


class StdioServiceTests(unittest.TestCase):
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
        system, _, _ = SystemFactory.create("VSGSMIBSystem")
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
            createSystem = SystemFactory.create

            def createInDirectory(*args, **kwargs):
                system, parameters, options = createSystem(*args, **kwargs)
                system.outputJsonFactory.outputDirectory = Path(directory)
                return system, parameters, options

            restarted = CLI()
            with patch.object(SystemFactory, "create", side_effect=createInDirectory):
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
            with patch.object(SystemFactory, "create", side_effect=createInDirectory):
                _, descriptor = reopened.loadModel(request)
            self.assertTrue(descriptor["transientVoltage"]["available"])
            self.assertEqual(descriptor["signals"], originalSignals)
            saved.pop("simulationData")
            snapshot.write_text(json.dumps(saved), encoding="utf-8")
            legacy = CLI()
            legacy.system, _, _ = SystemFactory.create(
                "VSGSMIBSystem", options=request["options"],
            )
            legacy.systemName = "VSGSMIBSystem"
            legacy.system.outputJsonFactory.outputDirectory = Path(directory)
            self.assertIsNotNone(legacy.system.outputJsonFactory.loadSimulationFromSnapshot())
            incompatible, _, _ = SystemFactory.create(
                "VSGSMIBSystem", {"Pref": 0.75}, request["options"],
            )
            incompatible.outputJsonFactory.outputDirectory = Path(directory)
            with self.assertRaisesRegex(ValueError, "does not match"):
                incompatible.outputJsonFactory.loadSimulationFromSnapshot()
            before = snapshot.read_bytes()
            with patch.object(SystemFactory, "create", side_effect=createInDirectory):
                with self.assertRaisesRegex(ValueError, "does not match"):
                    CLI().runTransientVoltage(4, {
                        **request, "parameters": {"Pref": 0.75},
                        "slowStateNames": ["delta_vsg"], "maxSamples": 2,
                    })
            self.assertEqual(snapshot.read_bytes(), before)
            incompatible.outputJsonFactory.saveSnapshot()
            self.assertFalse(json.loads(snapshot.read_text(encoding="utf-8"))["signals"])


if __name__ == "__main__":
    unittest.main()
