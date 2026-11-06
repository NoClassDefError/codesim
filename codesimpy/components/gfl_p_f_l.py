"""Grid-following converter with smooth LVRT current priority."""

import sympy as sp

from ..core import Device


class GFLVSC(Device):
    def __init__(self, Vb, Sb, index):
        super().__init__(Vb, Sb, "Current", index, {
            "L": 3.25e-4, "Kicc": 5.0, "Kpcc": 0.1,
            "KpPll": 0.01, "KiPll": 0.5, "wPllMin": 0.8,
            "wPllMax": 1.2, "KawPll": 5.0, "kpP": 0.02,
            "kiP": 1e-3, "kpQ": 0.02, "kiQ": 1e-3,
            "Vctrl": 0.0, "Vref": 1.0, "Kq": 0.05, "w0": 1.0,
            "K1": 1.5, "Imax": 1.5, "Id2": 1.2, "Vth": 0.9,
        }, ("id", "iq", "xPIccd", "xPIccq", "vPIoutd", "vPIoutq", "theta", "xPLL"),
           ("Pref", "Qref"))

    def getStateAndOutputEquationsSym(self):
        id, iq, xPIccd, xPIccq, xPIoutd, xPIoutq, theta, xPLL = self.x
        Pref, Qref = self.uref
        valpha, vbeta = self.u
        vd = valpha * sp.cos(theta) + vbeta * sp.sin(theta)
        vq = -valpha * sp.sin(theta) + vbeta * sp.cos(theta)
        wRaw = self.p["w0"]["sym"] + self.p["KpPll"]["sym"] * vq + self.p["KiPll"]["sym"] * xPLL
        wUpper = (wRaw + self.p["wPllMax"]["sym"] - sp.Abs(wRaw - self.p["wPllMax"]["sym"])) / 2
        w = (wUpper + self.p["wPllMin"]["sym"] + sp.Abs(wUpper - self.p["wPllMin"]["sym"])) / 2
        P = vd * id + vq * iq
        Q = vq * id - vd * iq
        vg = sp.sqrt(vd**2 + vq**2)
        Qcmd = Qref + self.p["Vctrl"]["sym"] * (self.p["Vref"]["sym"] - vg) / self.p["Kq"]["sym"]
        eP, eQ = Pref - P, Qcmd - Q
        Imax = self.p["Imax"]["sym"]
        idRaw = self.p["kpP"]["sym"] * eP + self.p["kiP"]["sym"] * xPIoutd
        idLower = (idRaw + sp.Abs(idRaw)) / 2
        idNormal = (idLower + Imax - sp.Abs(idLower - Imax)) / 2
        iqRaw = -(self.p["kpQ"]["sym"] * eQ + self.p["kiQ"]["sym"] * xPIoutq)
        iqLimit = sp.sqrt((Imax**2 - idNormal**2 + sp.Abs(Imax**2 - idNormal**2)) / 2)
        iqUpper = (iqRaw + iqLimit - sp.Abs(iqRaw - iqLimit)) / 2
        iqNormal = (iqUpper - iqLimit + sp.Abs(iqUpper + iqLimit)) / 2
        iqLvrtRaw = -self.p["K1"]["sym"] * (self.p["Vth"]["sym"] - vg)
        iqLvrtUpper = (iqLvrtRaw + Imax - sp.Abs(iqLvrtRaw - Imax)) / 2
        iqLvrt = (iqLvrtUpper - Imax + sp.Abs(iqLvrtUpper + Imax)) / 2
        idLimit = sp.sqrt((Imax**2 - iqLvrt**2 + sp.Abs(Imax**2 - iqLvrt**2)) / 2)
        idLvrt = (self.p["Id2"]["sym"] + idLimit - sp.Abs(self.p["Id2"]["sym"] - idLimit)) / 2
        lvrtMode = (1 + sp.tanh(50 * (self.p["Vth"]["sym"] - vg))) / 2
        idref = (1 - lvrtMode) * idNormal + lvrtMode * idLvrt
        iqref = (1 - lvrtMode) * iqNormal + lvrtMode * iqLvrt
        ed, eq = idref - id, iqref - iq
        L = self.p["L"]["sym"]
        vconvD = self.p["Kpcc"]["sym"] * ed + self.p["Kicc"]["sym"] * xPIccd + vd - w * L * iq
        vconvQ = self.p["Kpcc"]["sym"] * eq + self.p["Kicc"]["sym"] * xPIccq + vq + w * L * id
        did = (vconvD - vd + w * L * iq) / L
        diq = (vconvQ - vq - w * L * id) / L
        dxPLL = vq + self.p["KawPll"]["sym"] * (w - wRaw)
        return [did, diq, ed, eq, (1 - lvrtMode) * eP, (1 - lvrtMode) * eQ, w, dxPLL], [
            id * sp.cos(theta) - iq * sp.sin(theta),
            id * sp.sin(theta) + iq * sp.cos(theta),
        ]

    def getPowerFlowEquations(self, V, theta, P, Q):
        return [P - self.uref[0], Q - self.uref[1]]

    def getFInit(self):
        return sp.Matrix.vstack(self.f[:6, :], self.f[7:8, :])

    def initFromPowerFlow(self, V, theta, P, Q):
        id, iq = P / V, -Q / V
        return [id, iq, 0.0, 0.0, id / self.p["kiP"]["num"],
                -iq / self.p["kiQ"]["num"], theta, 0.0]
