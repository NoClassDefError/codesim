"""GFL low-voltage ride-through benchmark."""

import numpy as np

from ..components import Capacitor, GFLVSC, Infbus, ZeroCurrent
from ..core import System


class GFLLVRTSystem(System):
    def __init__(self, p):
        gfl = GFLVSC(1, 8100, "1")
        for name, value in (("Vctrl", 0), ("KpPll", 0.2), ("KiPll", 0.2), ("Vref", 1), ("Kq", 1)):
            gfl.p[name]["num"] = value
        capacitor = Capacitor(1, 8100, "2")
        capacitor.p["Gd"]["num"], capacitor.p["C"]["num"] = 0.2, 5e-4
        zero, source = ZeroCurrent(1, 8100, "3"), Infbus(1, 8100, "4")
        refs = {str(gfl.uref[0]): p["Pref"], str(gfl.uref[1]): p["Qref"], str(source.uref[0]): p["gridVoltage"]}
        devices = {"Vdev": [capacitor, source], "Idev": [gfl, zero], "gfl": gfl, "capacitor": capacitor, "source": source}
        network = {"A": np.array([[1.0], [-1.0]]), "R": [p["Rg"]], "L": [p["Lg"]],
                   "busNames": ["PCC", "Infinite bus"]}
        super().__init__("GFLLVRTSystem", network, devices, {"Vbase": 1, "Sbase": 8100, "frequency_Hz": 50}, refs)
        self.parameters, self.parameterNames = p, list(p)

    def calculateSignals(self, time_s, state, net):
        state = np.asarray(state)
        gfl = self.devices["gfl"]
        gflIdx = [self.stateNames.index(str(symbol)) for symbol in gfl.x]
        gridIdx = [self.stateNames.index(str(symbol)) for symbol in self.devices["source"].x]
        voltage, branch = net["busVoltage"], net["branchCurrent"]
        id, iq = state[:, gflIdx[0]], state[:, gflIdx[1]]
        thetaPLL, xPLL = state[:, gflIdx[6]], state[:, gflIdx[7]]
        pccVoltage, gridVoltage = np.abs(voltage[:, 0]), np.abs(voltage[:, 1])
        vd = voltage[:, 0].real * np.cos(thetaPLL) + voltage[:, 0].imag * np.sin(thetaPLL)
        vq = -voltage[:, 0].real * np.sin(thetaPLL) + voltage[:, 0].imag * np.cos(thetaPLL)
        activePower, reactivePower = vd * id + vq * iq, vq * id - vd * iq
        lvrtMode = 0.5 * (1 + np.sign(gfl.p["Vth"]["num"] - pccVoltage))
        droopActive = gfl.p["Vctrl"]["num"] * (1 - lvrtMode)
        qDroop = droopActive * (gfl.p["Vref"]["num"] - pccVoltage) / gfl.p["Kq"]["num"]
        qCommand = net["referenceTrace"][0, 1] + qDroop
        iqReferenceSchedule = -qCommand / np.maximum(pccVoltage, 1e-6)
        iqReferenceSupport = -gfl.p["K1"]["num"] * (gfl.p["Vth"]["num"] - pccVoltage)
        iqReferenceFRT = np.clip(iqReferenceSupport, -gfl.p["Imax"]["num"], gfl.p["Imax"]["num"])
        idReferenceFRT = np.minimum(gfl.p["Id2"]["num"], np.sqrt(np.maximum(0, gfl.p["Imax"]["num"]**2 - iqReferenceFRT**2)))
        branchActivePower = voltage[:, 0].real * branch[:, 0].real + voltage[:, 0].imag * branch[:, 0].imag
        branchReactivePower = voltage[:, 0].imag * branch[:, 0].real - voltage[:, 0].real * branch[:, 0].imag
        pllFrequencyRaw = gfl.p["w0"]["num"] + gfl.p["KpPll"]["num"] * vq + gfl.p["KiPll"]["num"] * xPLL
        nodeVoltage = np.empty((len(state), 2 * voltage.shape[1]))
        nodeVoltage[:, 0::2], nodeVoltage[:, 1::2] = voltage.real, voltage.imag
        deviceCurrentValue = net["currentDeviceCurrent"]
        deviceCurrent = np.empty((len(state), 2 * deviceCurrentValue.shape[1]))
        deviceCurrent[:, 0::2], deviceCurrent[:, 1::2] = deviceCurrentValue.real, deviceCurrentValue.imag
        return {
            "branchCurrent": np.column_stack((branch[:, 0].real, branch[:, 0].imag)),
            "nodeVoltage": nodeVoltage, "deviceCurrent": deviceCurrent,
            "referenceTrace": net["referenceTrace"], "pccVoltage": pccVoltage, "gridVoltage": gridVoltage,
            "id": id, "iq": iq, "vd": vd, "vq": vq, "thetaPLL": thetaPLL, "xPLL": xPLL,
            "thetaGrid": state[:, gridIdx[0]], "activePower": activePower, "reactivePower": reactivePower,
            "lvrtMode": lvrtMode, "droopActive": droopActive, "qDroop": qDroop, "qCommand": qCommand,
            "iqReferenceSchedule": iqReferenceSchedule, "iqReferenceSupport": iqReferenceSupport,
            "iqReferenceFRT": iqReferenceFRT, "idReferenceFRT": idReferenceFRT,
            "gflCurrentMagnitude": np.hypot(id, iq), "branchCurrentMagnitude": np.abs(branch[:, 0]),
            "branchActivePower": branchActivePower, "branchReactivePower": branchReactivePower,
            "pllFrequencyRaw": pllFrequencyRaw,
            "pllFrequency": np.clip(pllFrequencyRaw, gfl.p["wPllMin"]["num"], gfl.p["wPllMax"]["num"]),
            "pllAngleError": np.rad2deg(np.unwrap(thetaPLL - state[:, gridIdx[0]])),
        }
