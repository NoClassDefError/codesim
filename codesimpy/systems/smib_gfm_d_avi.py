"""SMIB__GFM_D_L_LC, SMIB__GFM_D_S_LC, SMIB__GFM_D_H_LC: direct adaptive-VI GFM on an infinite bus."""

from typing import Any

import numpy as np

from ..components import GFM_D_H_LC, GFM_D_L_LC, GFM_D_S_LC, Infbus
from ..core import System


class _SMIBGFMDirectAVI(System):
    """One-node SMIB with the capacitor and Rg/Lg embedded in the GFM (``DEVICE``)."""
    DEVICE = GFM_D_L_LC

    @staticmethod
    def defaultParameters(overrides=None):
        p = {
            "Vbase": 1, "Sbase": 8100, "frequency_Hz": 50,
            "SCR": 1 / (0.1 * np.sqrt(1.01)), "rho": 0.1,
            "Pref": 0.0, "Vref": 1.0, "wref": 1.0,
            "C": 0.1, "Rf": 0.1, "Lf": 0.1,
            "Ith": 0.9, "kVI": 2.0, "thetaVI": 0.0, "Kp": 0.2,
            "Imax": 1.5,
            "clearMode": "angle", "clearAngle_rad": -np.pi / 3,
            "faultStart_s": 0.2, "faultComplete_s": 0.20001,
            "minimumFaultDuration_s": 0.5,
            "recoveryStart_s": 1.0, "recoveryComplete_s": 1.00001,
            "faultVoltage": 0.0, "validationTime_s": 1.4,
            "outputStep_s": 5e-5, "residualTolerance": 1e-4,
            "clearingState": "delta",
        }
        p.update(overrides or {})
        p["wBase"] = 2 * np.pi * p["frequency_Hz"]
        p["Lg"] = 1 / (p["SCR"] * np.sqrt(1 + p["rho"] ** 2))
        p["Rg"] = p["rho"] * p["Lg"]
        p["breakpoints_s"] = [p["faultStart_s"], p["faultComplete_s"]]
        p["breakpoints_s"] += (
            [p["recoveryStart_s"], p["recoveryComplete_s"]]
            if p["clearMode"] == "time"
            else [p["faultStart_s"] + p["minimumFaultDuration_s"]]
        )
        return p

    def __init__(self, p: dict[str, Any]) -> None:
        gfm = self.DEVICE(p["Vbase"], p["Sbase"], "gfm")
        for name in (
            "C", "Rf", "Lf", "Rg", "Lg", "Ith", "kVI",
            "thetaVI", "Kp", "Imax",
        ):
            gfm.p[name]["num"] = p[name]
        source = Infbus(p["Vbase"], p["Sbase"], "grid")
        refs = {
            str(gfm.uref[0]): p["Pref"],
            str(gfm.uref[1]): p["Vref"],
            str(gfm.uref[2]): p["wref"],
            str(source.uref[0]): lambda t: self.voltageReference(t, p),
        }
        devices = {
            "Vdev": [source], "Idev": [gfm],
            "gfm": gfm, "source": source,
        }
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
            "method": "RK45", "max_step": 1e-4,
            "rtol": 1e-5, "atol": 1e-7,
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
            f"{self.clearingState}{gfm.index}"
        )

    def voltageReference(self, t: float, p: dict[str, Any]) -> float:
        fall_duration = max(
            p["faultComplete_s"] - p["faultStart_s"],
            np.finfo(float).eps,
        )
        rise_duration = max(
            p["recoveryComplete_s"] - p["recoveryStart_s"],
            np.finfo(float).eps,
        )
        fall = min(1.0, max(0.0, (t - p["faultStart_s"]) / fall_duration))
        rise = min(1.0, max(0.0, (t - self.eventTime_s) / rise_duration))
        return 1 - (1 - p["faultVoltage"]) * fall + (1 - p["faultVoltage"]) * rise

    def eventHandler(self, _time_s: float, state: np.ndarray) -> float:
        return float(np.sin(
            (state[self.eventStateIndex] - self.parameters["clearAngle_rad"]) / 2
        ))

    def calculateSignals(self, time_s: Any, state: Any, net: dict[str, Any]):
        time_s, state = np.asarray(time_s), np.asarray(state)
        signals = self.busSignals(net, [0], 0)
        gfm = self.devices["gfm"]

        def states(*names):
            indices = [
                self.stateNames.index(f"{name}{gfm.index}") for name in names
            ]
            return state[:, indices]

        vc = states("vCd", "vCq")
        iref = states("iRefd", "iRefq")
        ig = states("iGd", "iGq")
        delta = states("delta")[:, 0]
        magnitude = np.hypot(iref[:, 0], iref[:, 1])
        limiter_magnitude = magnitude
        if int(gfm.p["aviLaw"]["num"]) in (1, 2):
            internal_voltage = self.parameters["Vref"] * np.column_stack((
                np.cos(delta), np.sin(delta),
            ))
            error = internal_voltage - vc
            impedance = np.array([
                [gfm.p["Rf"]["num"], -gfm.p["Lf"]["num"]],
                [gfm.p["Lf"]["num"], gfm.p["Rf"]["num"]],
            ])
            unlimited = np.linalg.solve(impedance, error.T).T
            limiter_magnitude = np.hypot(unlimited[:, 0], unlimited[:, 1])
        excess = gfm.viGain(
            np.maximum(limiter_magnitude, 1e-12), symbolic=False,
        )
        virtual_magnitude = gfm.p["kVI"]["num"] * excess
        signals.update({
            "pccVoltage": np.hypot(vc[:, 0], vc[:, 1]),
            "gridVoltage": np.abs(net["busVoltage"][:, 0]),
            "vd": vc[:, 0], "vq": vc[:, 1],
            "irefDQ": iref, "gridCurrentDQ": ig,
            "filterCurrentMagnitude": magnitude,
            "limiterCurrentMagnitude": limiter_magnitude,
            "gridCurrentMagnitude": np.hypot(ig[:, 0], ig[:, 1]),
            "adaptiveExcess": excess,
            "virtualResistance": virtual_magnitude * np.cos(gfm.p["thetaVI"]["num"]),
            "virtualInductance": virtual_magnitude * np.sin(gfm.p["thetaVI"]["num"]),
            "activePower": vc[:, 0] * ig[:, 0] + vc[:, 1] * ig[:, 1],
            "reactivePower": vc[:, 1] * ig[:, 0] - vc[:, 0] * ig[:, 1],
            "delta": (delta + np.pi) % (2 * np.pi) - np.pi,
            "dot_delta": np.zeros_like(delta),
        })
        if time_s.size > 1:
            signals["dot_delta"] = np.gradient(np.unwrap(delta), time_s)
        return signals


