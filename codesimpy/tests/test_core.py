from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import sympy as sp

from codesimpy.core import Device, RLGrid, SmallSignalAnalyzer, System


class VoltageSource(Device):
    def __init__(self, index: int):
        super().__init__(1.0, 1.0, "Voltage", index, {"k": 2.0},
                         ("va_state", "vb_state"), ("va_ref", "vb_ref"))

    def getStateAndOutputEquationsSym(self):
        return (
            [self.p["k"]["sym"] * (self.uref[0] - self.x[0]),
             self.p["k"]["sym"] * (self.uref[1] - self.x[1])],
            list(self.x),
        )

    def getPowerFlowEquations(self, V, theta, P, Q):
        return [V * sp.cos(theta) - self.uref[0],
                V * sp.sin(theta) - self.uref[1]]

    def initFromPowerFlow(self, V, theta, P, Q):
        return [V * np.cos(theta), V * np.sin(theta)]

    def getFInit(self):
        return self.f


class ZeroCurrent(Device):
    def __init__(self, index: int):
        super().__init__(1.0, 1.0, "Current", index, {}, (), ())

    def getStateAndOutputEquationsSym(self):
        return [], [0, 0]

    def getPowerFlowEquations(self, V, theta, P, Q):
        return [P, Q]

    def initFromPowerFlow(self, V, theta, P, Q):
        return []

    def getFInit(self):
        return []


class TwoBusSystem(System):
    def calculateSignals(self, time_s, state, networkSignals):
        return self.busSignals(networkSignals, [0, 1], 0)


class CoreTests(unittest.TestCase):
    @staticmethod
    def makeSystem():
        network = {
            "A": np.array([[1.0], [-1.0]]), "L": np.array([0.2]),
            "R": np.array([0.1]), "busNames": ["Source", "Remote"],
        }
        devices = {
            "Vdev": [VoltageSource(1), VoltageSource(2)],
            "Idev": [ZeroCurrent(1), ZeroCurrent(2)],
        }
        references = {"va_ref_1": 1.0, "vb_ref_1": 0.0,
                      "va_ref_2": 1.0, "vb_ref_2": 0.0}
        return TwoBusSystem(
            "two-bus", network, devices,
            {"Vbase": 1.0, "Sbase": 1.0, "frequency_Hz": 50.0}, references,
        )

    def test_device_names_and_base_conversion(self):
        device = VoltageSource(3)
        self.assertEqual([str(x) for x in device.x], ["va_state_3", "vb_state_3"])
        self.assertEqual(device.p["k"]["num"], 2.0)
        device.convertToAnotherBase(2.0, 4.0)
        self.assertAlmostEqual(device.Outputscale, 0.5)
        self.assertAlmostEqual(device.Inputscale, 2.0)

    def test_grid_symbolic_and_numeric_interfaces(self):
        system = self.makeSystem()
        grid = system.rlGrid
        state = np.array([0, 0, 1, 0, 1, 0], dtype=float)
        reference = system.getReference(0)
        np.testing.assert_allclose(grid.f_numeric(state, reference), 0, atol=1e-12)
        branch, voltage, current = grid.g_numeric(state, reference)
        np.testing.assert_allclose(branch, [0, 0])
        np.testing.assert_allclose(voltage, [1, 0, 1, 0])
        np.testing.assert_allclose(current, 0)
        self.assertEqual(grid.getStateMatrix(state, reference).shape, (6, 6))

    def test_integration_and_json_snapshot(self):
        system = self.makeSystem()
        state = np.array([0, 0, 1, 0, 1, 0], dtype=float)
        result = system.simulate([0, 1e-4, 2e-4], InitialState=state,
                                 SolverSettings={"max_step": 5e-5}, saveSnapshot=False)
        np.testing.assert_allclose(result["state"], np.tile(state, (3, 1)), atol=1e-11)
        with tempfile.TemporaryDirectory() as directory:
            system.outputJsonFactory.outputDirectory = Path(directory)
            snapshot, descriptor = system.outputJsonFactory.saveSnapshot(result)
            self.assertTrue(snapshot.exists())
            loaded = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertEqual(loaded["schemaVersion"], 1)
            self.assertEqual(len(descriptor["connections"]), 3)
            self.assertEqual(
                len([signal for signal in descriptor["signals"] if signal["category"] == "state"]),
                len(system.stateNames),
            )

    def test_solve_ivp_integration_respects_breakpoints(self):
        system = self.makeSystem()
        initial = np.array([0, 0, 1, 0, 1, 0], dtype=float)
        state, time_s, event = system.integrate(
            [0, 1e-4, 2e-4], initial, system.getReference(),
            {**system.solverSettings, "max_step": 5e-5}, [1.5e-4],
        )

        np.testing.assert_allclose(time_s, [0, 1e-4, 2e-4])
        np.testing.assert_allclose(state, np.tile(initial, (3, 1)), atol=1e-11)
        self.assertEqual(event["time_s"], [])

    def test_solve_ivp_event_continues_from_detected_state(self):
        system = self.makeSystem()
        initial = np.array([0, 0, 1, 0, 1, 0], dtype=float)
        target = 1.25e-4
        system.eventName = "test"
        system.eventStartTime_s = 0.0
        system.eventHandler = lambda time_s, _state: time_s - target

        result = system.simulate(
            [0, 1e-4, 2e-4], InitialState=initial,
            SolverSettings={"max_step": 5e-5}, saveSnapshot=False,
        )

        self.assertEqual(result["events"]["name"], ["test"])
        self.assertAlmostEqual(result["events"]["time_s"][0], target)
        np.testing.assert_allclose(result["state"], np.tile(initial, (3, 1)))

    def test_small_signal_and_kron_reduction(self):
        analysis = SmallSignalAnalyzer.analyzeModes(
            [[-1, 0], [0, -2]], ["x1", "x2"]
        )
        self.assertEqual(analysis["participation"].shape, (2, 2))
        A = np.array([[1, 0], [-1, 1], [0, -1]], dtype=float)
        reducedA, reducedL, reducedR = RLGrid.kronReduction(A, [1, 2], [3, 4], [1])
        self.assertEqual(reducedA.shape, (2, 1))
        np.testing.assert_allclose([reducedL[0], reducedR[0]], [3, 7])

    def test_transient_voltage_uses_system_base_frequency(self):
        system = self.makeSystem()
        self.assertFalse(hasattr(system, "wBase"))
        state = np.array([0, 0, 1, 0, 1, 0], dtype=float)
        simulation = system.simulate(
            [0, 1e-4, 2e-4], InitialState=state,
            SolverSettings={"max_step": 5e-5}, saveSnapshot=False,
        )
        decomposition = system.transientVoltage.decompose(
            simulation, "va_state_1", angleStateName="va_state_1",
        )
        self.assertEqual(decomposition["qssVoltage"].shape, (3, 2))
        self.assertEqual(decomposition["emtVoltage"].shape, (3, 2))


if __name__ == "__main__":
    unittest.main()
