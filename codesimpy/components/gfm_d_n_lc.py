"""Grid-forming converter with an LC filter and current-limit parameters."""

import numpy as np
import sympy as sp

from ..core import Device


class VSGCL(Device):
    def __init__(self, Vb: float, Sb: float, index: str) -> None:
        super().__init__(
            Vb, Sb, "Voltage", index,
            {
                "C": 0.068, "Rf": 0.1, "Lf": 0.1, "Imax": 1.2,
                "Kp": 0.1, "Ith": 1.0, "kVI": 2.0, "thetaVI": np.pi / 4,
            },
            ("vCd", "vCq", "iLd", "iLq", "delta", "theta"),
            ("Pref", "Vref", "wref"),
        )

    def getStateAndOutputEquationsSym(self):
        C = self.p["C"]["sym"]
        Rf = self.p["Rf"]["sym"]
        Lf = self.p["Lf"]["sym"]
        Kp = self.p["Kp"]["sym"]
        vo = sp.Matrix(self.x[0:2])
        iLv = sp.Matrix(self.x[2:4])
        delta, theta = self.x[4:6]
        Pref, Vref, w = self.uref
        ia, ib = self.u
        iLg = sp.Matrix([
            ia * sp.cos(theta) + ib * sp.sin(theta),
            -ia * sp.sin(theta) + ib * sp.cos(theta),
        ])
        J = sp.Matrix([[0, -1], [1, 0]])
        vs = Vref * sp.Matrix([sp.cos(delta), sp.sin(delta)])
        diLv = (vs - vo - Rf * iLv - w * Lf * J * iLv) / Lf
        dvo = (iLv - iLg) / C - w * J * vo
        ddelta = Kp * (Pref - (vo.T * iLg)[0])
        rotation = sp.Matrix([
            [sp.cos(theta), -sp.sin(theta)],
            [sp.sin(theta), sp.cos(theta)],
        ])
        return sp.Matrix.vstack(dvo, diLv, sp.Matrix([ddelta, w])), rotation * vo

    def getPowerFlowEquations(self, V, theta, P, Q):
        w = self.uref[2]
        C = self.p["C"]["num"]
        Rf = self.p["Rf"]["num"]
        Lf = self.p["Lf"]["num"]
        J = sp.Matrix([[0, -1], [1, 0]])
        vo = sp.Matrix([V, 0])
        iLv = sp.Matrix([P, -Q]) / V + C * w * J * vo
        internalVoltage = vo + (Rf * sp.eye(2) + w * Lf * J) * iLv
        return [self.uref[0] - P, (internalVoltage.T * internalVoltage)[0] - self.uref[1] ** 2]

    def getFInit(self):
        return self.f[:5, :]

    def initFromPowerFlow(self, V, theta, P, Q):
        voltageMagnitude = max(abs(V), 1e-8)
        vo = np.array([voltageMagnitude, 0.0])
        iLg = np.array([P, -Q]) / voltageMagnitude
        C = self.p["C"]["num"]
        Rf = self.p["Rf"]["num"]
        Lf = self.p["Lf"]["num"]
        J = np.array([[0.0, -1.0], [1.0, 0.0]])
        iLv = iLg + C * J @ vo
        internalVoltage = vo + (Rf * np.eye(2) + Lf * J) @ iLv
        delta = np.arctan2(internalVoltage[1], internalVoltage[0])
        return np.r_[vo, iLv, delta, theta]
