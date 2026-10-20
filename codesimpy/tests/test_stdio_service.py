import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
            system.simulateFault(
                np.array([0, 1e-4, 2e-4]), point["state"], saveSnapshot=False,
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
        outputIds = {signal["id"] for signal in signals[:firstState]}
        self.assertTrue(any("busvoltagemagnitude" in signalId for signalId in outputIds))
        self.assertTrue(any("line-current" in signalId for signalId in outputIds))
        self.assertTrue(any("activepower" in signalId for signalId in outputIds))
        self.assertTrue(any("reactivepower" in signalId for signalId in outputIds))
        self.assertTrue(any("busvoltageangledeg" in signalId for signalId in outputIds))
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


if __name__ == "__main__":
    unittest.main()
