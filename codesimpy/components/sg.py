"""Eighth-order synchronous generator with AVR and governor."""

import numpy as np
import sympy as sp

from ..core import Device


class SG(Device):
    def __init__(self, Vb, Sb, index):
        Xl, Xad, Xfd, Xf1d, X1d, X1q, Xaq = 0.198, 0.906, 0.1281, -0.01783, 0.0344, 0.1541, 0.218
        Xd = np.array([[Xl + Xad, Xad, Xad], [Xad, X1d + Xad, Xad + Xf1d],
                       [Xad, Xad + Xf1d, Xfd + Xad]])
        Xq = np.array([[Xl + Xaq, Xaq], [Xaq, Xaq + X1q]])
        Gd, Gq = np.linalg.inv(Xd), np.linalg.inv(Xq)
        parameters = {
            "Rs": 0.0645, "Rfd": 1.9597, "R1d": 0.0039, "R1q": 0.00687,
            "Rsnub": 1e4, "Csnub": 1e-4, "Xl": Xl, "Xad": Xad, "Xfd": Xfd,
            "Xf1d": Xf1d, "X1d": X1d, "X1q": X1q, "Xaq": Xaq, "w0": 1.0,
            "Kq": 0.1, "Ka": 120.0, "Ta": 0.15, "Vf0": 0.0,
            "D": 1.0, "M": 2.0, "Kg": 100.0,
        }
        for row in range(3):
            for column in range(3):
                parameters[f"Gd{row + 1}{column + 1}"] = Gd[row, column]
        for row in range(2):
            for column in range(2):
                parameters[f"Gq{row + 1}{column + 1}"] = Gq[row, column]
        super().__init__(Vb, Sb, "Current", index, parameters,
                         ("psi_d", "psi_kd", "psi_fd", "psi_q", "psi_kq1", "vr", "theta", "w"),
                         ("Pref", "Vdref", "Vqref", "wref"))

    def getStateAndOutputEquationsSym(self):
        psi_d, psi_kd, psi_fd, psi_q, psi_kq1, vr, theta, w = self.x
        Pref, Vdref, Vqref, wref = self.uref
        valpha, vbeta = self.u
        vd = valpha * sp.cos(theta) + vbeta * sp.sin(theta)
        vq = -valpha * sp.sin(theta) + vbeta * sp.cos(theta)
        Gd = sp.Matrix([[self.p[f"Gd{r}{c}"]["sym"] for c in range(1, 4)] for r in range(1, 4)])
        Gq = sp.Matrix([[self.p[f"Gq{r}{c}"]["sym"] for c in range(1, 3)] for r in range(1, 3)])
        idVector = Gd * sp.Matrix([psi_d, psi_kd, psi_fd])
        iqVector = Gq * sp.Matrix([psi_q, psi_kq1])
        id, iq = -idVector[0], -iqVector[0]
        P = vd * id + vq * iq
        Q = vq * id - vd * iq
        e = Vdref - sp.sqrt(vd**2 + vq**2) - self.p["Kq"]["sym"] * Q
        vf = self.p["Vf0"]["sym"] + vr
        dpsi_d = vd + self.p["Rs"]["sym"] * id + w * psi_q
        dpsi_kd = -self.p["R1d"]["sym"] * idVector[1]
        dpsi_fd = vf - self.p["Rfd"]["sym"] * idVector[2]
        dpsi_q = vq + self.p["Rs"]["sym"] * iq - w * psi_d
        dpsi_kq1 = -self.p["R1q"]["sym"] * iqVector[1]
        dvr = (-vr + self.p["Ka"]["sym"] * e) / self.p["Ta"]["sym"]
        dtheta = w
        dw = (-P + Pref - (self.p["D"]["sym"] + self.p["Kg"]["sym"]) * w
              + (self.p["D"]["sym"] + self.p["Kg"]["sym"]) * wref) / self.p["M"]["sym"]
        return [dpsi_d, dpsi_kd, dpsi_fd, dpsi_q, dpsi_kq1, dvr, dtheta, dw], [
            id * sp.cos(theta) - iq * sp.sin(theta),
            id * sp.sin(theta) + iq * sp.cos(theta),
        ]

    def getPowerFlowEquations(self, V, theta, P, Q):
        return [P - self.uref[0], V + self.p["Kq"]["num"] * Q - (self.uref[1]**2 + self.uref[2]**2)]

    def getFInit(self):
        return sp.Matrix.vstack(self.f[:6, :], self.f[7:8, :])

    def initFromPowerFlow(self, V, theta, P, Q):
        voltageMagnitude = abs(V)
        w = self.p["w0"]["num"]
        Rs = self.p["Rs"]["num"]
        Xq = self.p["Xl"]["num"] + self.p["Xaq"]["num"]
        activeCurrent, reactiveCurrent = P / voltageMagnitude, Q / voltageMagnitude
        cosineCoefficient = V + Rs * activeCurrent + w * Xq * reactiveCurrent
        sineCoefficient = Rs * reactiveCurrent - w * Xq * activeCurrent
        deltaCandidate = np.arctan2(-cosineCoefficient, sineCoefficient)
        bestFieldCurrent, bestState = -np.inf, None
        for delta in (deltaCandidate, deltaCandidate + np.pi):
            vd, vq = V * np.cos(delta), V * np.sin(delta)
            id = activeCurrent * np.cos(delta) + reactiveCurrent * np.sin(delta)
            iq = activeCurrent * np.sin(delta) - reactiveCurrent * np.cos(delta)
            psiQ = -Xq * iq
            psiD = (vq + Rs * iq) / w
            Xd = self.p["Xl"]["num"] + self.p["Xad"]["num"]
            fieldCurrent = (psiD + Xd * id) / self.p["Xad"]["num"]
            psiKd = -self.p["Xad"]["num"] * id + (self.p["Xad"]["num"] + self.p["Xf1d"]["num"]) * fieldCurrent
            psiFd = -self.p["Xad"]["num"] * id + (self.p["Xfd"]["num"] + self.p["Xad"]["num"]) * fieldCurrent
            psiKq = -self.p["Xaq"]["num"] * iq
            regulatorState = self.p["Rfd"]["num"] * fieldCurrent - self.p["Vf0"]["num"]
            if fieldCurrent > bestFieldCurrent:
                bestFieldCurrent = fieldCurrent
                bestState = [psiD, psiKd, psiFd, psiQ, psiKq, regulatorState, theta - delta, w]
        return bestState

    def convertToAnotherBase(self, Vbnew, Sbnew):
        kZ = (Vbnew**2 / Sbnew) / (self.Vb**2 / self.Sb)
        for name in ("Rs", "Rfd", "R1d", "R1q", "Rsnub", "Xl", "Xad", "Xaq", "Xf1d", "Xfd", "X1d", "X1q"):
            self.p[name]["num"] *= kZ
        Xl, Xad, Xfd, Xf1d, X1d, X1q, Xaq = (self.p[name]["num"] for name in ("Xl", "Xad", "Xfd", "Xf1d", "X1d", "X1q", "Xaq"))
        Gd = np.linalg.inv(np.array([[Xl + Xad, Xad, Xad], [Xad, X1d + Xad, Xad + Xf1d], [Xad, Xad + Xf1d, Xfd + Xad]]))
        Gq = np.linalg.inv(np.array([[Xl + Xaq, Xaq], [Xaq, Xaq + X1q]]))
        for row in range(3):
            for column in range(3):
                self.p[f"Gd{row + 1}{column + 1}"]["num"] = Gd[row, column]
        for row in range(2):
            for column in range(2):
                self.p[f"Gq{row + 1}{column + 1}"]["num"] = Gq[row, column]
        self.Vb, self.Sb = Vbnew, Sbnew
        self.Ib = Sbnew / (np.sqrt(3 / 2) * Vbnew)
