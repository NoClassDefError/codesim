"""Infinite-bus voltage source."""

import sympy as sp

from ..core import Device


class Infbus(Device):
    def __init__(self, Vb: float, Sb: float, index: str) -> None:
        super().__init__(
            Vb, Sb, "Voltage", index,
            {"w0": 1.0, "kA": 100.0},
            ("theta", "A"), ("Aref",),
        )

    def getStateAndOutputEquationsSym(self):
        w0 = self.p["w0"]["sym"]
        kA = self.p["kA"]["sym"]
        theta, A = self.x
        Aref = self.uref[0]
        return [w0, kA * (Aref - A)], [A * sp.cos(theta), A * sp.sin(theta)]

    def getPowerFlowEquations(self, V, theta, P, Q):
        return [V - self.uref[0], theta]

    def initFromPowerFlow(self, V, theta, P, Q):
        return [theta, V]

    def convertToAnotherBase(self, Vbnew: float, Sbnew: float) -> None:
        return None

    def getFInit(self):
        return self.f[1:2, :]