class SMIB__GFM_D_L_LC(_SMIBGFMDirectAVI):
    """SMIB · GFM_D_L_LC: internal voltage directly behind Rf + jLf, linear adaptive virtual impedance
    Z_VI = kVI max(0, |i_ref| - Ith) e^(j thetaVI); terminal capacitor and grid branch in the device."""
    DEVICE = GFM_D_L_LC


class _SMIBCircularCLC(_SMIBGFMDirectAVI):
    """Circular CLC: kVI and thetaVI default to |Rf + jLf| / Imax and atan2(Lf, Rf), so Z_VI = Phi (Rf + jLf)/Imax."""

    @staticmethod
    def defaultParameters(overrides=None):
        overrides = dict(overrides or {})
        rf, lf, imax = overrides.get("Rf", 0.1), overrides.get("Lf", 0.1), overrides.get("Imax", 1.5)
        overrides.setdefault("kVI", float(np.hypot(rf, lf) / imax))
        overrides.setdefault("thetaVI", float(np.arctan2(lf, rf)))
        return _SMIBGFMDirectAVI.defaultParameters(overrides)


class SMIB__GFM_D_S_LC(_SMIBCircularCLC):
    """SMIB · GFM_D_S_LC: as SMIB__GFM_D_L_LC with the smooth circular CLC, Phi(r) = r / tanh(r / Imax) - Imax
    on the unlimited current (Presentation 2026-07-07, slide 1)."""
    DEVICE = GFM_D_S_LC


class SMIB__GFM_D_H_LC(_SMIBCircularCLC):
    """SMIB · GFM_D_H_LC: as SMIB__GFM_D_L_LC with the hard circular CLC, max(0, r - Imax) (slide 2)."""
    DEVICE = GFM_D_H_LC
