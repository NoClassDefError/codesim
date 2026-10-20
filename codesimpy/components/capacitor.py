"""Synchronous-frame shunt capacitor."""

import numpy as np
import sympy as sp

from ..core import Device


class Capacitor(Device):
    def __init__(self, Vb, Sb, index):
        super().__init__(Vb, Sb, "Voltage", index, {"C": 0.068, "Gd": 0.0, "w": 1.0},
                         ("vCd", "vCq", "thetaC"), ())

    def getStateAndOutputEquationsSym(self):
        vCd, vCq, theta = self.x
        ia, ib = self.u
        C, Gd, w = (self.p[name]["sym"] for name in ("C", "Gd", "w"))
        id = ia * sp.cos(theta) + ib * sp.sin(theta)
        iq = -ia * sp.sin(theta) + ib * sp.cos(theta)
        f = [( -id - Gd * vCd) / C + w * vCq,
             ( -iq - Gd * vCq) / C - w * vCd, w]
        return f, [vCd * sp.cos(theta) - vCq * sp.sin(theta),
                   vCd * sp.sin(theta) + vCq * sp.cos(theta)]

    def getPowerFlowEquations(self, V, theta, P, Q):
        return [P + self.p["Gd"]["num"] * V**2,
                Q - self.p["w"]["num"] * self.p["C"]["num"] * V**2]

    def initFromPowerFlow(self, V, theta, P, Q):
        return [abs(V), 0.0, theta]

    def getFInit(self):
        return self.f[:2, :]

    def convertToAnotherBase(self, Vbnew, Sbnew):
        scaleZ = (Vbnew**2 / Sbnew) / (self.Vb**2 / self.Sb)
        self.p["C"]["num"] /= scaleZ
        self.p["Gd"]["num"] *= scaleZ
        self.Vb, self.Sb = Vbnew, Sbnew
        self.Ib = Sbnew / (np.sqrt(3 / 2) * Vbnew)
