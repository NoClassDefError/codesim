import unittest

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
            "HybridSystem", "VSGSMIBSystem", "VSGSMIBAVCSystem", "GFLLVRTSystem",
            "ParallelVSGSystem", "SGSMIBSystem", "IEEE13System",
            "CIGREMV14System",
        ])

    def test_all_components_are_exposed(self):
        for name in ("Capacitor", "CPL", "GFLLongTerm", "GFLVSC",
                     "InductionMotor", "Infbus", "PQLoad", "SG", "VSGCC",
                     "VSGCCAVC", "VSGCL", "VSGLongTerm", "ZeroCurrent", "ZIP"):
            self.assertTrue(hasattr(codesimpy, name), name)


if __name__ == "__main__":
    unittest.main()
