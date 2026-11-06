"""Grid-forming converter with an internal PCC capacitor and adaptive VI."""

import numpy as np
import sympy as sp

from ..core import Device


class GFMAVI(Device):
    """Current-port GFM with embedded capacitor, grid impedance, and AVI."""

    def __init__(self, Vb: float, Sb: float, index: str) -> None:
        super().__init__(
            Vb, Sb, "Current", index,
            {
                "C": 0.1, "Rf": 0.1, "Lf": 0.1,
                "Rg": 0.01, "Lg": 0.1,
                "Ith": 0.9, "kVI": 2.0, "thetaVI": 0.0,
                "Kp": 0.2,
            },
            ("vCd", "vCq", "iRefd", "iRefq", "iGd", "iGq",
             "delta", "theta"),
            ("Pref", "Vref", "wref"),
        )

    def getStateAndOutputEquationsSym(self):
        vc = sp.Matrix(self.x[0:2])
        iref = sp.Matrix(self.x[2:4])
        ig = sp.Matrix(self.x[4:6])
        delta, theta = self.x[6:8]
        Pref, Vref, w = self.uref
        grid_stationary = sp.Matrix(self.u)
        p = lambda name: self.p[name]["sym"]
        J = sp.Matrix([[0, -1], [1, 0]])
        rotation = sp.Matrix([
            [sp.cos(theta), -sp.sin(theta)],
            [sp.sin(theta), sp.cos(theta)],
        ])
        grid = rotation.T * grid_stationary

        current_magnitude = sp.sqrt(iref.dot(iref))
        excess_raw = current_magnitude - p("Ith")
        excess = (excess_raw + sp.Abs(excess_raw)) / 2
        direction = p("kVI") * (
            sp.cos(p("thetaVI")) * sp.eye(2)
            + sp.sin(p("thetaVI")) * J
        )
        virtual_impedance = direction * excess

        internal_voltage = Vref * sp.Matrix([
            sp.cos(delta), sp.sin(delta),
        ])
        diref = (
            internal_voltage - vc - p("Rf") * iref
            - w * p("Lf") * J * iref
            - virtual_impedance * iref
        ) / p("Lf")
        dvc = (iref - ig) / p("C") - w * J * vc
        dig = (
            vc - grid - p("Rg") * ig - w * p("Lg") * J * ig
        ) / p("Lg")
        ddelta = p("Kp") * (Pref - vc.dot(ig))

        output_current = rotation * ig
        return (
            list(dvc) + list(diref) + list(dig) + [ddelta, w],
            list(output_current),
        )

    def getPowerFlowEquations(self, V, theta, P, Q):
        del theta
        w = self.uref[2]
        J = sp.Matrix([[0, -1], [1, 0]])
        grid = sp.Matrix([V, 0])
        ig = sp.Matrix([P / V, -Q / V])
        vc = (
            grid + self.p["Rg"]["num"] * ig
            + w * self.p["Lg"]["num"] * J * ig
        )
        iref = ig + self.p["C"]["num"] * w * J * vc
        magnitude = sp.sqrt(iref.dot(iref))
        raw = magnitude - self.p["Ith"]["num"]
        excess = (raw + sp.Abs(raw)) / 2
        direction = self.p["kVI"]["num"] * (
            np.cos(self.p["thetaVI"]["num"]) * sp.eye(2)
            + np.sin(self.p["thetaVI"]["num"]) * J
        )
        internal_voltage = (
            vc + self.p["Rf"]["num"] * iref
            + w * self.p["Lf"]["num"] * J * iref
            + direction * excess * iref
        )
        return [
            self.uref[0] - vc.dot(ig),
            internal_voltage.dot(internal_voltage) - self.uref[1] ** 2,
        ]

    def getFInit(self):
        return self.f[:7, :]

    def initFromPowerFlow(self, V, theta, P, Q):
        w = 1.0
        J = np.array([[0.0, -1.0], [1.0, 0.0]])
        grid = np.array([V, 0.0])
        ig = np.array([P / V, -Q / V])
        vc = (
            grid + self.p["Rg"]["num"] * ig
            + w * self.p["Lg"]["num"] * J @ ig
        )
        iref = ig + self.p["C"]["num"] * w * J @ vc
        excess = max(0.0, np.linalg.norm(iref) - self.p["Ith"]["num"])
        direction = self.p["kVI"]["num"] * (
            np.cos(self.p["thetaVI"]["num"]) * np.eye(2)
            + np.sin(self.p["thetaVI"]["num"]) * J
        )
        internal_voltage = (
            vc + self.p["Rf"]["num"] * iref
            + w * self.p["Lf"]["num"] * J @ iref
            + direction * excess @ iref
        )
        delta = np.arctan2(internal_voltage[1], internal_voltage[0])
        return np.r_[vc, iref, ig, delta, theta]
