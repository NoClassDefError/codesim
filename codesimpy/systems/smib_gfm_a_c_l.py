"""SMIB__GFM_A_C_L: no-capacitor GFM connected directly to an infinite bus."""

from typing import Any

import numpy as np

from ..components import GFM_A_C_L, Infbus
from ..core import System


class SMIB__GFM_A_C_L(System):
    """SMIB · GFM_A_C_L: virtual admittance + current PI, circular current-reference limit, no terminal
    capacitor; the grid impedance is embedded in the device (current port)."""

    @staticmethod
    def defaultParameters(overrides=None):
        p = {
            "Vbase": 1, "Sbase": 8100, "frequency_Hz": 50,
            "SCR": 2, "rho": 0.1,
            "Pref": 1, "Vref": 1.1, "wref": 1,
            "Lf": 0.07, "Rv": 0.05, "Lv": 0.01,
            "Imax": 1.5, "Kp": 0.05, "Kp_cc": 20, "Ki_cc": 5,
            "clearMode": "time", "clearAngle_rad": -np.pi / 3,
            "faultStart_s": 0.2, "faultComplete_s": 0.201,
            "minimumFaultDuration_s": 0.5, "recoveryStart_s": 1,
            "recoveryComplete_s": 1.001, "faultVoltage": 0.5,
            "validationTime_s": 2, "outputStep_s": 1e-4,
            "residualTolerance": 1e-4, "clearingState": "delta",
        }
        p.update(overrides or {})
        p["wBase"] = 2 * np.pi * p["frequency_Hz"]
        p["Lg"] = 1 / (p["SCR"] * np.sqrt(1 + p["rho"]**2))
        p["Rg"] = p["rho"] * p["Lg"]
        p["breakpoints_s"] = [p["faultStart_s"], p["faultComplete_s"]]
        p["breakpoints_s"] += (
            [p["recoveryStart_s"], p["recoveryComplete_s"]]
            if p["clearMode"] == "time"
            else [p["faultStart_s"] + p["minimumFaultDuration_s"]]
        )
        return p

    def __init__(self, p: dict[str, Any]) -> None:
        vsg = GFM_A_C_L(p["Vbase"], p["Sbase"], "vsg")
        for name in ("Lf", "Rv", "Lv", "Rg", "Lg", "Imax", "Kp", "Kp_cc", "Ki_cc"):
            vsg.p[name]["num"] = p[name]

        source = Infbus(p["Vbase"], p["Sbase"], "grid")
        refs = {
            str(vsg.uref[0]): p["Pref"],
            str(vsg.uref[1]): p["Vref"],
            str(vsg.uref[2]): p["wref"],
            str(source.uref[0]): lambda t: self.voltageReference(t, p),
        }
        devices = {
            "Vdev": [source], "Idev": [vsg],
            "vsg": vsg, "source": source,
        }
        # There is one physical node and no explicit branch. Rg/Lg live in
        # GFM_A_C_L, including the line-inductor transient, and reconstruct
        # the converter-side PCC.
        network = {
            "A": np.empty((1, 0)), "R": [], "L": [],
            "busNames": ["Infinite bus"],
        }
        base = {
            "Vbase": p["Vbase"], "Sbase": p["Sbase"],
            "frequency_Hz": p["frequency_Hz"],
        }
        super().__init__(type(self).__name__, network, devices, base, refs)
        self.solverSettings = {
            "method": "RK45",
            "max_step": 5e-3 / (2 * np.pi * self.base["frequency_Hz"]),
            "rtol": 1e-3,
            "atol": 1e-5,
        }
        self.parameters = p
        self.parameterNames = list(p)
        self.clearingState = p["clearingState"]
        self.eventName = "faultClearing"
        self.eventTime_s = p["recoveryStart_s"]
        if p["clearMode"] == "angle":
            self.eventTime_s = np.inf
            self.eventStartTime_s = (
                p["faultStart_s"] + p["minimumFaultDuration_s"]
            )
        self.eventStateIndex = self.stateNames.index(
            f"{self.clearingState}{self.devices['vsg'].index}"
        )

    def voltageReference(self, t: float, p: dict[str, Any]) -> float:
        fallDuration = max(
            p["faultComplete_s"] - p["faultStart_s"], np.finfo(float).eps,
        )
        riseDuration = max(
            p["recoveryComplete_s"] - p["recoveryStart_s"],
            np.finfo(float).eps,
        )
        fall = min(1.0, max(0.0, (t - p["faultStart_s"]) / fallDuration))
        rise = min(1.0, max(0.0, (t - self.eventTime_s) / riseDuration))
        return 1 - (1 - p["faultVoltage"]) * fall + (1 - p["faultVoltage"]) * rise

    def eventHandler(self, _time_s: float, state: np.ndarray) -> float:
        return float(np.sin(
            (state[self.eventStateIndex] - self.parameters["clearAngle_rad"]) / 2
        ))

    def calculateSignals(self, time_s: Any, state: Any, net: dict[str, Any]):
        time_s, state = np.asarray(time_s), np.asarray(state)
        signals = self.busSignals(net, [0], 0)
        vsg = self.devices["vsg"]

        def states(*names):
            indices = [
                self.stateNames.index(f"{name}{vsg.index}") for name in names
            ]
            return state[:, indices]

        current = states("iLd", "iLq")
        reference = states("irefd", "irefq")
        theta = states("theta")[:, 0]
        delta = states("delta")[:, 0]
        grid = net["busVoltage"][:, 0]
        gridD = grid.real * np.cos(theta) + grid.imag * np.sin(theta)
        gridQ = -grid.real * np.sin(theta) + grid.imag * np.cos(theta)
        wColumn = self.referenceNames.index(str(vsg.uref[2]))
        w = net["referenceTrace"][:, wColumn]
        gridSideD = (
            gridD + vsg.p["Rg"]["num"] * current[:, 0]
            - w * vsg.p["Lg"]["num"] * current[:, 1]
        )
        gridSideQ = (
            gridQ + vsg.p["Rg"]["num"] * current[:, 1]
            + w * vsg.p["Lg"]["num"] * current[:, 0]
        )

        referenceMagnitude = np.hypot(reference[:, 0], reference[:, 1])
        limitedReference = reference * np.minimum(
            1,
            vsg.p["Imax"]["num"]
            / np.maximum(referenceMagnitude, np.finfo(float).eps),
        )[:, None]
        controllerVoltage = (
            vsg.p["Kp_cc"]["num"] * (limitedReference - current)
            + vsg.p["Ki_cc"]["num"] * states("xccd", "xccq")
        )
        currentDerivative = (
            controllerVoltage
            - 0.5 * np.column_stack((gridSideD, gridSideQ))
        ) / (vsg.p["Lf"]["num"] + 0.5 * vsg.p["Lg"]["num"])
        vd = gridSideD + vsg.p["Lg"]["num"] * currentDerivative[:, 0]
        vq = gridSideQ + vsg.p["Lg"]["num"] * currentDerivative[:, 1]
        signals.update({
            "pccVoltage": np.hypot(vd, vq),
            "gridVoltage": np.abs(grid),
            "vd": vd,
            "vq": vq,
            "activePower": (
                vd * current[:, 0] + vq * current[:, 1]
            )[:, None],
            "reactivePower": (
                vq * current[:, 0] - vd * current[:, 1]
            )[:, None],
            "irefDQ": limitedReference,
            "filterCurrentMagnitude": np.hypot(
                current[:, 0], current[:, 1],
            ),
            "delta": (delta + np.pi) % (2 * np.pi) - np.pi,
            "dot_delta": np.zeros_like(delta),
        })
        if time_s.size > 1:
            signals["dot_delta"] = np.gradient(np.unwrap(delta), time_s)
        return signals
