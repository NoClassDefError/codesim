"""Four-node GFM/GFL reduction of the CIGRE MV14 feeder."""

import numpy as np

from ..components import Capacitor, GFLVSC, Infbus, VSGCC, ZeroCurrent
from ..core import System
from .cigre_mv14_system import CIGREMV14System


class HybridGFMGFLSystem(System):
    """Retain CIGRE buses 7, 8, 9 and replace the upstream feeder by an infinite bus.

    The original source--1--2--3--8 corridor is represented by one series-equivalent
    branch.  The original 7--8 and 8--9 branches are retained unchanged.  Loads and
    laterals outside this four-node corridor are intentionally omitted.
    """

    def __init__(self, p):
        incidence, branchR, branchL, busNames, busCapacitance = self.buildReducedNetwork()
        _, gflNode, middleNode, vsgNode = range(4)

        source = Infbus(1, p["Sbase_VA"], "hybrid_cigre_infbus")
        source.p["kA"]["num"] = 100

        bus7 = Capacitor(1, p["Sbase_VA"], "hybrid_cigre_bus7_lineC")
        bus8 = Capacitor(1, p["Sbase_VA"], "hybrid_cigre_bus8_lineC")
        for capacitor, node in ((bus7, gflNode), (bus8, middleNode)):
            capacitor.p["C"]["num"] = busCapacitance[node]
            capacitor.p["Gd"]["num"] = 0
            capacitor.p["w"]["num"] = 1

        gfl = GFLVSC(1, p["GFLSbase_VA"], "hybrid_cigre_gfl_bus7")
        for sourceName, targetName in (
            ("GFLLf", "L"), ("GFLKpCc", "Kpcc"), ("GFLKiCc", "Kicc"),
            ("GFLKpPll", "KpPll"), ("GFLKiPll", "KiPll"),
            ("GFLKpP", "kpP"), ("GFLKiP", "kiP"),
            ("GFLKpQ", "kpQ"), ("GFLKiQ", "kiQ"),
        ):
            gfl.p[targetName]["num"] = p[sourceName]

        vsg = VSGCC(1, p["VSGSbase_VA"], "hybrid_cigre_vsg_bus9")
        for name, value in (
            ("Lv", 0.3), ("Rv", 0.1), ("Lf", 0.07), ("Imax", 1.5),
            ("Kp", 0.05), ("Kp_cc", 20), ("Ki_cc", 5),
        ):
            vsg.p[name]["num"] = value
        vsg.p["C"]["num"] = (
            busCapacitance[vsgNode] * p["Sbase_VA"] / p["VSGSbase_VA"]
        )

        voltageDevices = [source, bus7, bus8, vsg]
        currentDevices = [
            ZeroCurrent(1, p["Sbase_VA"], "hybrid_cigre_infbus_zero"),
            gfl,
            ZeroCurrent(1, p["Sbase_VA"], "hybrid_cigre_bus8_zero"),
            ZeroCurrent(1, p["Sbase_VA"], "hybrid_cigre_bus9_zero"),
        ]
        p["clearTime_s"] = (
            np.inf if p["clearMode"] == "angle" else p["fixedClearStart_s"]
        )
        references = {
            str(source.uref[0]): lambda t: self.sourceVoltage(t, p),
            str(gfl.uref[0]): p["GFLPref"],
            str(gfl.uref[1]): p["GFLQref"],
            str(vsg.uref[0]): p["VSGPref"],
            str(vsg.uref[1]): p["VSGVref"],
            str(vsg.uref[2]): p["VSGwref"],
        }
        devices = {
            "Vdev": voltageDevices, "Idev": currentDevices,
            "source": source, "gfl": gfl, "vsg": vsg,
        }
        network = {
            "A": incidence, "R": branchR, "L": branchL,
            "busNames": busNames,
        }
        super().__init__(
            "HybridGFMGFLSystem", network, devices,
            {"Vbase": 1, "Sbase": p["Sbase_VA"], "frequency_Hz": p["frequency_Hz"]},
            references,
        )
        self.solverSettings["max_step"] = (
            p["maximumStep_tau"] / (2 * np.pi * p["frequency_Hz"])
        )
        self.parameters, self.parameterNames = p, list(p)
        self.busCapacitance = busCapacitance
        # These outer power-loop integrators evolve on the same slow manifold
        # as the selected PLL integrator. Treating them as fast forces P and Q
        # to recover instantaneously after LVRT/current limiting and can remove
        # the conditional equilibrium altogether.
        self.qssRequiredSlowStateNames = [
            str(gfl.x[4]), str(gfl.x[5]),
        ]
        self.eventName = "faultClearing"
        self.eventDirection = 1
        self.eventTime_s = p["clearTime_s"]
        if p["clearMode"] == "angle":
            self.eventStartTime_s = p["angleClearEligible_s"]
        self.eventStateIndex = self.stateNames.index(f"delta{vsg.index}")

    @staticmethod
    def buildReducedNetwork():
        """Build the four-node corridor from the original CIGRE branch data."""
        rows = {
            (fromNode, toNode): (R, L, C)
            for fromNode, toNode, R, L, C
            in CIGREMV14System.buildCigreData()["branchTable"]
        }
        upstreamPath = [("source", "1"), ("1", "2"), ("2", "3"), ("3", "8")]
        upstream = np.sum([rows[branch] for branch in upstreamPath], axis=0)
        reducedBranches = [upstream, rows[("7", "8")], rows[("8", "9")]]

        busNames = ["Infinite bus", "7", "8", "9"]
        connections = [("Infinite bus", "8"), ("7", "8"), ("8", "9")]
        incidence = np.zeros((len(busNames), len(connections)))
        busCapacitance = np.zeros(len(busNames))
        for branchIndex, ((fromNode, toNode), (_, _, capacitance)) in enumerate(
            zip(connections, reducedBranches)
        ):
            fromIndex, toIndex = busNames.index(fromNode), busNames.index(toNode)
            incidence[fromIndex, branchIndex] = 1
            incidence[toIndex, branchIndex] = -1
            busCapacitance[fromIndex] += capacitance / 2
            busCapacitance[toIndex] += capacitance / 2

        branchR = np.asarray([branch[0] for branch in reducedBranches])
        branchL = np.asarray([branch[1] for branch in reducedBranches])
        return incidence, branchR, branchL, busNames, busCapacitance

    def sourceVoltage(self, time_s, p):
        return CIGREMV14System.sourceVoltage(self, time_s, p)

    def eventHandler(self, time_s, state):
        return CIGREMV14System.eventHandler(self, time_s, state)

    def calculateSignals(self, time_s, state, networkSignals):
        return CIGREMV14System.calculateSignals(self, time_s, state, networkSignals)


# Keep the spelling from the original request importable as a compatibility alias.
HybridGFMGFLsystem = HybridGFMGFLSystem
