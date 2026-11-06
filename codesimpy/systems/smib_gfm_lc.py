"""Single grid-forming converter connected to an infinite bus."""

from typing import Any

import numpy as np
from scipy.integrate import cumulative_trapezoid

from ..components import Infbus, VSGCC, VSGCCAVC, VSGCL, ZeroCurrent
from ..core import System


class VSGSMIBSystem(System):
    @staticmethod
    def defaultParameters(overrides=None):
        p = {
            "Vbase": 1, "Sbase": 8100, "frequency_Hz": 50, "SCR": 2,
            "rho": 0.1, "Pref": 1, "Vref": 1.1, "wref": 1,
            "clearMode": "time", "clearAngle_rad": -np.pi / 3,
            "faultStart_s": 0.2, "faultComplete_s": 0.201,
            "minimumFaultDuration_s": 0.5, "recoveryStart_s": 1,
            "recoveryComplete_s": 1.001, "faultVoltage": 0.5,
            "validationTime_s": 2, "Rv": 0.05,
            "outputStep_s": 1e-4, "residualTolerance": 1e-4,
            "deviceModel": "VSGCC", "clearingState": "delta",
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
        deviceModel = p["deviceModel"]
        deviceClass = {"VSGCC": VSGCC, "VSGCCAVC": VSGCCAVC, "VSGCL": VSGCL}[deviceModel]
        vsg = deviceClass(p["Vbase"], p["Sbase"], "vsg")
        if "Rv" in vsg.p:
            vsg.p["Rv"]["num"] = p["Rv"]
        if "Kp" in p:
            vsg.p["Kp"]["num"] = p["Kp"]
        if "Lf" in p:
            vsg.p["Lf"]["num"] = p["Lf"]
        source = Infbus(p["Vbase"], p["Sbase"], "grid")
        zeroVsg = ZeroCurrent(p["Vbase"], p["Sbase"], "vsg_zero")
        zeroGrid = ZeroCurrent(p["Vbase"], p["Sbase"], "grid_zero")
        refs = {
            str(vsg.uref[0]): p["Pref"],
            str(vsg.uref[1]): p["Vref"],
            str(vsg.uref[2]): p["wref"],
            str(source.uref[0]): lambda t: self.voltageReference(t, p),
        }
        devices = {
            "Vdev": [vsg, source], "Idev": [zeroVsg, zeroGrid],
            "vsg": vsg, "source": source,
        }
        network = {
            "A": np.array([[1.0], [-1.0]]), "R": np.array([p["Rg"]]),
            "L": np.array([p["Lg"]]),
            "busNames": ["VSG terminal", "Infinite bus"],
        }
        base = {
            "Vbase": p["Vbase"], "Sbase": p["Sbase"],
            "frequency_Hz": p["frequency_Hz"],
        }
        super().__init__(f"VSGSMIBSystem_{deviceModel}", network, devices, base, refs)
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
        fallDuration = max(p["faultComplete_s"] - p["faultStart_s"], np.finfo(float).eps)
        riseDuration = max(p["recoveryComplete_s"] - p["recoveryStart_s"], np.finfo(float).eps)
        fall = min(1.0, max(0.0, (t - p["faultStart_s"]) / fallDuration))
        rise = min(1.0, max(0.0, (t - self.eventTime_s) / riseDuration))
        return 1 - (1 - p["faultVoltage"]) * fall + (1 - p["faultVoltage"]) * rise

    def eventHandler(self, _time_s: float, state: np.ndarray) -> float:
        p = self.parameters
        return float(np.sin(
            (state[self.eventStateIndex] - p["clearAngle_rad"]) / 2
        ))

    def calculateSignals(self, time_s: Any, state: Any, net: dict[str, Any]):
        time_s, state = np.asarray(time_s), np.asarray(state)
        signals = self.busSignals(net, np.arange(self.rlGrid.n), self.rlGrid.n - 1)
        vsg = self.devices["vsg"]
        delta = state[:, self.stateNames.index(f"delta{vsg.index}")]
        inductorIndices = [self.stateNames.index(f"{name}{vsg.index}") for name in ("iLd", "iLq")]
        il = state[:, inductorIndices]
        if isinstance(vsg, VSGCC):
            currentIndices = [self.stateNames.index(f"{name}{vsg.index}") for name in ("irefd", "irefq")]
            current = state[:, currentIndices]
        elif isinstance(vsg, VSGCCAVC):
            capacitorIndices = [self.stateNames.index(f"{name}{vsg.index}") for name in ("vCd", "vCq")]
            controllerIndices = [self.stateNames.index(f"{name}{vsg.index}") for name in ("xavcd", "xavcq")]
            vc, xavc = state[:, capacitorIndices], state[:, controllerIndices]
            vcol = self.referenceNames.index(str(vsg.uref[1]))
            voltageReference = net["referenceTrace"][:, vcol, None]
            target = voltageReference * np.column_stack((np.cos(delta), np.sin(delta)))
            current = vsg.p["Kp_avc"]["num"] * (target - vc) + vsg.p["Ki_avc"]["num"] * xavc
        else:
            capacitorIndices = [self.stateNames.index(f"{name}{vsg.index}") for name in ("vCd", "vCq")]
            vc = state[:, capacitorIndices]
            vcol = self.referenceNames.index(str(vsg.uref[1]))
            wcol = self.referenceNames.index(str(vsg.uref[2]))
            current = np.zeros_like(vc)
            J = np.array([[0.0, 1.0], [-1.0, 0.0]])
            for k in range(state.shape[0]):
                error = net["referenceTrace"][k, vcol] * np.array([np.cos(delta[k]), np.sin(delta[k])]) - vc[k]
                impedance = vsg.p["Rf"]["num"] * np.eye(2) - net["referenceTrace"][k, wcol] * vsg.p["Lf"]["num"] * J
                current[k] = np.linalg.solve(impedance, error)
        magnitude = np.hypot(current[:, 0], current[:, 1])
        signals["irefDQ"] = current * np.minimum(1, vsg.p["Imax"]["num"] / np.maximum(magnitude, np.finfo(float).eps))[:, None]
        signals["filterCurrentMagnitude"] = np.hypot(il[:, 0], il[:, 1])
        signals["delta"] = (delta + np.pi) % (2 * np.pi) - np.pi
        signals["dot_delta"] = np.zeros_like(delta)
        period = 1 / self.base["frequency_Hz"]
        signals["fundamentalPeriod_s"] = period
        signals["busVoltageFundamentalMagnitude"] = np.full(net["busVoltage"].shape, np.nan)
        if time_s.size > 1:
            signals["dot_delta"] = np.gradient(np.unwrap(delta), time_s)
            rotatingVoltage = net["busVoltage"] * np.exp(-1j * 2 * np.pi * self.base["frequency_Hz"] * time_s[:, None])
            integral = cumulative_trapezoid(rotatingVoltage, time_s, axis=0, initial=0)
            delayed = np.column_stack([
                np.interp(time_s - period, time_s, integral[:, column], left=np.nan, right=np.nan)
                for column in range(integral.shape[1])
            ])
            signals["busVoltageFundamentalMagnitude"] = np.abs((integral - delayed) / period)
        return signals
