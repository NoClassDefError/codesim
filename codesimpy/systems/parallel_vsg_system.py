"""Two grid-forming converters connected to an infinite bus."""

import numpy as np

from ..components import Infbus, VSGCL, ZeroCurrent
from ..core import System


class ParallelVSGSystem(System):
    def __init__(self, p):
        vsg1 = VSGCL(p["Vbase"], p["Sbase"], "parallel_vsg1")
        vsg2 = VSGCL(p["Vbase"], p["Sbase"], "parallel_vsg2")
        source = Infbus(p["Vbase"], p["Sbase"], "parallel_grid")
        devices = {
            "Vdev": [vsg1, vsg2, source],
            "Idev": [ZeroCurrent(p["Vbase"], p["Sbase"], "parallel_zero1"),
                     ZeroCurrent(p["Vbase"], p["Sbase"], "parallel_zero2"),
                     ZeroCurrent(p["Vbase"], p["Sbase"], "parallel_grid_zero")],
            "vsg1": vsg1, "vsg2": vsg2, "source": source,
        }
        refs = {
            str(vsg1.uref[0]): p["Pref"][0], str(vsg1.uref[1]): p["Vref"][0], str(vsg1.uref[2]): p["wref"][0],
            str(vsg2.uref[0]): p["Pref"][1], str(vsg2.uref[1]): p["Vref"][1], str(vsg2.uref[2]): p["wref"][1],
            str(source.uref[0]): p["gridVoltage"],
        }
        network = {"A": np.array([[1, 0], [0, 1], [-1, -1]], dtype=float),
                   "R": p["branchR"], "L": p["branchL"],
                   "busNames": ["VSG 1", "VSG 2", "Infinite bus"]}
        super().__init__("ParallelVSGSystem", network, devices,
                         {"Vbase": p["Vbase"], "Sbase": p["Sbase"], "frequency_Hz": p["frequency_Hz"]}, refs)
        self.solverSettings["max_step"] = 5e-3 / (2 * np.pi * p["frequency_Hz"])
        self.parameters, self.parameterNames = p, list(p)

    def calculateSignals(self, time_s, state, networkSignals):
        signals = self.busSignals(networkSignals, np.arange(self.rlGrid.n), self.rlGrid.n - 1)
        a = [self.stateNames.index(str(symbol)) for symbol in self.devices["vsg1"].x]
        b = [self.stateNames.index(str(symbol)) for symbol in self.devices["vsg2"].x]
        state = np.asarray(state)
        signals["vsgFilterCurrentMagnitude"] = np.column_stack((
            np.hypot(state[:, a[2]], state[:, a[3]]),
            np.hypot(state[:, b[2]], state[:, b[3]]),
        ))
        return signals
