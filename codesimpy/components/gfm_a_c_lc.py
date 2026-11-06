"""Virtual-admittance GFM with PI current control and an LC filter."""

import numpy as np
import sympy as sp

from ..core import Device


class VSGCC(Device):
    def __init__(self, Vb: float, Sb: float, index: str) -> None:
        super().__init__(
            Vb, Sb, "Voltage", index,
            {
                "C": 0.068, "Lf": 0.07, "Rv": 0.1, "Lv": 0.01,
                "Imax": 1.5, "Kp": 0.05, "Kp_cc": 20.0, "Ki_cc": 5.0,
            },
            ("vCd", "vCq", "irefd", "irefq", "iLd", "iLq",
             "xccd", "xccq", "delta", "theta"),
            ("Pref", "Vref", "wref"),
        )

    def getStateAndOutputEquationsSym(self):
        C = self.p["C"]["sym"]
        Lf = self.p["Lf"]["sym"]
        Rv = self.p["Rv"]["sym"]
        Lv = self.p["Lv"]["sym"]
        Imax = self.p["Imax"]["sym"]
        Kp = self.p["Kp"]["sym"]
        Kp_cc = self.p["Kp_cc"]["sym"]
        Ki_cc = self.p["Ki_cc"]["sym"]
        vc = sp.Matrix(self.x[0:2])
        iref = sp.Matrix(self.x[2:4])
        il = sp.Matrix(self.x[4:6])
        xcc = sp.Matrix(self.x[6:8])
        delta, theta = self.x[8:10]
        Pref, Vref, w = self.uref
        rotation = sp.Matrix([
            [sp.cos(theta), -sp.sin(theta)],
            [sp.sin(theta), sp.cos(theta)],
        ])
        ig = rotation.T * sp.Matrix(self.u)
        J = sp.Matrix([[0, -1], [1, 0]])
        vs = Vref * sp.Matrix([sp.cos(delta), sp.sin(delta)])
        diref = (vs - vc - Rv * iref - w * Lv * J * iref) / Lv
        r2 = (iref.T * iref)[0]
        denominator = sp.sqrt((r2 + Imax**2 + sp.Abs(r2 - Imax**2)) / 2)
        ireflim = Imax * iref / denominator
        ei = ireflim - il
        vbridge = sp.Rational(1, 2) * vc + w * Lf * J * il + Kp_cc * ei + Ki_cc * xcc
        dil = (vbridge - vc) / Lf - w * J * il
        dvc = (il - ig) / C - w * J * vc
        ddelta = Kp * (Pref - (vc.T * il)[0])
        f = sp.Matrix.vstack(dvc, diref, dil, ei, sp.Matrix([ddelta, w]))
        return f, rotation * vc

    def getPowerFlowEquations(self, V, theta, P, Q):
        w = self.uref[2]
        C = self.p["C"]["num"]
        Rv = self.p["Rv"]["num"]
        Lv = self.p["Lv"]["num"]
        J = sp.Matrix([[0, -1], [1, 0]])
        vc = sp.Matrix([V, 0])
        il = sp.Matrix([P, -Q]) / V + C * w * J * vc
        vs = vc + (Rv * sp.eye(2) + w * Lv * J) * il
        return [self.uref[0] - P, (vs.T * vs)[0] - self.uref[1] ** 2]

    def getFInit(self):
        return self.f[:9, :]

    def initFromPowerFlow(self, V, theta, P, Q):
        C = self.p["C"]["num"]
        Rv = self.p["Rv"]["num"]
        Lv = self.p["Lv"]["num"]
        Ki_cc = self.p["Ki_cc"]["num"]
        vc = np.array([V, 0.0])
        J = np.array([[0.0, -1.0], [1.0, 0.0]])
        il = np.array([P, -Q]) / V + C * J @ vc
        vs = vc + (Rv * np.eye(2) + Lv * J) @ il
        delta = np.arctan2(vs[1], vs[0])
        xcc = 0.5 * vc / Ki_cc
        return np.r_[vc, il, il, xcc, delta, theta]
