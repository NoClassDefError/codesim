"""CIGRE4__GFM_A_C_LC__GFL_C_F_L: four-node reduction of the CIGRE MV feeder."""

import numpy as np

from ..components import Capacitor, GFL_C_F_L, GFM_A_C_LC, Infbus, ZeroCurrent
from ..core import System
from .cigre14 import _CIGRE14, buildGFL


class _CIGRE4GFMAdmittance(System):
    """Retain CIGRE buses 7, 8, 9 and replace the upstream feeder by an infinite bus.

    The original source--1--2--3--8 corridor is represented by one series-equivalent
    branch.  The original 7--8 and 8--9 branches are retained unchanged.  Loads and
    laterals outside this four-node corridor are intentionally omitted.
    """

    @staticmethod
    def defaultParameters(overrides=None):
        """CIGRE defaults plus ``gridImpedanceScale`` (multiplies the R and L of the
        upstream source--8 equivalent; >1 weakens the grid) and ``gridRX``
        (R/X of that equivalent at constant |Z|; ``None`` keeps the CIGRE 0.53)."""
        overrides = dict(overrides or {})
        overrides.setdefault("gridImpedanceScale", 1.0)
        overrides.setdefault("gridRX", None)
        return _CIGRE14.defaultParameters(overrides)

    def __init__(self, p):
        incidence, branchR, branchL, busNames, busCapacitance = self.buildReducedNetwork(
            p["gridImpedanceScale"], p["gridRX"]
        )
        _, gflNode, middleNode, vsgNode = range(4)

        source = Infbus(1, p["Sbase_VA"], "hybrid_cigre_infbus")
        source.p["kA"]["num"] = 100

        bus7 = Capacitor(1, p["Sbase_VA"], "hybrid_cigre_bus7_lineC")
        bus8 = Capacitor(1, p["Sbase_VA"], "hybrid_cigre_bus8_lineC")
        for capacitor, node in ((bus7, gflNode), (bus8, middleNode)):
            capacitor.p["C"]["num"] = busCapacitance[node]
            capacitor.p["Gd"]["num"] = 0
            capacitor.p["w"]["num"] = 1

        gfl, gflReferences = buildGFL(p, "hybrid_cigre_gfl_bus7", self.GFL)

        vsg = GFM_A_C_LC(1, p["VSGSbase_VA"], "hybrid_cigre_vsg_bus9")
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
        clearingTime_s = np.inf if p["clearMode"] == "angle" else p["recoveryStart_s"]
        references = {
            str(source.uref[0]): lambda t: self.sourceVoltage(t, p),
            str(gfl.uref[0]): gflReferences[0],
            str(gfl.uref[1]): gflReferences[1],
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
            type(self).__name__, network, devices,
            {"Vbase": 1, "Sbase": p["Sbase_VA"], "frequency_Hz": p["frequency_Hz"]},
            references,
        )
        self.solverSettings["max_step"] = (
            p["maximumStep_tau"] / (2 * np.pi * p["frequency_Hz"])
        )
        self.parameters, self.parameterNames = p, list(p)
        self.busCapacitance = busCapacitance
        self.qssRequiredSlowStateNames = []
        self.eventName = "faultClearing"
        self.eventDirection = 1
        self.eventTime_s = clearingTime_s
        if p["clearMode"] == "angle":
            self.eventStartTime_s = p["angleClearEligible_s"]
        self.eventStateIndex = self.stateNames.index(f"delta{vsg.index}")

    @staticmethod
    def buildReducedNetwork(gridImpedanceScale=1.0, gridRX=None):
        """Build the four-node corridor from the original CIGRE branch data.

        ``gridImpedanceScale`` multiplies R and L of the upstream equivalent (its
        line capacitance is kept). ``gridRX``, if given, then sets the R/X of
        that equivalent while keeping its |Z| (so the short-circuit level)."""
        rows = {
            (fromNode, toNode): (R, L, C)
            for fromNode, toNode, R, L, C
            in _CIGRE14.buildCigreData()["branchTable"]
        }
        upstreamPath = [("source", "1"), ("1", "2"), ("2", "3"), ("3", "8")]
        upstream = np.sum([rows[branch] for branch in upstreamPath], axis=0)
        upstream = upstream * np.array([gridImpedanceScale, gridImpedanceScale, 1.0])
        if gridRX is not None:
            magnitude = np.hypot(upstream[0], upstream[1])
            upstream[1] = magnitude / np.hypot(gridRX, 1.0)
            upstream[0] = gridRX * upstream[1]
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
        return _CIGRE14.sourceVoltage(self, time_s, p)

    def eventHandler(self, time_s, state):
        return _CIGRE14.eventHandler(self, time_s, state)

    def calculateSignals(self, time_s, state, networkSignals):
        return _CIGRE14.calculateSignals(self, time_s, state, networkSignals)


class CIGRE4__GFM_A_C_LC__GFL_C_F_L(_CIGRE4GFMAdmittance):
    """CIGRE4 · GFM_A_C_LC at bus 9 (virtual admittance + current PI, circular current-reference limit; its
    capacitor is the bus-9 line capacitance, no converter filter capacitor) + GFL_C_F_L at bus 7 (current
    references, FRT current priority; bus-7 line capacitance only). The p261030 tier-A benchmark."""
    GFL = GFL_C_F_L

