"""SMIB__GFL_P_F_LC: GFL low-voltage ride-through benchmark."""

import numpy as np

from ..components import Capacitor, GFL_P_F_L, Infbus, ZeroCurrent
from ..core import System


class SMIB__GFL_P_F_LC(System):
    """SMIB · GFL_P_F_LC: GFL with outer P/Q loops, PLL and FRT/LVRT current priority, with its terminal
    capacitor ``C`` (GFL base) at the PCC. Recurrent-FRT studies."""
    @staticmethod
    def defaultParameters(overrides=None):
        p = {
            "SCR": 5, "rho": 0.25, "Pref": 1, "Qref": 0.1,
            "C": 0.068,
            "K1": 0.3, "Id2": 1.0,
            "frequency_Hz": 50, "validationTime_s": 1,
            "faultStart_s": 0.3, "faultComplete_s": 0.301,
            "recoveryStart_s": 0.6, "recoveryComplete_s": 0.601,
            "faultVoltage": 0.5,
            "outputStep_s": 1e-4, "residualTolerance": 1e-3,
        }
        p.update(overrides or {})
        p["wBase"] = 2 * np.pi * p["frequency_Hz"]
        p["Lg"] = 1 / (p["SCR"] * np.sqrt(1 + p["rho"]**2))
        p["Rg"] = p["rho"] * p["Lg"]
        p["breakpoints_s"] = [p[name] for name in (
            "faultStart_s", "faultComplete_s", "recoveryStart_s", "recoveryComplete_s",
        )]
        p.setdefault("gridVoltage", lambda t: float(np.interp(
            t, [0, *p["breakpoints_s"], p["validationTime_s"]],
            [1, 1, p["faultVoltage"], p["faultVoltage"], 1, 1], right=1,
        )))
        return p

    def __init__(self, p):
        gfl = GFL_P_F_L(1, 8100, "1")
        for name, value in (("Vctrl", 0), ("KpPll", 0.2), ("KiPll", 0.2), ("Vref", 1), ("Kq", 1)):
            gfl.p[name]["num"] = value
        for name in ("K1", "Id2"):
            gfl.p[name]["num"] = p[name]
        capacitor = Capacitor(1, 8100, "2")
        capacitor.p["C"]["num"] = p["C"]
        zero, source = ZeroCurrent(1, 8100, "3"), Infbus(1, 8100, "4")
        refs = {str(gfl.uref[0]): p["Pref"], str(gfl.uref[1]): p["Qref"], str(source.uref[0]): p["gridVoltage"]}
        devices = {"Vdev": [capacitor, source], "Idev": [gfl, zero], "gfl": gfl, "capacitor": capacitor, "source": source}
        network = {"A": np.array([[1.0], [-1.0]]), "R": [p["Rg"]], "L": [p["Lg"]],
                   "busNames": ["PCC", "Infinite bus"]}
        super().__init__(type(self).__name__, network, devices,
            {"Vbase": 1, "Sbase": 8100, "frequency_Hz": 50}, refs,
        )
        self.solverSettings = {
            "method": "DOP853",
            "max_step": 5e-3 / (2 * np.pi * self.base["frequency_Hz"]),
            "rtol": 1e-3,
            "atol": 1e-5,
        }
        self.parameters, self.parameterNames = p, list(p)

    def calculateSignals(self, time_s, state, net):
        state = np.asarray(state)
        gfl = self.devices["gfl"]
        gflIdx = [self.stateNames.index(str(symbol)) for symbol in gfl.x]
        gridIdx = [self.stateNames.index(str(symbol)) for symbol in self.devices["source"].x]
        voltage, branch = net["busVoltage"], net["branchCurrent"]
        id, iq = state[:, gflIdx[0]], state[:, gflIdx[1]]
        # GFL_P_F_L has 8 states (with outer-loop PI), so look theta/xPLL up by name, not position.
        gflNames = [str(symbol) for symbol in gfl.x]
        thetaPLL = state[:, gflIdx[gflNames.index(f"theta{gfl.index}")]]
        xPLL = state[:, gflIdx[gflNames.index(f"xPLL{gfl.index}")]]
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
            "lineCurrentMagnitude": np.abs(branch),
            "nodeVoltage": nodeVoltage,
            "busVoltageMagnitude": np.abs(voltage),
            "busVoltageAngleDeg": np.rad2deg(np.angle(voltage)),
            "busNames": self.busNames,
            "deviceCurrent": deviceCurrent,
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