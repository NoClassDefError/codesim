import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from codesimpy.api import SystemFactory
from codesimpy.components import VSGCCAVC


class VSGSMIBTests(unittest.TestCase):
    def test_avc_system_initializes_and_simulates(self):
        system, _, options = SystemFactory.create("VSGSMIBAVCSystem")
        self.assertIsInstance(system.devices["vsg"], VSGCCAVC)
        point = system.initialize(ResidualTolerance=options["ResidualTolerance"])
        result = system.simulateFault(
            np.linspace(0, 0.002, 5), point["state"], saveSnapshot=False,
        )
        self.assertEqual(system.name, "VSGSMIBAVCSystem")
        self.assertEqual(result["state"].shape, (5, 14))
        self.assertEqual(result["signals"]["irefDQ"].shape, (5, 2))

    def test_both_device_models_initialize(self):
        for model in ("VSGCC", "VSGCL"):
            with self.subTest(model=model):
                system, _, options = SystemFactory.create(
                    "VSGSMIBSystem", options={"DeviceModel": model}
                )
                point = system.initialize(
                    ResidualTolerance=options["ResidualTolerance"]
                )
                self.assertLess(point["initialization"]["residualInfNorm"], 1e-4)
                self.assertLess(
                    point["initialization"]["powerFlow"]["residualInfNorm"], 1e-4
                )

    def test_fault_simulation_and_descriptor(self):
        system, _, _ = SystemFactory.create("VSGSMIBSystem")
        point = system.initialize()
        result = system.simulateFault(
            np.linspace(0, 0.002, 5), point["state"], saveSnapshot=False,
        )
        self.assertEqual(result["state"].shape, (5, 14))
        with tempfile.TemporaryDirectory() as directory:
            system.outputJsonFactory.outputDirectory = Path(directory)
            snapshot, descriptor = system.outputJsonFactory.saveSnapshot(result)
            self.assertTrue(snapshot.exists())
            self.assertEqual(descriptor["system"]["name"], "VSGSMIBSystem_VSGCC")

    def test_snapshot_merges_independent_results(self):
        with tempfile.TemporaryDirectory() as directory:
            outputDirectory = Path(directory)
            simulationSystem, _, _ = SystemFactory.create("VSGSMIBSystem")
            simulationSystem.outputJsonFactory.outputDirectory = outputDirectory
            point = simulationSystem.initialize()
            simulation = simulationSystem.simulateFault(
                np.linspace(0, 0.002, 5), point["state"], saveSnapshot=False,
            )
            snapshot, first = simulationSystem.outputJsonFactory.saveSnapshot(simulation)
            first["layout"] = {"nodes": {"bus-1": {"x": 10, "y": 20}}}
            first["interactionAnalysis"] = {
                "available": True, "matrices": {"dAll": {}}
            }
            snapshot.write_text(json.dumps(first), encoding="utf-8")

            analysisSystem, _, _ = SystemFactory.create("VSGSMIBSystem")
            analysisSystem.outputJsonFactory.outputDirectory = outputDirectory
            operatingPoint = analysisSystem.initialize()
            analysisSystem.smallSignal.analyze(operatingPoint)
            _, merged = analysisSystem.outputJsonFactory.saveSnapshot({})

            self.assertEqual(len(merged["signals"]), len(first["signals"]))
            self.assertEqual(merged["layout"], first["layout"])
            self.assertTrue(merged["interactionAnalysis"]["available"])
            self.assertTrue(merged["smallSignal"]["available"])
            self.assertIn("symbolicExpressions", merged["smallSignal"])

