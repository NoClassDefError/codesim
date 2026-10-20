"""Dynamic voltage-form ZIP load."""

import numpy as np
import sympy as sp

from ..core import Device


class ZIP(Device):
    def __init__(self, Vb, Sb, index):
        super().__init__(Vb, Sb, "Voltage", index, {
            "Ki": 100.0, "w": 1.0, "aZ": 19.0, "aI": 0.0, "aP": 0.0,
            "bZ": 3.8, "bI": 0.0, "bP": 0.0,
        }, ("vZIPd", "vZIPq", "thetaZIP"), ())

    def getStateAndOutputEquationsSym(self):
        vd, vq, theta = self.x
        ia, ib = self.u
        id = sp.cos(theta) * ia + sp.sin(theta) * ib
        iq = -sp.sin(theta) * ia + sp.cos(theta) * ib
        V2 = vd**2 + vq**2
        V2Safe = V2 + 1e-12
        V = sp.sqrt(V2Safe)
        pLoad = self.p["aZ"]["sym"] * V2 + self.p["aI"]["sym"] * V + self.p["aP"]["sym"]
        qLoad = self.p["bZ"]["sym"] * V2 + self.p["bI"]["sym"] * V + self.p["bP"]["sym"]
        iZipD = (-pLoad * vd - qLoad * vq) / V2Safe
        iZipQ = (-pLoad * vq + qLoad * vd) / V2Safe
        return [self.p["Ki"]["sym"] * (iZipD - id),
                self.p["Ki"]["sym"] * (iZipQ - iq), self.p["w"]["sym"]], [
            sp.cos(theta) * vd - sp.sin(theta) * vq,
            sp.sin(theta) * vd + sp.cos(theta) * vq,
        ]

    def getPowerFlowEquations(self, V, theta, P, Q):
        pLoad = self.p["aZ"]["num"] * V**2 + self.p["aI"]["num"] * V + self.p["aP"]["num"]
        qLoad = self.p["bZ"]["num"] * V**2 + self.p["bI"]["num"] * V + self.p["bP"]["num"]
        return [P + pLoad, Q + qLoad]

    def initFromPowerFlow(self, V, theta, P, Q):
        return [abs(V), 0.0, theta]

    def getFInit(self):
        return self.f[:2, :]

    def convertToAnotherBase(self, newVb, newSb):
        voltageScale = newVb / self.Vb
        powerScale = self.Sb / newSb
        for name in ("aZ", "bZ"):
            self.p[name]["num"] *= powerScale * voltageScale**2
        for name in ("aI", "bI"):
            self.p[name]["num"] *= powerScale * voltageScale
        for name in ("aP", "bP"):
            self.p[name]["num"] *= powerScale
        self.Vb, self.Sb = newVb, newSb
        self.Ib = newSb / (np.sqrt(3 / 2) * newVb)
