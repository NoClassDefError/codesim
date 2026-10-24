import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from codesimpy.api import SystemFactory
from codesimpy.components import VSGCCAVC


class VSGSMIBTests(unittest.TestCase):
    def test_transient_voltage_decomposition_reports_progress(self):
        system, _, options = SystemFactory.create("VSGSMIBSystem")
        point = system.initialize(ResidualTolerance=options["ResidualTolerance"])
        progress = io.StringIO()

        with contextlib.redirect_stderr(progress):
            system.transientVoltage.decompose(
                {
                    "time_s": np.array([0.0]),
                    "state": point["state"][None, :],
                    "referenceTrace": point["reference"][None, :],
                },
                "delta_vsg",
                angleStateName="delta_vsg",
            )

        messages = progress.getvalue().splitlines()
        self.assertIn("starting decomposition of 1/1 samples", messages[0])
        self.assertTrue(any("running EMT replay" in message for message in messages))
        self.assertTrue(any("processed 1/1 QSS samples (100%)" in message for message in messages))
        self.assertIn("complete; 1/1 QSS samples converged", messages[-1])

    def test_avc_system_initializes_and_simulates(self):
        system, _, options = SystemFactory.create("VSGSMIBAVCSystem")
        self.assertIsInstance(system.devices["vsg"], VSGCCAVC)
        point = system.initialize(ResidualTolerance=options["ResidualTolerance"])
        result = system.simulate(
            np.linspace(0, 0.002, 5), InitialState=point["state"], saveSnapshot=False,
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
        result = system.simulate(
            np.linspace(0, 0.002, 5), InitialState=point["state"], saveSnapshot=False,
        )
        self.assertEqual(result["state"].shape, (5, 14))
        with tempfile.TemporaryDirectory() as directory:
            system.outputJsonFactory.outputDirectory = Path(directory)
            snapshot, descriptor = system.outputJsonFactory.saveSnapshot(result)
            self.assertTrue(snapshot.exists())
            self.assertEqual(descriptor["system"]["name"], "VSGSMIBSystem_VSGCC")

    def test_angle_fault_uses_scipy_event(self):
        parameters = {
            "clearMode": "angle", "faultStart_s": 0.001,
            "minimumFaultDuration_s": 0.002, "clearAngle_rad": 0.02,
            "faultVoltage_pu": 0.0, "voltageRamp_s": 1e-4,
            "validationTime_s": 0.02,
        }
        system, _, options = SystemFactory.create(
            "VSGSMIBSystem", parameters=parameters,
        )
        point = system.initialize(ResidualTolerance=options["ResidualTolerance"])
        result = system.simulate(
            np.linspace(0, 0.02, 201), InitialState=point["state"],
            SolverSettings=options["SolverSettings"],
            Breakpoints_s=options["Breakpoints_s"], saveSnapshot=False,
        )

        self.assertEqual(result["events"]["name"], ["faultClearing"])
        self.assertGreaterEqual(result["clearingTime_s"], 0.003)
        eventState = result["events"]["state"][0]
        stateIndex = system.stateNames.index(
            f"{system.clearingState}{system.devices['vsg'].index}"
        )
        self.assertAlmostEqual(
            np.sin((eventState[stateIndex] - parameters["clearAngle_rad"]) / 2),
            0.0, places=9,
        )

    def test_qss_uses_rotating_frame_initialization_residual(self):
        system, _, options = SystemFactory.create("VSGSMIBSystem")
        point = system.initialize(ResidualTolerance=options["ResidualTolerance"])
        result = system.simulate(
            np.linspace(0, 0.002, 5), InitialState=point["state"], saveSnapshot=False,
        )

        decomposition = system.transientVoltage.decompose(
            result, "delta_vsg", angleStateName="delta_vsg",
        )

        self.assertTrue(np.all(decomposition["qssConverged"]))
        self.assertLess(np.max(decomposition["qssResidualNorm"]), 1e-8)
        np.testing.assert_allclose(
            decomposition["qssVoltage"], decomposition["actualVoltage"], atol=1e-8,
        )
        self.assertTrue(np.all(np.isfinite(decomposition["fastJacobianCondition"])))

        constantRate = system.transientVoltage.decompose(
            {
                "time_s": np.array([0.0]),
                "state": point["state"][None, :],
                "referenceTrace": point["reference"][None, :],
            },
            "delta_vsg",
            angleStateName="delta_vsg",
            angleRate_rad_s=1.0,
        )
        gridBus = system.busNames.index("Infinite bus")
        self.assertAlmostEqual(
            abs(constantRate["firstOrderError"][0, gridBus]), 0.0, places=12,
        )
        serialized = system.outputJsonFactory.serializeTransientVoltage(constantRate)
        firstOrderMagnitude = np.asarray(
            serialized["components"]["firstOrder"]["magnitude"]
        )
        errorMagnitude = np.asarray(
            serialized["components"]["firstOrderError"]["magnitude"]
        )
        np.testing.assert_allclose(firstOrderMagnitude, errorMagnitude, atol=1e-15)
        self.assertLess(np.max(firstOrderMagnitude), 1e-2)

        steppedReference = system.getReference(0.0)
        sourceReference = system.referenceNames.index(
            str(system.devices["source"].uref[0])
        )
        steppedReference[sourceReference] = 0.5
        stepped = system.transientVoltage.decompose(
            {
                "time_s": np.array([0.0]),
                "state": point["state"][None, :],
                "referenceTrace": steppedReference[None, :],
            },
            "delta_vsg",
            angleStateName="delta_vsg",
        )
        self.assertTrue(stepped["qssConverged"][0])
        self.assertLess(stepped["qssResidualNorm"][0], 1e-8)
        deltaIndex = system.stateNames.index("delta_vsg")
        slowDerivative = system.rlGrid.f_numeric(
            stepped["qssState"][0], steppedReference,
        )[deltaIndex]
        self.assertGreater(abs(slowDerivative), 1e-4)

    def test_transient_voltage_components_approximately_reconstruct_voltage(self):
        system, _, options = SystemFactory.create("VSGSMIBSystem")
        point = system.initialize(ResidualTolerance=options["ResidualTolerance"])
        result = system.simulate(
            np.linspace(0.195, 0.205, 21), InitialState=point["state"], saveSnapshot=False,
        )

        decomposition = system.transientVoltage.decompose(
            result, "delta_vsg", angleStateName="delta_vsg",
        )
        componentSum = (
            decomposition["qssVoltage"]
            + decomposition["firstOrderError"]
            + decomposition["emtVoltage"]
        )

        np.testing.assert_allclose(
            componentSum, decomposition["reconstructedVoltage"], atol=1e-12,
        )
        np.testing.assert_allclose(
            decomposition["actualVoltage"] - componentSum,
            decomposition["reconstructionError"],
            atol=1e-12,
        )
        self.assertLess(
            np.max(np.abs(decomposition["reconstructionError"])), 0.02,
        )
        self.assertGreater(
            np.max(np.abs(decomposition["emtVoltage"])), 0.1,
        )
        self.assertLess(
            np.max(np.abs(decomposition["emtVoltage"])), 0.6,
        )
        serialized = system.outputJsonFactory.serializeTransientVoltage(decomposition)
        self.assertIn("reconstructed", serialized["components"])
        self.assertIn("reconstructionError", serialized["components"])

    def test_transient_voltage_supports_multiple_slow_states(self):
        system, _, options = SystemFactory.create("VSGSMIBSystem")
        point = system.initialize(ResidualTolerance=options["ResidualTolerance"])
        result = system.simulate(
            np.linspace(0.195, 0.205, 21), InitialState=point["state"], saveSnapshot=False,
        )
        slowStateNames = ["delta_vsg", "vCd_vsg", "vCq_vsg"]

        decomposition = system.transientVoltage.decompose(
            result, slowStateNames, angleStateName="delta_vsg",
        )
        angleOnly = system.transientVoltage.decompose(
            result, "delta_vsg", angleStateName="delta_vsg",
        )

        self.assertEqual(decomposition["slowStateNames"], slowStateNames)
        self.assertEqual(
            decomposition["slowStateRates_per_s"].shape,
            (result["time_s"].size, len(slowStateNames)),
        )
        np.testing.assert_allclose(
            decomposition["angleRate_rad_s"],
            decomposition["slowStateRates_per_s"][:, 0],
        )
        self.assertTrue(
            set(slowStateNames).isdisjoint(decomposition["fastStateNames"])
        )
        self.assertTrue(np.all(decomposition["qssConverged"]))
        self.assertLess(np.max(decomposition["qssResidualNorm"]), 1e-8)
        self.assertLess(np.max(np.abs(decomposition["reconstructionError"])), 1e-3)
        self.assertGreater(
            np.max(np.abs(
                decomposition["firstOrderError"]
                - angleOnly["firstOrderError"]
            )),
            1e-4,
        )

        serialized = system.outputJsonFactory.serializeTransientVoltage(decomposition)
        self.assertEqual(serialized["slowStateNames"], slowStateNames)
        self.assertEqual(
            np.asarray(serialized["slowStateRates_per_s"]).shape,
            (result["time_s"].size, len(slowStateNames)),
        )

        thinned = system.transientVoltage.decompose(
            result, slowStateNames, angleStateName="delta_vsg", maxSamples=10,
        )
        self.assertEqual(thinned["sourceSampleCount"], result["time_s"].size)
        self.assertEqual(thinned["time_s"].size, 10)
        self.assertEqual(thinned["sampleIndices"][0], 0)
        self.assertEqual(thinned["sampleIndices"][-1], result["time_s"].size - 1)

    def test_transient_voltage_survives_unavailable_linearization(self):
        system, _, options = SystemFactory.create("VSGSMIBSystem")
        point = system.initialize(ResidualTolerance=options["ResidualTolerance"])
        result = system.simulate(
            np.linspace(0, 0.002, 3), InitialState=point["state"], saveSnapshot=False,
        )
        original = system.rlGrid.getStateMatrix
        system.rlGrid.getStateMatrix = lambda *_: np.full(
            (len(system.stateNames), len(system.stateNames)), np.nan
        )
        try:
            decomposition = system.transientVoltage.decompose(
                result, "delta_vsg", angleStateName="delta_vsg",
            )
        finally:
            system.rlGrid.getStateMatrix = original

        self.assertTrue(np.isnan(decomposition["firstOrderError"]).all())
        self.assertTrue(np.isinf(decomposition["fastJacobianCondition"]).all())
        self.assertFalse(np.any(decomposition["firstOrderAvailable"]))
        serialized = system.outputJsonFactory.serializeTransientVoltage(decomposition)
        json.dumps(
            system.outputJsonFactory.jsonSafe(serialized), allow_nan=False,
        )

    def test_snapshot_merges_independent_results(self):
        with tempfile.TemporaryDirectory() as directory:
            outputDirectory = Path(directory)
            simulationSystem, _, _ = SystemFactory.create("VSGSMIBSystem")
            simulationSystem.outputJsonFactory.outputDirectory = outputDirectory
            point = simulationSystem.initialize()
            simulation = simulationSystem.simulate(
                np.linspace(0, 0.002, 5), InitialState=point["state"], saveSnapshot=False,
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

