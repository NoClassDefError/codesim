import importlib.util
import unittest

import numpy as np

import codesimpy
from codesimpy.systems import (
    CIGREMV14System, GFLLVRTSystem, HybridGFMGFLSystem, HybridSystem,
    IEEE13System, ParallelVSGSystem, SGSMIBSystem, VSGSMIBAVCSystem,
    VSGSMIBSystem, VSGSMIBSystemNoCapacitor,
)


SYSTEM_CLASSES = (
    HybridSystem, HybridGFMGFLSystem, VSGSMIBSystem, VSGSMIBAVCSystem,
    GFLLVRTSystem, ParallelVSGSystem, SGSMIBSystem, IEEE13System,
    CIGREMV14System, VSGSMIBSystemNoCapacitor,
)


class MigratedInventoryTests(unittest.TestCase):
    def test_each_system_class_owns_fresh_complete_defaults(self):
        for systemClass in SYSTEM_CLASSES:
            with self.subTest(system=systemClass.__name__):
                self.assertIn("defaultParameters", systemClass.__dict__)
                first = systemClass.defaultParameters()
                second = systemClass.defaultParameters()
                self.assertIsInstance(first, dict)
                self.assertIsNot(first, second)
                for name in ("validationTime_s", "outputStep_s",
                             "residualTolerance", "breakpoints_s"):
                    self.assertIn(name, first)

    def test_system_factory_is_removed(self):
        self.assertIsNone(importlib.util.find_spec("codesimpy.api.system_factory"))
        self.assertFalse(hasattr(codesimpy, "SystemFactory"))

    def test_time_domain_fault_parameters_use_one_schema(self):
        canonical = {
            "faultStart_s", "faultComplete_s", "recoveryStart_s",
            "recoveryComplete_s", "faultVoltage",
        }
        for systemClass in SYSTEM_CLASSES:
            with self.subTest(system=systemClass.__name__):
                self.assertTrue(canonical <= systemClass.defaultParameters().keys())

    def test_parameter_overrides_recalculate_derived_values(self):
        parameters = GFLLVRTSystem.defaultParameters({"SCR": 10, "rho": 0})
        self.assertEqual(parameters["Lg"], 0.1)
        self.assertEqual(parameters["Rg"], 0)

    def test_cigre_converter_defaults_match_simulink_reference(self):
        parameters = CIGREMV14System.defaultParameters()
        expected = {
            "GFLSbase_VA": 1.5e6, "GFLLf": 0.07,
            "GFLKpCc": 0.3, "GFLKiCc": 1,
            "GFLKpPll": 0.2, "GFLKiPll": 0.02,
            "GFLKpP": 0.02, "GFLKiP": 0.02,
            "GFLKpQ": 0.02, "GFLKiQ": 0.02,
            "VSGVref": 1.1,
        }
        for name, value in expected.items():
            with self.subTest(parameter=name):
                self.assertEqual(parameters[name], value)

    def test_gfl_lvrt_initializes_directly(self):
        parameters = GFLLVRTSystem.defaultParameters()
        system = GFLLVRTSystem(parameters)
        self.assertEqual(system.network["A"].shape, (1, 0))
        self.assertEqual(system.busNames, ["PCC / Infinite bus"])
        self.assertNotIn("capacitor", system.devices)
        self.assertEqual(len(system.devices["gfl"].x), 6)
        self.assertEqual(system.devices["gfl"].p["Rg"]["num"], parameters["Rg"])
        self.assertEqual(system.devices["gfl"].p["Lg"]["num"], parameters["Lg"])
        expected = {"K1": 0.3, "Id2": 1.0}
        for name, value in expected.items():
            with self.subTest(parameter=name):
                self.assertEqual(parameters[name], value)
                self.assertEqual(system.devices["gfl"].p[name]["num"], value)
        for name in ("Kad", "wAD", "Klvrt"):
            self.assertNotIn(name, parameters)
            self.assertNotIn(name, system.devices["gfl"].p)

    def test_gfl_lvrt_logs_internal_pcc_voltage_for_frontend(self):
        parameters = GFLLVRTSystem.defaultParameters({"validationTime_s": 1e-3})
        system = GFLLVRTSystem(parameters)
        simulation = system.simulate(np.array([0.0, 1e-3]), saveSnapshot=False)
        frontendSignals = system.outputJsonFactory.buildSignals(simulation)
        pccSignals = [
            signal for signal in frontendSignals
            if signal["label"].startswith("PCC voltage-")
        ]
        self.assertEqual(len(pccSignals), 1)
        self.assertEqual(pccSignals[0]["unit"], "pu")
        np.testing.assert_allclose(
            pccSignals[0]["values"], simulation["signals"]["pccVoltage"],
        )

    def test_hybrid_gfm_gfl_reduces_cigre_to_four_nodes(self):
        system = HybridGFMGFLSystem(HybridGFMGFLSystem.defaultParameters())
        self.assertEqual(system.network["busNames"], ["Infinite bus", "7", "8", "9"])
        self.assertEqual(system.network["A"].shape, (4, 3))
        np.testing.assert_allclose(system.network["R"], [
            0.00049751859510499465 + 0.001 + 0.08830125 + 0.13840125 + 0.04070625,
            0.052291875,
            0.01002,
        ])
        np.testing.assert_allclose(system.network["L"], [
            0.0049751859510499463 + 0.12 + 0.126195 + 0.197795 + 0.058175,
            0.0747325,
            0.01432,
        ])
        self.assertTrue(system.devices["gfl"].index.endswith("hybrid_cigre_gfl_bus7"))
        self.assertTrue(system.devices["vsg"].index.endswith("hybrid_cigre_vsg_bus9"))
        self.assertEqual(system.qssRequiredSlowStateNames, [
            "vPIoutd_hybrid_cigre_gfl_bus7",
            "vPIoutq_hybrid_cigre_gfl_bus7",
        ])

    def test_all_components_are_exposed(self):
        for name in ("Capacitor", "CPL", "GFLLongTerm", "GFLVSC",
                     "InductionMotor", "Infbus", "PQLoad", "SG", "VSGCC",
                     "VSGCCAVC", "VSGCL", "VSGNoCapacitor", "ZeroCurrent", "ZIP"):
            self.assertTrue(hasattr(codesimpy, name), name)


if __name__ == "__main__":
    unittest.main()
