"""Balanced IEEE 13-node feeder, optionally including converters."""

import numpy as np

from ..components import Capacitor, GFLVSC, Infbus, PQLoad, VSGCL, ZIP, ZeroCurrent
from ..core import System


class IEEE13System(System):
    def __init__(self, p, *, EnableConverters=False):
        busTable, branchTable, loadTable, data = self.networkData()
        incidence, branchLpu, branchRpu = self.branches(busTable, branchTable, data, p)
        voltageDevices, currentDevices, referenceMap = [None] * len(busTable), [None] * len(busTable), {}
        for busIndex, busName in enumerate(busTable):
            deviceIndex = f"ieee13_{busName}"
            hasSource = -1
            if busName == "650":
                source = Infbus(1, p["Sbase_VA"], deviceIndex)
                voltageDevices[busIndex] = source
                referenceMap[str(source.uref[0])] = p["infbusVoltage"]
                hasSource = 0
            elif EnableConverters and busName == "680":
                source = VSGCL(1, p["Sbase_Dev"], deviceIndex)
                voltageDevices[busIndex] = source
                for symbol, value in zip(source.uref, (p["GFMPref"], p["GFMVref"], p["GFMwref"])):
                    referenceMap[str(symbol)] = value
                hasSource = 0
            elif EnableConverters and busName in ("645", "671"):
                source = GFLVSC(1, p["Sbase_Dev"], f"{deviceIndex}_gfl")
                source.p["KpPll"]["num"], source.p["KiPll"]["num"] = p["gflKpPll"], p["gflKiPll"]
                if busName == "671":
                    source.p["Vth"]["num"], source.p["K1"]["num"] = p["gfl671Vth"], p["gfl671K1"]
                    source.p["Vctrl"]["num"], source.p["Vref"]["num"], source.p["Kq"]["num"] = 0, 1, 0.3
                deviceNumber = ("645", "671").index(busName)
                referenceMap[str(source.uref[0])] = p["gflPref"][deviceNumber]
                referenceMap[str(source.uref[1])] = p["gflQref"][deviceNumber]
                currentDevices[busIndex], hasSource = source, 1
            rows = [row for row in loadTable if row[0] == busName]
            hasLoad = bool(rows)
            loadPpu = sum(row[1] for row in rows) * 1e3 / p["Sbase_VA"]
            loadQpu = sum(row[2] - row[3] for row in rows) * 1e3 / p["Sbase_VA"]
            if EnableConverters:
                if hasSource == 0 and hasLoad:
                    load = PQLoad(1, p["Sbase_VA"], f"{deviceIndex}_load")
                    referenceMap[str(load.uref[0])], referenceMap[str(load.uref[1])] = loadPpu, loadQpu
                    currentDevices[busIndex] = load
                elif hasSource == 1 and hasLoad:
                    load = ZIP(1, p["Sbase_VA"], f"{deviceIndex}_load")
                    load.p["aZ"]["num"] = loadPpu + (p["bus645Gd"] if busName == "645" else 0)
                    load.p["aP"]["num"] = 0
                    if busName == "671":
                        load.p["aZ"]["num"] = p["bus671ActiveZFraction"] * loadPpu
                        load.p["aP"]["num"] = (1 - p["bus671ActiveZFraction"]) * loadPpu
                    load.p["aI"]["num"] = 0
                    load.p["bZ"]["num"], load.p["bI"]["num"], load.p["bP"]["num"] = -loadQpu, 0, 0
                    voltageDevices[busIndex] = load
                elif hasSource == 0:
                    currentDevices[busIndex] = ZeroCurrent(1, p["Sbase_VA"], f"{deviceIndex}_zero")
                elif hasSource == 1:
                    capacitor = Capacitor(1, p["Sbase_VA"], f"{deviceIndex}_capacitor")
                    capacitor.p["Gd"]["num"], capacitor.p["C"]["num"] = 0.2, 5e-4
                    voltageDevices[busIndex] = capacitor
                elif hasLoad:
                    load = ZIP(1, p["Sbase_VA"], f"{deviceIndex}_load")
                    load.p["aZ"]["num"], load.p["aI"]["num"], load.p["aP"]["num"] = loadPpu, 0, 0
                    load.p["bZ"]["num"], load.p["bI"]["num"], load.p["bP"]["num"] = -loadQpu, 0, 0
                    voltageDevices[busIndex] = load
                    currentDevices[busIndex] = ZeroCurrent(1, p["Sbase_VA"], f"{deviceIndex}_zero")
            else:
                if hasSource == 0 and hasLoad:
                    load = PQLoad(1, p["Sbase_VA"], f"{deviceIndex}_load")
                    referenceMap[str(load.uref[0])], referenceMap[str(load.uref[1])] = -loadPpu, -loadQpu
                    currentDevices[busIndex] = load
                elif hasSource == 0:
                    currentDevices[busIndex] = ZeroCurrent(1, p["Sbase_VA"], f"{deviceIndex}_zero")
                elif hasLoad:
                    load = ZIP(1, p["Sbase_VA"], f"{deviceIndex}_load")
                    load.p["aZ"]["num"], load.p["aI"]["num"], load.p["aP"]["num"] = loadPpu, 0, 0
                    load.p["bZ"]["num"], load.p["bI"]["num"], load.p["bP"]["num"] = loadQpu, 0, 0
                    voltageDevices[busIndex] = load
                    currentDevices[busIndex] = ZeroCurrent(1, p["Sbase_VA"], f"{deviceIndex}_zero")
        devices = {"Vdev": voltageDevices, "Idev": currentDevices}
        network = {"A": incidence, "R": branchRpu, "L": branchLpu, "busNames": busTable}
        name = "IEEE13System_converters" if EnableConverters else "IEEE13System_passive"
        super().__init__(name, network, devices,
                         {"Vbase": 1, "Sbase": p["Sbase_VA"], "frequency_Hz": p["wBase"] / (2 * np.pi)}, referenceMap)
        self.parameters, self.parameterNames = p, list(p)
        self.enableConverters = EnableConverters
        self.data = {"busTable": busTable, "branchTable": branchTable, "loadTable": loadTable, **data}

    @staticmethod
    def networkData():
        busTable = ["650", "632", "633", "634", "645", "646", "671", "680", "684", "611", "652", "692", "675"]
        branchTable = list(zip(
            ["632", "632", "633", "645", "650", "684", "632", "671", "671", "671", "684", "692"],
            ["645", "633", "634", "646", "632", "652", "671", "684", "680", "692", "611", "675"],
            [500, 500, 0, 300, 2000, 800, 2000, 300, 1000, 0, 300, 500],
            ["601", "601", "XFM-1", "601", "601", "606", "601", "601", "601", "Switch", "601", "606"],
        ))
        loadTable = list(zip(
            ["632", "634", "645", "646", "652", "671", "675", "692", "611"],
            [100, 400, 170, 230, 128, 1255, 843, 170, 170],
            [58, 290, 125, 132, 86, 718, 462, 151, 80],
            [0, 0, 0, 0, 0, 0, 600, 0, 100],
        ))
        data = {
            "R601": np.array([[0.3465, 0.1560, 0.1580], [0.1560, 0.3375, 0.1535], [0.1580, 0.1535, 0.3414]]),
            "X601": np.array([[1.0179, 0.5017, 0.4236], [0.5017, 1.0478, 0.3849], [0.4236, 0.3849, 1.0348]]),
            "R606": np.array([[0.7982, 0.3192, 0.2849], [0.3192, 0.7891, 0.3192], [0.2849, 0.3192, 0.7982]]),
            "X606": np.array([[0.4463, 0.0328, -0.0143], [0.0328, 0.4041, 0.0328], [-0.0143, 0.0328, 0.4463]]),
        }
        return busTable, branchTable, loadTable, data

    @staticmethod
    def branches(busTable, branchTable, data, p):
        A = np.zeros((len(busTable), len(branchTable)))
        for column, row in enumerate(branchTable):
            A[busTable.index(row[0]), column], A[busTable.index(row[1]), column] = 1, -1
        sequence = {}
        for code in ("601", "606"):
            Rabc, Xabc = data[f"R{code}"], data[f"X{code}"]
            sequence[code] = ((np.trace(Rabc) / 3 - (Rabc.sum() - np.trace(Rabc)) / 6),
                              (np.trace(Xabc) / 3 - (Xabc.sum() - np.trace(Xabc)) / 6))
        Rpu, Lpu = np.zeros(len(branchTable)), np.zeros(len(branchTable))
        for k, (fromBus, toBus, lengthFt, code) in enumerate(branchTable):
            if code in sequence:
                Rpu[k], Lpu[k] = np.asarray(sequence[code]) * (lengthFt / 5280) / p["Zbase_ohm"]
            elif code == "XFM-1":
                Rpu[k], Lpu[k] = 0.011 * p["Sbase_VA"] / 500e3, 0.020 * p["Sbase_VA"] / 500e3
            else:
                Rpu[k], Lpu[k] = 1e-5, 1e-4
            if "bus671LineRScale" in p and "671" in (fromBus, toBus):
                Rpu[k] *= p["bus671LineRScale"]
        return A, Lpu, Rpu

    def calculateSignals(self, time_s, state, net):
        if not self.enableConverters:
            indices = [self.busNames.index(name) for name in ("650", "632", "645", "671", "675")]
            signals = self.busSignals(net, indices, indices[0])
            signals["activePowerMW"] = signals["activePower"] * self.base["Sbase"] / 1e6
            signals["reactivePowerMvar"] = signals["reactivePower"] * self.base["Sbase"] / 1e6
            return signals
        state = np.asarray(state)
        originalNames = self.data["busTable"]
        vsg = self.devices["Vdev"][originalNames.index("680")]
        idxVsg = [self.stateNames.index(str(symbol)) for symbol in vsg.x]
        gflDevices = [self.devices["Idev"][originalNames.index(name)] for name in self.parameters["gflBusNames"]]
        idxGfl = [[self.stateNames.index(str(symbol)) for symbol in device.x] for device in gflDevices]
        activePower = np.zeros((len(state), 3)); reactivePower = np.zeros_like(activePower)
        currentD = np.zeros_like(activePower); currentQ = np.zeros_like(activePower); converterMode = np.zeros_like(activePower)
        vo, iLv = state[:, idxVsg[:2]], state[:, idxVsg[2:4]]
        activePower[:, 0] = np.sum(vo * iLv, axis=1)
        reactivePower[:, 0] = vo[:, 1] * iLv[:, 0] - vo[:, 0] * iLv[:, 1]
        currentD[:, 0], currentQ[:, 0] = iLv[:, 0], iLv[:, 1]
        vrefColumn = self.referenceNames.index(str(vsg.uref[1])); wrefColumn = self.referenceNames.index(str(vsg.uref[2]))
        delta = state[:, idxVsg[4]]
        J = np.array([[0.0, -1.0], [1.0, 0.0]])
        for sample in range(len(state)):
            sourceVoltage = net["referenceTrace"][sample, vrefColumn] * np.array([np.cos(delta[sample]), np.sin(delta[sample])])
            impedance = vsg.p["Rf"]["num"] * np.eye(2) + net["referenceTrace"][sample, wrefColumn] * vsg.p["Lf"]["num"] * J
            converterMode[sample, 0] = np.linalg.norm(np.linalg.solve(impedance, sourceVoltage - vo[sample])) > vsg.p["Imax"]["num"]
        for deviceIndex, (device, indices, busName) in enumerate(zip(gflDevices, idxGfl, self.parameters["gflBusNames"]), 1):
            id, iq, theta = state[:, indices[0]], state[:, indices[1]], state[:, indices[6]]
            voltage = net["busVoltage"][:, self.busNames.index(busName)]
            vd = voltage.real * np.cos(theta) + voltage.imag * np.sin(theta)
            vq = -voltage.real * np.sin(theta) + voltage.imag * np.cos(theta)
            activePower[:, deviceIndex], reactivePower[:, deviceIndex] = vd * id + vq * iq, vq * id - vd * iq
            currentD[:, deviceIndex], currentQ[:, deviceIndex] = id, iq
            converterMode[:, deviceIndex] = np.abs(voltage) < device.p["Vth"]["num"]
        angle = (np.angle(net["busVoltage"]) - np.angle(net["busVoltage"][:, [0]]) + np.pi) % (2 * np.pi) - np.pi
        angle[:, self.busNames.index("680")] = (delta + np.pi) % (2 * np.pi) - np.pi
        return {"busNames": self.busNames, "busVoltageMagnitude": np.abs(net["busVoltage"]),
                "busVoltageAngle": angle, "deviceNames": ["VSG 680", "GFL 645", "GFL 671"],
                "activePower": activePower, "reactivePower": reactivePower,
                "currentD": currentD, "currentQ": currentQ, "converterMode": converterMode}
