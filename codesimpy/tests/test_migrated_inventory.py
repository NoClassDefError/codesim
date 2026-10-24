import unittest

import numpy as np

import codesimpy
from codesimpy.api import SystemFactory


class MigratedInventoryTests(unittest.TestCase):
    def test_cigre_converter_defaults_match_simulink_reference(self):
        parameters, _ = SystemFactory.defaultParameters("CIGREMV14System", {}, {})
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

    def test_all_systems_are_exposed(self):
        self.assertEqual(SystemFactory.systemNames, [
            "HybridSystem", "HybridGFMGFLSystem", "VSGSMIBSystem", "VSGSMIBAVCSystem", "GFLLVRTSystem",
            "ParallelVSGSystem", "SGSMIBSystem", "IEEE13System",
            "CIGREMV14System",
        ])

    def test_hybrid_gfm_gfl_reduces_cigre_to_four_nodes(self):
        system, _, _ = SystemFactory.create("HybridGFMGFLSystem")
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
                     "VSGCCAVC", "VSGCL", "VSGLongTerm", "ZeroCurrent", "ZIP"):
            self.assertTrue(hasattr(codesimpy, name), name)


if __name__ == "__main__":
    unittest.main()
