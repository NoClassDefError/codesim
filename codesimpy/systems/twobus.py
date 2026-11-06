"""TwoBus__GFM_A_C_LC__GFL_P_F_L, TwoBus__GFM_A_C_LC: GFM (and GFL) at one PCC behind a grid impedance."""

import numpy as np

from ..components import GFL_P_F_L, GFM_A_C_LC, Infbus, ZeroCurrent
from ..core import System


class _TwoBus(System):
    WITH_GFL = True
    nonEditableParameterNames = frozenset({"branchL", "branchR"})

    @staticmethod
    def defaultParameters(overrides=None):
        p = {
            "Vbase": 1, "Sbase": 25e6, "vsgSbase": 5e6, "gflSbase": 1.5e6,
            "frequency_Hz": 50, "gflPref": 1, "gflQref": 0, "gflVref": 1,
            "vsgPref": 1, "vsgVref": 1.10, "vsgImax": 1.5, "wref": 1,
            "vsgRv": 0.1, "vsgLv": 0.3, "vsgLf": 0.07, "vsgKpApc": 0.05,
            "vsgKpCc": 20, "vsgKiCc": 5, "gflLf": 0.07, "gflKpCc": 0.3,
            "gflKiCc": 1, "gflKpPll": 0.2, "gflKiPll": 0.02,
            "gflKpP": 0.02, "gflKiP": 0.02, "gflKpQ": 0.02,
            "gflKiQ": 0.02, "gflKq": 0.05, "validationTime_s": 1,
            "faultStart_s": 0.10, "faultComplete_s": 0.101,
            "recoveryStart_s": 0.5, "recoveryComplete_s": 0.501,
            "faultVoltage": 0.25, "SCR": 1.69, "rho": 1.0,
            "outputStep_s": 2e-3, "residualTolerance": 1e-4,
        }
        p.update(overrides or {})
        p["wBase"] = 2 * np.pi * p["frequency_Hz"]
        p["Lg"] = 1 / (p["SCR"] * np.sqrt(1 + p["rho"]**2))
        p["Rg"] = p["rho"] * p["Lg"]
        p["branchL"], p["branchR"] = p["Lg"], p["Rg"]
        p["breakpoints_s"] = [p[name] for name in (
            "faultStart_s", "faultComplete_s", "recoveryStart_s", "recoveryComplete_s",
        )]
        p.setdefault("gridVoltage", lambda t: float(np.interp(
            t, [0, *p["breakpoints_s"], p["validationTime_s"]],
            [1, 1, p["faultVoltage"], p["faultVoltage"], 1, 1], right=1,
        )))
        return p

    def __init__(self, p):
        source = Infbus(p["Vbase"], p["Sbase"], "hybrid_grid")
        vsg = GFM_A_C_LC(p["Vbase"], p["vsgSbase"], "hybrid_vsg")
        vsg.p["Imax"]["num"] = p["vsgImax"]
        for sourceName, targetName in (("vsgRv", "Rv"), ("vsgLv", "Lv"), ("vsgLf", "Lf"),
                                       ("vsgKpApc", "Kp"), ("vsgKpCc", "Kp_cc"), ("vsgKiCc", "Ki_cc")):
            vsg.p[targetName]["num"] = p[sourceName]
        zero = ZeroCurrent(p["Vbase"], p["Sbase"], "hybrid_grid_zero")
        refs = {str(source.uref[0]): p["gridVoltage"], str(vsg.uref[0]): p["vsgPref"],
                str(vsg.uref[1]): p["vsgVref"], str(vsg.uref[2]): p["wref"]}
        if self.WITH_GFL:
            gfl = GFL_P_F_L(p["Vbase"], p["gflSbase"], "hybrid_gfl")
            for sourceName, targetName in (("gflLf", "L"), ("gflKpCc", "Kpcc"), ("gflKiCc", "Kicc"),
                                           ("gflKpPll", "KpPll"), ("gflKiPll", "KiPll"),
                                           ("gflKpP", "kpP"), ("gflKiP", "kiP"),
                                           ("gflKpQ", "kpQ"), ("gflKiQ", "kiQ"), ("gflKq", "Kq")):
                gfl.p[targetName]["num"] = p[sourceName]
            gfl.p["Vref"]["num"] = p["gflVref"]
            refs[str(gfl.uref[0])] = p["gflPref"]
            refs[str(gfl.uref[1])] = p["gflQref"]
        else:
            gfl = ZeroCurrent(p["Vbase"], p["Sbase"], "hybrid_pcc_zero")
        devices = {"Vdev": [source, vsg], "Idev": [zero, gfl], "source": source, "vsg": vsg, "gfl": gfl}
        network = {"A": np.array([[1.0], [-1.0]]), "R": [p["Rg"]], "L": [p["Lg"]],
                   "busNames": ["Infinite bus", "PCC"]}
        super().__init__(type(self).__name__, network, devices,
                         {"Vbase": p["Vbase"], "Sbase": p["Sbase"], "frequency_Hz": p["frequency_Hz"]}, refs)
        self.solverSettings["max_step"] = 5e-3 / (2 * np.pi * p["frequency_Hz"])
        self.parameters, self.parameterNames = p, list(p)
        self.enableGFL = self.WITH_GFL

    def calculateSignals(self, time_s, state, networkSignals):
        state = np.asarray(state)
        signals = self.busSignals(networkSignals, np.arange(self.rlGrid.n), 0)
        vsg = self.devices["vsg"]
        idx = [self.stateNames.index(str(symbol)) for symbol in vsg.x]
        devicePower = np.column_stack((networkSignals["voltageDevicePower"][:, 1],
                                       networkSignals["currentDevicePower"][:, 1]))
        scale = np.array([self.parameters["Sbase"] / vsg.Sb,
                          self.parameters["Sbase"] / self.devices["gfl"].Sb])
        devicePower = devicePower * scale
        signals["deviceNames"] = ["GFM", "GFL"]
        signals["deviceActivePower"] = devicePower.real
        signals["deviceReactivePower"] = devicePower.imag
        signals["gflCurrentMagnitude"] = np.abs(networkSignals["currentDeviceCurrent"][:, 1]) * scale[1]
        unlimitedCurrent = state[:, idx[2:4]]
        unlimitedMagnitude = np.linalg.norm(unlimitedCurrent, axis=1)
        limitedCurrent = unlimitedCurrent * np.minimum(1, vsg.p["Imax"]["num"] / np.maximum(unlimitedMagnitude, np.finfo(float).eps))[:, None]
        signals["vsgUnlimitedCurrentDQ"] = unlimitedCurrent
        signals["vsgUnlimitedCurrentMagnitude"] = unlimitedMagnitude
        signals["vsgLimitedCurrentDQ"] = limitedCurrent
        signals["vsgLimitedCurrentMagnitude"] = np.linalg.norm(limitedCurrent, axis=1)
        signals["vsgCurrentReferenceMagnitude"] = unlimitedMagnitude
        signals["vsgFilterCurrentMagnitude"] = np.hypot(state[:, idx[4]], state[:, idx[5]])
        pccVoltage = signals["busVoltageMagnitude"][:, 1]
        signals["gflLvrtMode"] = ((1 + np.tanh(50 * (self.devices["gfl"].p["Vth"]["num"] - pccVoltage))) / 2
                                  if self.enableGFL else np.zeros_like(pccVoltage))
        return signals


class TwoBus__GFM_A_C_LC__GFL_P_F_L(_TwoBus):
    """TwoBus · GFM_A_C_LC (virtual admittance + current PI, circular current-reference limit, LC filter) and
    GFL_P_F_L (outer P/Q loops, FRT current priority, no filter capacitor) at one PCC behind the grid impedance
    set by SCR and rho. Long-term studies and the interaction analysis."""
    WITH_GFL = True


class TwoBus__GFM_A_C_LC(_TwoBus):
    """TwoBus · GFM_A_C_LC alone at the PCC behind the grid impedance (the TwoBus system without the GFL)."""
    WITH_GFL = False
