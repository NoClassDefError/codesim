"""Grid-forming converter with PI voltage and current control."""

import numpy as np
import sympy as sp

from ..core import Device


class VSGCCAVC(Device):
    def __init__(self, Vb, Sb, index):
        super().__init__(Vb, Sb, "Voltage", index, {
            "C": 0.068, "Lf": 0.07, "Imax": 1.5, "Kp": 0.05,
            "Kp_avc": 4.0, "Ki_avc": 0.1, "Kp_cc": 20.0, "Ki_cc": 5.0,
        }, ("vCd", "vCq", "xavcd", "xavcq", "iLd", "iLq", "xccd", "xccq", "delta", "theta"),
           ("Pref", "Vref", "wref"))

    def getStateAndOutputEquationsSym(self):
        vc = sp.Matrix(self.x[0:2])
        xavc = sp.Matrix(self.x[2:4])
        il = sp.Matrix(self.x[4:6])
        xcc = sp.Matrix(self.x[6:8])
        delta, theta = self.x[8:10]
        Pref, Vref, w = self.uref
        R = sp.Matrix([[sp.cos(theta), -sp.sin(theta)], [sp.sin(theta), sp.cos(theta)]])
        J = sp.Matrix([[0, -1], [1, 0]])
        ig = R.T * sp.Matrix(self.u)
        ev = Vref * sp.Matrix([sp.cos(delta), sp.sin(delta)]) - vc
        iref = self.p["Kp_avc"]["sym"] * ev + self.p["Ki_avc"]["sym"] * xavc
        r2 = (iref.T * iref)[0]
        Imax = self.p["Imax"]["sym"]
        ireflim = Imax * iref / sp.sqrt((r2 + Imax**2 + sp.Abs(r2 - Imax**2)) / 2)
        ei = ireflim - il
        Lf = self.p["Lf"]["sym"]
        vbridge = vc / 2 + w * Lf * J * il + self.p["Kp_cc"]["sym"] * ei + self.p["Ki_cc"]["sym"] * xcc
        dil = (vbridge - vc) / Lf - w * J * il
        dvc = (il - ig) / self.p["C"]["sym"] - w * J * vc
        ddelta = self.p["Kp"]["sym"] * (Pref - (vc.T * il)[0])
        return sp.Matrix.vstack(dvc, ev, dil, ei, sp.Matrix([ddelta, w])), R * vc

    def getPowerFlowEquations(self, V, theta, P, Q):
        return [self.uref[0] - P, V - self.uref[1]]

    def getFInit(self):
        return self.f[:9, :]

    def initFromPowerFlow(self, V, theta, P, Q):
        vc = np.array([V, 0.0])
        J = np.array([[0.0, -1.0], [1.0, 0.0]])
        il = np.array([P, -Q]) / V + self.p["C"]["num"] * J @ vc
        xavc = il / self.p["Ki_avc"]["num"]
        xcc = 0.5 * vc / self.p["Ki_cc"]["num"]
        return np.r_[vc, xavc, il, xcc, 0.0, theta]
