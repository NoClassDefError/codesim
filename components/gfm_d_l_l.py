"""GFM_D_L_L: direct GFM with linear adaptive virtual impedance and no terminal capacitor."""

import numpy as np
import sympy as sp

from ..core import Device


class GFM_D_L_L(Device):
    """GFM · D: internal voltage V∠delta directly behind Rf + jLf, no inner loops · L: linear adaptive virtual
    impedance, Z_VI = kVI max(0, |i_M| - Ith) e^(j thetaVI) · L: no terminal capacitor (current port; the grid
    branch Rg/Lg is in the device, so filter and line carry the same current i_M).

    In the GFM dq frame (angle ``theta``, ``dtheta/dtau = w``) with the port voltage ``v_t``::

        (Lf + Lg) di_M/dtau = V∠delta - v_t - (Rf + Rg) i_M - w (Lf + Lg) J i_M - Z_VI(|i_M|) i_M
        v_M = v_t + (Rg + w Lg J) i_M + Lg di_M/dtau
        ddelta/dtau = Kp (Pref - v_M . i_M)

    ``v_M`` is the converter terminal voltage, behind the embedded line (slide: v_M = v_t + Z_1 i_M).
    """
    rmsDynamicStateNames = ("delta",)  # differential in the RMS model (besides frame angles)

    def __init__(self, Vb: float, Sb: float, index: str) -> None:
        super().__init__(
            Vb, Sb, "Current", index,
            {
                "Rf": 0.1, "Lf": 0.1, "Rg": 0.0, "Lg": 0.0,
                "Ith": 1.1, "kVI": 2.0, "thetaVI": 0.0,
                "Kp": 0.05, "Imax": 1.5,
            },
            ("iMd", "iMq", "delta", "theta"),
            ("Pref", "Vref", "wref"),
        )

    @staticmethod
    def _rotation(angle, module=sp):
        return sp.Matrix([[module.cos(angle), -module.sin(angle)], [module.sin(angle), module.cos(angle)]])

    def virtualImpedanceGain(self, magnitude, symbolic=True):
        """``kVI max(0, |i| - Ith)``."""
        if symbolic:
            p = lambda name: self.p[name]["sym"]
            raw = magnitude - p("Ith")
            return p("kVI") * (raw + sp.Abs(raw)) / 2
        p = lambda name: self.p[name]["num"]
        return p("kVI") * np.maximum(0.0, np.asarray(magnitude, float) - p("Ith"))

    def getStateAndOutputEquationsSym(self):
        i = sp.Matrix(self.x[0:2])
        delta, theta = self.x[2:4]
        Pref, Vref, w = self.uref
        p = lambda name: self.p[name]["sym"]
        J = sp.Matrix([[0, -1], [1, 0]])
        rotation = self._rotation(theta)
        vt = rotation.T * sp.Matrix(self.u)

        Lt, Rt = p("Lf") + p("Lg"), p("Rf") + p("Rg")
        internal = Vref * sp.Matrix([sp.cos(delta), sp.sin(delta)])
        gain = self.virtualImpedanceGain(sp.sqrt(i.dot(i)))
        virtualImpedance = gain * (sp.cos(p("thetaVI")) * sp.eye(2) + sp.sin(p("thetaVI")) * J)
        di = (internal - vt - Rt * i - w * Lt * J * i - virtualImpedance * i) / Lt
        vM = vt + p("Rg") * i + w * p("Lg") * J * i + p("Lg") * di
        ddelta = p("Kp") * (Pref - vM.dot(i))
        return list(di) + [ddelta, w], list(rotation * i)

    def _steadyState(self, V, P, Q, w, module):
        """Current, terminal voltage and internal EMF in the bus-voltage frame."""
        J = module.Matrix([[0, -1], [1, 0]]) if module is sp else np.array([[0.0, -1.0], [1.0, 0.0]])
        num = lambda name: self.p[name]["num"]
        if module is sp:
            i = sp.Matrix([P / V, -Q / V])
            magnitude = sp.sqrt(i.dot(i))
            raw = magnitude - num("Ith")
            gain = num("kVI") * (raw + sp.Abs(raw)) / 2
            vt = sp.Matrix([V, 0])
            mul = lambda M, x: M * x
            eye = sp.eye(2)
        else:
            i = np.array([P / V, -Q / V])
            gain = float(self.virtualImpedanceGain(np.linalg.norm(i), symbolic=False))
            vt = np.array([V, 0.0])
            mul = lambda M, x: M @ x
            eye = np.eye(2)
        vM = vt + num("Rg") * i + w * num("Lg") * mul(J, i)
        direction = np.cos(num("thetaVI")) * eye + np.sin(num("thetaVI")) * J
        internal = vM + num("Rf") * i + w * num("Lf") * mul(J, i) + gain * mul(direction, i)
        return i, vM, internal

    def getPowerFlowEquations(self, V, theta, P, Q):
        del theta
        i, vM, internal = self._steadyState(V, P, Q, self.uref[2], sp)
        return [self.uref[0] - vM.dot(i), internal.dot(internal) - self.uref[1] ** 2]

    def getFInit(self):
        return self.f[:3, :]

    def initFromPowerFlow(self, V, theta, P, Q):
        i, _, internal = self._steadyState(V, P, Q, 1.0, np)
        return np.r_[i, np.arctan2(internal[1], internal[0]), theta]
