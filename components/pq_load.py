"""Algebraic constant-power current injection."""

import numpy as np
import sympy as sp

from ..core import Device


class PQLoad(Device):
    def __init__(self, Vb, Sb, index):
        super().__init__(Vb, Sb, "Current", index, {}, (), ("Pref", "Qref"))

    def getStateAndOutputEquationsSym(self):
        va, vb = self.u
        Pref, Qref = self.uref
        voltageSquared = sp.Max(va**2 + vb**2, 1e-8)
        return [], [(Pref * va + Qref * vb) / voltageSquared,
                    (Pref * vb - Qref * va) / voltageSquared]

    def getPowerFlowEquations(self, V, theta, P, Q):
        return [P - self.uref[0], Q - self.uref[1]]

    def initFromPowerFlow(self, V, theta, P, Q):
        return []

    def getFInit(self):
        return self.f

    def convertToAnotherBase(self, Vbnew, Sbnew):
        self.Vb, self.Sb = Vbnew, Sbnew
        self.Ib = Sbnew / (np.sqrt(3 / 2) * Vbnew)
