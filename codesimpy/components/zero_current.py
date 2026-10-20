"""Empty current port used to close a voltage-device bus."""

from ..core import Device


class ZeroCurrent(Device):
    def __init__(self, Vb: float, Sb: float, index: str) -> None:
        super().__init__(Vb, Sb, "Current", index, {}, (), ())

    def getStateAndOutputEquationsSym(self):
        return [], [0, 0]

    def getPowerFlowEquations(self, V, theta, P, Q):
        return [P, Q]

    def initFromPowerFlow(self, V, theta, P, Q):
        return []

    def convertToAnotherBase(self, Vbnew: float, Sbnew: float) -> None:
        return None

    def getFInit(self):
        return self.f
