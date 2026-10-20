"""Grid-following converter with P control and Q-V droop."""

import numpy as np
import sympy as sp

from ..core import Device


class GFLLongTerm(Device):
    def __init__(self, Vb, Sb, index):
        super().__init__(Vb, Sb, "Current", index, {
            "L": 3.25e-4, "Kicc": 5.0, "Kpcc": 0.1,
            "KpPll": 0.01, "KiPll": 0.5, "wPllMin": 0.8,
            "wPllMax": 1.2, "KawPll": 5.0, "kpP": 0.02,
            "kiP": 1e-3, "kpQ": 0.02, "kiQ": 1e-3,
            "Kq": 0.05, "w0": 1.0,
        }, ("id", "iq", "xPIccd", "xPIccq", "vPIoutd", "vPIoutq", "theta", "xPLL"),
           ("Pref", "Vref", "Qref"))

    def getStateAndOutputEquationsSym(self):
        id, iq, xPIccd, xPIccq, xPIoutd, xPIoutq, theta, xPLL = self.x
        Pref, Vref, Qref = self.uref
        valpha, vbeta = self.u
        vd = valpha * sp.cos(theta) + vbeta * sp.sin(theta)
        vq = -valpha * sp.sin(theta) + vbeta * sp.cos(theta)
        wRaw = self.p["w0"]["sym"] + self.p["KpPll"]["sym"] * vq + self.p["KiPll"]["sym"] * xPLL
        wUpper = (wRaw + self.p["wPllMax"]["sym"] - sp.Abs(wRaw - self.p["wPllMax"]["sym"])) / 2
        w = (wUpper + self.p["wPllMin"]["sym"] + sp.Abs(wUpper - self.p["wPllMin"]["sym"])) / 2
        P = vd * id + vq * iq
        Q = vq * id - vd * iq
        Vcmd = Vref + self.p["Kq"]["sym"] * (Qref - Q)
        eP = Pref - P
        eV = Vcmd - sp.sqrt(vd**2 + vq**2)
        idref = self.p["kpP"]["sym"] * eP + self.p["kiP"]["sym"] * xPIoutd
        iqref = -(self.p["kpQ"]["sym"] * eV + self.p["kiQ"]["sym"] * xPIoutq)
        ed, eq = idref - id, iqref - iq
        L = self.p["L"]["sym"]
        vconvD = self.p["Kpcc"]["sym"] * ed + self.p["Kicc"]["sym"] * xPIccd + vd - w * L * iq
        vconvQ = self.p["Kpcc"]["sym"] * eq + self.p["Kicc"]["sym"] * xPIccq + vq + w * L * id
        did = (vconvD - vd + w * L * iq) / L
        diq = (vconvQ - vq - w * L * id) / L
        dxPLL = vq + self.p["KawPll"]["sym"] * (w - wRaw)
        return [did, diq, ed, eq, eP, eV, w, dxPLL], [
            id * sp.cos(theta) - iq * sp.sin(theta),
            id * sp.sin(theta) + iq * sp.cos(theta),
        ]

    def getPowerFlowEquations(self, V, theta, P, Q):
        Vcmd = self.uref[1] + self.p["Kq"]["num"] * (self.uref[2] - Q)
        return [P - self.uref[0], V - Vcmd]

    def getFInit(self):
        return sp.Matrix.vstack(self.f[:6, :], self.f[7:8, :])

    def initFromPowerFlow(self, V, theta, P, Q):
        id, iq = P / V, -Q / V
        return [id, iq, 0.0, 0.0, id / self.p["kiP"]["num"],
                -iq / self.p["kiQ"]["num"], theta, 0.0]
