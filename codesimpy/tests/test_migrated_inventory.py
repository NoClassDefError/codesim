import unittest

import codesimpy
from codesimpy.api import SystemFactory


class MigratedInventoryTests(unittest.TestCase):
    def test_all_systems_are_exposed(self):
        self.assertEqual(SystemFactory.systemNames, [
            "HybridSystem", "VSGSMIBSystem", "GFLLVRTSystem",
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
