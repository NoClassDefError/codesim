"""First-order constant-power voltage device."""

import numpy as np
import sympy as sp

from ..core import Device


class CPL(Device):
    def __init__(self, Vb, Sb, index):
        super().__init__(Vb, Sb, "Voltage", index, {"T": 1e-2, "w": 1.0},
                         ("vCPLd", "vCPLq", "thetaCPL"), ("Pref", "Qref"))

    def getStateAndOutputEquationsSym(self):
        ia, ib = self.u
        Pref, Qref = self.uref
        vd, vq, theta = self.x
        T, w = self.p["T"]["sym"], self.p["w"]["sym"]
        id = ia * sp.cos(theta) + ib * sp.sin(theta)
        iq = -ia * sp.sin(theta) + ib * sp.cos(theta)
        currentSquared = id**2 + iq**2 + 1e-8
        vdReference = (Pref * id - Qref * iq) / currentSquared
        vqReference = (Pref * iq + Qref * id) / currentSquared
        return [(vdReference - vd) / T, (vqReference - vq) / T, w], [
            vd * sp.cos(theta) - vq * sp.sin(theta),
            vd * sp.sin(theta) + vq * sp.cos(theta),
        ]

    def getPowerFlowEquations(self, V, theta, P, Q):
        return [P - self.uref[0], Q - self.uref[1]]

    def initFromPowerFlow(self, V, theta, P, Q):
        return [abs(V), 0.0, theta]

    def getFInit(self):
        return self.f[:2, :]

    def convertToAnotherBase(self, Vbnew, Sbnew):
        self.Vb, self.Sb = Vbnew, Sbnew
        self.Ib = Sbnew / (np.sqrt(3 / 2) * Vbnew)
