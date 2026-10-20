"""Long-term GFM with an optional parallel GFL."""

import numpy as np

from ..components import GFLVSC, Infbus, VSGCC, ZeroCurrent
from ..core import System


class HybridSystem(System):
    def __init__(self, p, *, EnableGFL=True):
        source = Infbus(p["Vbase"], p["Sbase"], "hybrid_grid")
        vsg = VSGCC(p["Vbase"], p["vsgSbase"], "hybrid_vsg")
        vsg.p["Imax"]["num"] = p["vsgImax"]
        for sourceName, targetName in (("vsgRv", "Rv"), ("vsgLv", "Lv"), ("vsgLf", "Lf"),
                                       ("vsgKpApc", "Kp"), ("vsgKpCc", "Kp_cc"), ("vsgKiCc", "Ki_cc")):
            vsg.p[targetName]["num"] = p[sourceName]
        zero = ZeroCurrent(p["Vbase"], p["Sbase"], "hybrid_grid_zero")
        refs = {str(source.uref[0]): p["gridVoltage"], str(vsg.uref[0]): p["vsgPref"],
                str(vsg.uref[1]): p["vsgVref"], str(vsg.uref[2]): p["wref"]}
        if EnableGFL:
            gfl = GFLVSC(p["Vbase"], p["gflSbase"], "hybrid_gfl")
            for sourceName, targetName in (("gflLf", "L"), ("gflKpCc", "Kpcc"), ("gflKiCc", "Kicc"),
                                           ("gflKpPll", "KpPll"), ("gflKiPll", "KiPll"),
                                           ("gflKpP", "kpP"), ("gflKiP", "kiP"),
                                           ("gflKpQ", "kpQ"), ("gflKiQ", "kiQ"), ("gflKq", "Kq")):
                gfl.p[targetName]["num"] = p[sourceName]
            gfl.p["Vref"]["num"] = p["gflVref"]
            refs[str(gfl.uref[0])] = p["gflPref"]
            refs[str(gfl.uref[1])] = p["gflQref"]
            name = "HybridSystem_gfm_gfl_current_limited" if p["vsgSbase"] == p["Sbase"] and p["gflSbase"] == p["Sbase"] else "HybridSystem_gfm_gfl_current_limited_multibase"
        else:
            gfl = ZeroCurrent(p["Vbase"], p["Sbase"], "hybrid_pcc_zero")
            name = "HybridSystem_gfm_only"
        devices = {"Vdev": [source, vsg], "Idev": [zero, gfl], "source": source, "vsg": vsg, "gfl": gfl}
        network = {"A": np.array([[1.0], [-1.0]]), "R": [p["Rg"]], "L": [p["Lg"]],
                   "busNames": ["Infinite bus", "PCC"]}
        super().__init__(name, network, devices,
                         {"Vbase": p["Vbase"], "Sbase": p["Sbase"], "frequency_Hz": p["frequency_Hz"]}, refs)
        self.parameters, self.parameterNames, self.enableGFL = p, list(p), EnableGFL

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
