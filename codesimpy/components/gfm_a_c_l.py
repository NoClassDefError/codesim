"""GFM_A_C_L: Virtual-admittance GFM without a PCC capacitor."""

import numpy as np
import sympy as sp

from ..core import Device


class GFM_A_C_L(Device):
    """GFM · A: virtual admittance + current PI · C: circular limit on the current reference · L: no terminal capacitor (current port; the grid branch Rg/Lg is in the device)."""

    def __init__(self, Vb: float, Sb: float, index: str) -> None:
        super().__init__(
            Vb, Sb, "Current", index,
            {
                "Lf": 0.07, "Rv": 0.1, "Lv": 0.01,
                "Rg": 0.0, "Lg": 0.0,
                "Imax": 1.5, "Kp": 0.05,
                "Kp_cc": 20.0, "Ki_cc": 5.0,
            },
            ("irefd", "irefq", "iLd", "iLq", "xccd", "xccq",
             "delta", "theta"),
            ("Pref", "Vref", "wref"),
        )

    def getStateAndOutputEquationsSym(self):
        iref = sp.Matrix(self.x[0:2])
        current = sp.Matrix(self.x[2:4])
        xcc = sp.Matrix(self.x[4:6])
        delta, theta = self.x[6:8]
        Pref, Vref, w = self.uref
        gridVoltageStationary = sp.Matrix(self.u)

        p = lambda name: self.p[name]["sym"]
        J = sp.Matrix([[0, -1], [1, 0]])
        rotation = sp.Matrix([
            [sp.cos(theta), -sp.sin(theta)],
            [sp.sin(theta), sp.cos(theta)],
        ])

        # The external voltage port is the infinite bus. With no PCC
        # capacitor, the filter and grid current are identical, so the grid
        # inductor can be eliminated exactly and embedded in this current
        # device.
        gridVoltage = rotation.T * gridVoltageStationary
        gridSideDrop = (
            gridVoltage + p("Rg") * current
            + w * p("Lg") * J * current
        )

        squaredMagnitude = iref.dot(iref)
        denominator = sp.sqrt((
            squaredMagnitude + p("Imax")**2
            + sp.Abs(squaredMagnitude - p("Imax")**2)
        ) / 2)
        limitedReference = p("Imax") * iref / denominator
        currentError = limitedReference - current
        controllerVoltage = (
            p("Kp_cc") * currentError + p("Ki_cc") * xcc
        )
        dcurrent = (
            controllerVoltage - gridSideDrop / 2
        ) / (p("Lf") + p("Lg") / 2)
        pccVoltage = gridSideDrop + p("Lg") * dcurrent

        internalVoltage = Vref * sp.Matrix([
            sp.cos(delta), sp.sin(delta),
        ])
        diref = (
            internalVoltage - pccVoltage - p("Rv") * iref
            - w * p("Lv") * J * iref
        ) / p("Lv")
        ddelta = p("Kp") * (
            Pref - pccVoltage.dot(current)
        )

        outputCurrent = rotation * current
        return (
            list(diref) + list(dcurrent) + list(currentError)
            + [ddelta, w],
            list(outputCurrent),
        )

    def getPowerFlowEquations(self, V, theta, P, Q):
        del theta
        w = self.uref[2]
        current = sp.Matrix([P / V, -Q / V])
        J = sp.Matrix([[0, -1], [1, 0]])
        pccVoltage = (
            sp.Matrix([V, 0]) + self.p["Rg"]["num"] * current
            + w * self.p["Lg"]["num"] * J * current
        )
        internalVoltage = (
            pccVoltage + self.p["Rv"]["num"] * current
            + w * self.p["Lv"]["num"] * J * current
        )
        return [
            self.uref[0] - pccVoltage.dot(current),
            internalVoltage.dot(internalVoltage) - self.uref[1] ** 2,
        ]

    def getFInit(self):
        return self.f[:7, :]

    def initFromPowerFlow(self, V, theta, P, Q):
        w = 1.0
        current = np.array([P / V, -Q / V])
        J = np.array([[0.0, -1.0], [1.0, 0.0]])
        pccVoltage = (
            np.array([V, 0.0]) + self.p["Rg"]["num"] * current
            + w * self.p["Lg"]["num"] * J @ current
        )
        internalVoltage = (
            pccVoltage + self.p["Rv"]["num"] * current
            + w * self.p["Lv"]["num"] * J @ current
        )
        delta = np.arctan2(internalVoltage[1], internalVoltage[0])
        xcc = 0.5 * pccVoltage / self.p["Ki_cc"]["num"]
        return np.r_[current, current, xcc, delta, theta]
