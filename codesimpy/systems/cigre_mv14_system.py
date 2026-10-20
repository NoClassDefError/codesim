"""CIGRE MV14 feeder with a grid-forming converter at bus 9."""

from time import perf_counter

import numpy as np

from ..components import Capacitor, Infbus, VSGCC, ZeroCurrent
from ..core import System


class CIGREMV14System(System):
    def __init__(self, p):
        data = self.buildCigreData()
        incidence, branchR, branchL, nodeNames, busCapacitance = self.assembleNetwork(data)
        voltageDevices, currentDevices, referenceMap = [None] * len(nodeNames), [None] * len(nodeNames), {}
        sourceNode, groundNode, vsgNode = nodeNames.index("source"), nodeNames.index("ground"), nodeNames.index("9")
        source = Infbus(1, p["Sbase_VA"], "cigre_source"); source.p["kA"]["num"] = 100
        ground = Infbus(1, p["Sbase_VA"], "cigre_ground"); ground.p["kA"]["num"] = 100
        voltageDevices[sourceNode], voltageDevices[groundNode] = source, ground
        referenceMap[str(source.uref[0])], referenceMap[str(ground.uref[0])] = 1.0, 0.0
        vsg = None
        for nodeIndex, nodeName in enumerate(nodeNames):
            deviceIndex = f"cigre_{nodeName}"
            if nodeIndex not in (sourceNode, groundNode, vsgNode):
                capacitor = Capacitor(1, p["Sbase_VA"], f"{deviceIndex}_lineC")
                capacitor.p["C"]["num"], capacitor.p["Gd"]["num"], capacitor.p["w"]["num"] = busCapacitance[nodeIndex], 0, 1
                voltageDevices[nodeIndex] = capacitor
            if nodeIndex == vsgNode:
                vsg = VSGCC(1, p["VSGSbase_VA"], "cigre_vsg_bus9")
                for name, value in (("Lv", 0.3), ("Rv", 0.1), ("Lf", 0.07), ("Imax", 1.5),
                                    ("Kp", 0.05), ("Kp_cc", 20), ("Ki_cc", 5)):
                    vsg.p[name]["num"] = value
                vsg.p["C"]["num"] = busCapacitance[nodeIndex] * p["Sbase_VA"] / p["VSGSbase_VA"]
                voltageDevices[nodeIndex] = vsg
                for symbol, value in zip(vsg.uref, (p["VSGPref"], p["VSGVref"], p["VSGwref"])):
                    referenceMap[str(symbol)] = value
            currentDevices[nodeIndex] = ZeroCurrent(1, p["Sbase_VA"], f"{deviceIndex}_zero")
        devices = {"Vdev": voltageDevices, "Idev": currentDevices, "source": source, "vsg": vsg}
        network = {"A": incidence, "R": branchR, "L": branchL, "busNames": nodeNames}
        super().__init__("CIGREMV14System", network, devices,
                         {"Vbase": 1, "Sbase": p["Sbase_VA"], "frequency_Hz": p["frequency_Hz"]}, referenceMap)
        self.parameters, self.parameterNames = p, list(p)
        self.data, self.busCapacitance = data, busCapacitance

    @staticmethod
    def buildCigreData():
        return {
            "branchTable": list(zip(
                ["source", "1", "2", "3", "3", "4", "5", "7", "8", "9", "10"],
                ["1", "2", "3", "4", "8", "5", "6", "8", "9", "10", "11"],
                [0.00049751859510499465 + 0.001, 0.08830125, 0.13840125, 0.019100625, 0.04070625, 0.017535, 0.04822125, 0.052291875, 0.01002, 0.024110625, 0.010333125],
                [0.0049751859510499463 + 0.12, 0.126195, 0.197795, 0.0272975, 0.058175, 0.02506, 0.068915, 0.0747325, 0.01432, 0.0344575, 0.0147675],
                [0, 0.00214288416, 0.00335870496, 0.00046353168, 0.0009878544, 0.00042553728, 0.00117022752, 0.00126901296, 0.00024316416, 0.00058511376, 0.00025076304],
            )),
            "loadTable": list(zip(
                ["1", "3", "4", "5", "6", "7", "8", "9", "10", "11"],
                [1.1948643729138855, 42.468763552332916, 54.49438202247191, 32.333333333333329, 42.920353982300881, 236.11111111111111, 40.082644628099168, 31.481481481481477, 42.289242026495018, 71.323529411764696],
                [0.27928568249809682, 17.681828918901711, 13.657579529374406, 8.1034971874288129, 10.75685467357807, 146.32852434517696, 10.0456576703663, 19.510469912690258, 12.552426517584911, 17.875361442857677],
            )),
        }

    @staticmethod
    def assembleNetwork(data):
        nodeNames = ["source"] + [str(index) for index in range(1, 12)] + ["ground"]
        connections = [(row[0], row[1]) for row in data["branchTable"]] + [(row[0], "ground") for row in data["loadTable"]]
        A = np.zeros((len(nodeNames), len(connections)))
        for branchIndex, (fromNode, toNode) in enumerate(connections):
            A[nodeNames.index(fromNode), branchIndex], A[nodeNames.index(toNode), branchIndex] = 1, -1
        R = np.array([row[2] for row in data["branchTable"]] + [row[1] for row in data["loadTable"]])
        L = np.array([row[3] for row in data["branchTable"]] + [row[2] for row in data["loadTable"]])
        busCapacitance = np.zeros(len(nodeNames))
        for fromNode, toNode, Rline, Lline, Cline in data["branchTable"]:
            busCapacitance[nodeNames.index(fromNode)] += Cline / 2
            busCapacitance[nodeNames.index(toNode)] += Cline / 2
        return A, R, L, nodeNames, busCapacitance

    @staticmethod
    def sourceVoltage(time_s, p, clearMode, clearingTime_s):
        time_s = np.asarray(time_s)
        if clearMode == "angle":
            faulted = time_s >= p["faultStartAngle_s"]
            if np.isfinite(clearingTime_s):
                faulted &= time_s < clearingTime_s
            voltage = np.ones(time_s.shape)
            voltage[faulted] = p["angleFaultVoltage_pu"]
            return float(voltage) if voltage.ndim == 0 else voltage
        times = [0, p["fixedFaultStart_s"], p["fixedFaultComplete_s"], p["fixedClearStart_s"],
                 p["fixedClearComplete_s"], p["validationTime_s"]]
        values = [1, 1, p["fixedFaultVoltage_pu"], p["fixedFaultVoltage_pu"], 1, 1]
        return np.interp(time_s, times, values, right=1)

    @staticmethod
    def eventTimes(p, clearMode, clearingTime_s):
        if clearMode == "angle":
            return [p["faultStartAngle_s"]] + ([clearingTime_s] if np.isfinite(clearingTime_s) else [])
        return [p["fixedFaultStart_s"], p["fixedFaultComplete_s"], p["fixedClearStart_s"], p["fixedClearComplete_s"]]

    @staticmethod
    def makeOutputTime(endTime_s, step_s, requiredTimes_s):
        result = np.arange(0, endTime_s + step_s / 2, step_s)
        result = np.r_[result[result <= endTime_s], endTime_s]
        required = np.asarray(requiredTimes_s, dtype=float).reshape(-1)
        required = required[np.isfinite(required) & (required >= 0) & (required <= endTime_s)]
        return np.unique(np.r_[result, required])

    def simulateFault(self, mode, x0, *, saveSnapshot=True):
        p, refs = self.parameters, self.getReference()
        sourceIndex = self.referenceNames.index(str(self.devices["source"].uref[0]))
        deltaIndex = self.stateNames.index(f"delta{self.devices['vsg'].index}")
        self.rlGrid.refreshParameters()
        started, clearingTime_s = perf_counter(), p["fixedClearStart_s"]
        if mode == "angle":
            streaming = self.outputJsonFactory.streaming
            self.outputJsonFactory.streaming = False
            detectionRefs = list(refs)
            detectionRefs[sourceIndex] = lambda t: float(t < p["faultStartAngle_s"]) + p["angleFaultVoltage_pu"] * float(t >= p["faultStartAngle_s"])
            td = self.makeOutputTime(p["validationTime_s"], min(p["outputStep_s"], 2e-5),
                                     [p["faultStartAngle_s"], p["angleClearEligible_s"]])
            detected, td, _ = self.integrate(td, x0, detectionRefs,
                                             p["maximumStep_tau"] / (2 * np.pi * self.base["frequency_Hz"]),
                                             [p["faultStartAngle_s"]], None)
            self.outputJsonFactory.streaming = streaming
            delta = (detected[:, deltaIndex] + np.pi) % (2 * np.pi) - np.pi
            eligible = np.flatnonzero((td >= p["angleClearEligible_s"]) & (delta > p["angleClearLower_rad"]) & (delta < p["angleClearUpper_rad"]))
            clearingTime_s = td[eligible[0]] if eligible.size else np.inf
        refs[sourceIndex] = lambda t: self.sourceVoltage(t, p, mode, clearingTime_s)
        breaks = self.eventTimes(p, mode, clearingTime_s)
        time_s = self.makeOutputTime(p["validationTime_s"], p["outputStep_s"], breaks)
        state, time_s, events = self.integrate(time_s, x0, refs,
                                               p["maximumStep_tau"] / (2 * np.pi * self.base["frequency_Hz"]),
                                               breaks, None)
        net = self.calculateNetworkSignals(time_s, state, refs)
        result = {"time_s": time_s, "state": state, "stateNames": self.stateNames,
                  "signals": self.calculateSignals(time_s, state, net), "referenceNames": self.referenceNames,
                  "referenceTrace": net["referenceTrace"], "initialization": None, "events": events,
                  "parameters": self.parameters, "simulationTime_s": perf_counter() - started,
                  "clearingTime_s": clearingTime_s}
        if saveSnapshot:
            _, result["frontendDescriptor"] = self.outputJsonFactory.saveSnapshot(result)
        return result

    def calculateSignals(self, time_s, state, net):
        state, time_s = np.asarray(state), np.asarray(time_s)
        idx = [self.stateNames.index(str(symbol)) for symbol in self.devices["vsg"].x]
        signals = self.busSignals(net, np.arange(self.rlGrid.n), 0)
        signals["irefDQ"] = state[:, idx[2:4]]
        signals["filterCurrentDQ"] = state[:, idx[4:6]]
        signals["filterCurrentMagnitude"] = np.linalg.norm(signals["filterCurrentDQ"], axis=1)
        delta = state[:, idx[8]]
        signals["delta"] = (delta + np.pi) % (2 * np.pi) - np.pi
        signals["dot_delta"] = np.gradient(np.unwrap(delta), time_s) if len(time_s) > 1 else np.zeros_like(delta)
        return signals
