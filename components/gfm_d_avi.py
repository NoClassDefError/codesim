"""GFM_D_L_LC, GFM_D_S_LC, GFM_D_H_LC: direct GFM with an internal PCC capacitor and adaptive VI."""

import numpy as np
import sympy as sp

from ..core import Device


class _GFMDirectAVI(Device):
    """Current-port GFM with embedded capacitor, grid impedance, and AVI.

    The virtual impedance is ``Z_VI = kVI * g(|i_ref|) * exp(j thetaVI)``.
    ``aviLaw`` selects ``g``: 0 (default) is the AVI excess
    ``max(0, r - Ith)``; 1 is the smooth circular CLC of Presentation
    2026-07-07, ``Phi(r) = r / tanh(r / Imax) - Imax``; 2 is its hard
    counterpart ``max(0, r - Imax)``.
    """
    rmsDynamicStateNames = ("delta",)  # differential in the RMS model (besides frame angles)

    def __init__(self, Vb: float, Sb: float, index: str) -> None:
        super().__init__(
            Vb, Sb, "Current", index,
            {
                "C": 0.1, "Rf": 0.1, "Lf": 0.1,
                "Rg": 0.01, "Lg": 0.1,
                "Ith": 0.9, "kVI": 2.0, "thetaVI": 0.0,
                "Kp": 0.2, "aviLaw": 0, "Imax": 1.5,
            },
            ("vCd", "vCq", "iRefd", "iRefq", "iGd", "iGq",
             "delta", "theta"),
            ("Pref", "Vref", "wref"),
        )

    def viGain(self, magnitude, symbolic=True):
        """``g(r)`` of the virtual impedance for the selected ``aviLaw``.

        The circular law is evaluated with ``sqrt(r^2 + 1e-12)`` so that its
        removable singularity at ``r = 0`` remains finite. Symbolically both laws
        are blended with the ``aviLaw`` symbol, because the equations are built
        before the system sets the parameter.
        """
        if symbolic:
            p = lambda name: self.p[name]["sym"]
            raw = magnitude - p("Ith")
            linear = (raw + sp.Abs(raw)) / 2
            r = sp.sqrt(magnitude**2 + sp.Float(1e-12))
            circular = r / sp.tanh(r / p("Imax")) - p("Imax")
            hard_raw = magnitude - p("Imax")
            hard = (hard_raw + sp.Abs(hard_raw)) / 2
            law = p("aviLaw")
            select_linear = (law - 1) * (law - 2) / 2
            select_circular = law * (2 - law)
            select_hard = law * (law - 1) / 2
            return (
                select_linear * linear
                + select_circular * circular
                + select_hard * hard
            )
        p = lambda name: self.p[name]["num"]
        law = int(p("aviLaw"))
        if law == 1:
            r = np.sqrt(np.asarray(magnitude, float) ** 2 + 1e-12)
            return r / np.tanh(r / p("Imax")) - p("Imax")
        if law == 2:
            return np.maximum(0.0, np.asarray(magnitude, float) - p("Imax"))
        return np.maximum(0.0, np.asarray(magnitude, float) - p("Ith"))

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

        internal_voltage = Vref * sp.Matrix([
            sp.cos(delta), sp.sin(delta),
        ])
        voltage_error = internal_voltage - vc
        base_impedance = p("Rf") * sp.eye(2) + w * p("Lf") * J
        unlimited_current = base_impedance.inv() * voltage_error
        law = p("aviLaw")
        select_avi = (law - 1) * (law - 2) / 2
        select_clc = 1 - select_avi
        current_magnitude = (
            select_avi * sp.sqrt(iref.dot(iref))
            + select_clc * sp.sqrt(unlimited_current.dot(unlimited_current))
        )
        excess = self.viGain(current_magnitude)
        direction = p("kVI") * (
            sp.cos(p("thetaVI")) * sp.eye(2)
            + sp.sin(p("thetaVI")) * J
        )
        virtual_impedance = direction * excess

        diref = (
            voltage_error - p("Rf") * iref
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
        law = int(self.p["aviLaw"]["num"])
        if law == 1:   # called at initialization, after the system set aviLaw
            r = sp.sqrt(magnitude**2 + sp.Float(1e-12))
            excess = (
                r / sp.tanh(r / self.p["Imax"]["num"])
                - self.p["Imax"]["num"]
            )
        elif law == 2:
            raw = magnitude - self.p["Imax"]["num"]
            excess = (raw + sp.Abs(raw)) / 2
        else:
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
        excess = float(self.viGain(np.linalg.norm(iref), symbolic=False))
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


class GFM_D_L_LC(_GFMDirectAVI):
    """GFM · D: internal voltage directly behind Rf + jLf, no inner loops · L: linear adaptive virtual
    impedance, Z_VI = kVI max(0, |i_ref| - Ith) e^(j thetaVI) · LC: terminal capacitor and grid branch in the
    device (current port)."""
    AVI_LAW = 0

    def __init__(self, Vb: float, Sb: float, index: str) -> None:
        super().__init__(Vb, Sb, index)
        self.p["aviLaw"]["num"] = self.AVI_LAW


class GFM_D_S_LC(GFM_D_L_LC):
    """GFM · D: internal voltage directly behind Rf + jLf, no inner loops · S: smooth circular CLC,
    Z_VI = kVI Phi(r) e^(j thetaVI), Phi(r) = r / tanh(r / Imax) - Imax on the unlimited current
    r = |(E - v_C) / (Rf + jLf)| · LC: terminal capacitor and grid branch in the device (current port)."""
    AVI_LAW = 1


class GFM_D_H_LC(GFM_D_L_LC):
    """GFM · D: internal voltage directly behind Rf + jLf, no inner loops · H: hard circular CLC,
    Z_VI = kVI max(0, r - Imax) e^(j thetaVI) on the unlimited current r · LC: terminal capacitor and grid
    branch in the device (current port)."""
    AVI_LAW = 2
