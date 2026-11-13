"""Sixth-order induction motor."""

import numpy as np
import sympy as sp

from ..core import Device


class InductionMotor(Device):
    def __init__(self, Vb, Sb, index):
        Xls, Xlr, Xm = 0.098, 0.098, 1.9597
        Ls, Lr = Xls + Xm, Xlr + Xm
        inductance = np.array([[Ls, 0, Xm, 0], [0, Ls, 0, Xm],
                               [Xm, 0, Lr, 0], [0, Xm, 0, Lr]], dtype=float)
        super().__init__(Vb, Sb, "Current", index, {
            "Rs": 0.0645, "Rr": 0.0645, "Xls": Xls, "Xlr": Xlr,
            "Xm": Xm, "M": 1.0, "G_ab": np.linalg.inv(inductance),
        }, ("psi_ds", "psi_qs", "psi_dr", "psi_qr", "theta", "w"), ("Tm",))

    def getStateAndOutputEquationsSym(self):
        psi_as, psi_bs, psi_ar, psi_br, theta, w = self.x
        G_ab = sp.Matrix(np.asarray(self.p["G_ab"]["sym"], dtype=object).tolist())
        current = G_ab * sp.Matrix([psi_as, psi_bs, psi_ar, psi_br])
        ias, ibs, iar, ibr = (-current[i] for i in range(4))
        va, vb = self.u
        dpsi_as = va - self.p["Rs"]["sym"] * ias
        dpsi_bs = vb - self.p["Rs"]["sym"] * ibs
        dpsi_ar = -self.p["Rr"]["sym"] * iar + w * psi_br
        dpsi_br = -self.p["Rr"]["sym"] * ibr - w * psi_ar
        Te = sp.Rational(3, 2) * (psi_as * ibs - psi_bs * ias)
        return [dpsi_as, dpsi_bs, dpsi_ar, dpsi_br, w - 1,
                (Te - self.uref[0]) / self.p["M"]["sym"]], [ias, ibs]

    def getPowerFlowEquations(self, V, theta, P, Q):
        return [P + self.uref[0], Q + V**2 / (self.p["Xls"]["num"] + self.p["Xm"]["num"])]

    def initFromPowerFlow(self, V, theta, P, Q):
        rotation = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
        statorCurrent = rotation @ (np.array([P, -Q]) / abs(V))
        flux = np.linalg.solve(self.p["G_ab"]["num"], np.r_[-statorCurrent, 0.0, 0.0])
        return np.r_[flux, theta, 1.0]

    def getFInit(self):
        return self.f

    def convertToAnotherBase(self, Vbnew, Sbnew):
        kZ = (Vbnew**2 / Sbnew) / (self.Vb**2 / self.Sb)
        for name in ("Rs", "Rr", "Xls", "Xlr", "Xm"):
            self.p[name]["num"] *= kZ
        Xls, Xlr, Xm = (self.p[name]["num"] for name in ("Xls", "Xlr", "Xm"))
        self.p["G_ab"]["num"] = np.linalg.inv(np.array([
            [Xls + Xm, 0, Xm, 0], [0, Xls + Xm, 0, Xm],
            [Xm, 0, Xlr + Xm, 0], [0, Xm, 0, Xlr + Xm],
        ]))
        self.Vb, self.Sb = Vbnew, Sbnew
        self.Ib = Sbnew / (np.sqrt(3 / 2) * Vbnew)
