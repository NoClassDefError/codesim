"""Single grid-forming converter connected to an infinite bus."""

from time import perf_counter
from typing import Any

import numpy as np
from scipy.integrate import cumulative_trapezoid

from ..components import Infbus, VSGCC, VSGCL, ZeroCurrent
from ..core import System


class VSGSMIBSystem(System):
    def __init__(
        self, p: dict[str, Any], *, DeviceModel: str = "VSGCC",
        ClearingState: str = "delta",
    ) -> None:
        deviceClass = {"VSGCC": VSGCC, "VSGCL": VSGCL}[DeviceModel]
        vsg = deviceClass(p["Vbase"], p["Sbase"], "vsg")
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
        super().__init__(f"VSGSMIBSystem_{DeviceModel}", network, devices, base, refs)
        self.parameters = p
        self.parameterNames = list(p)
        self.clearingState = ClearingState

    @staticmethod
    def voltageReference(t: float, p: dict[str, Any]) -> float:
        fall = min(1.0, max(0.0, (t - p["faultStart_s"]) / p["voltageRamp_s"]))
        rise = min(1.0, max(0.0, (t - p["clearTime_s"]) / p["voltageRamp_s"]))
        return 1 - (1 - p["faultVoltage_pu"]) * fall + (1 - p["faultVoltage_pu"]) * rise

    @staticmethod
    def angleCrossing(
        t: float, a: np.ndarray, nextTime: float, b: np.ndarray,
        eligible: float, index: int, angle: float,
    ) -> float:
        if t < eligible:
            return np.nan
        start, stop = a[index], b[index]
        turn = np.ceil((start - angle) / (2 * np.pi)) if stop >= start else np.floor((start - angle) / (2 * np.pi))
        target = angle + 2 * np.pi * turn
        if start == target:
            return 0.0
        fraction = (target - start) / (stop - start) if stop != start else np.nan
        return float(fraction) if 0 < fraction <= 1 else np.nan

    def simulateFault(
        self, time_s: Any, x0: Any, *, saveSnapshot: bool = True,
    ) -> dict[str, Any]:
        time_s = np.asarray(time_s, dtype=float).reshape(-1)
        p = dict(self.parameters)
        refs = self.getReference()
        sourceIndex = self.referenceNames.index(str(self.devices["source"].uref[0]))
        deltaIndex = self.stateNames.index(f"{self.clearingState}{self.devices['vsg'].index}")
        started = perf_counter()
        self.rlGrid.refreshParameters()
        clearingTime_s = p["clearTime_s"]
        eventFcn = None
        eligible = p["faultStart_s"] + p["minimumFaultDuration_s"]
        if p["clearMode"] == "angle":
            p["clearTime_s"] = np.inf
            refs[sourceIndex] = lambda t: self.voltageReference(t, p)
            eventFcn = lambda t, a, tn, b: self.angleCrossing(
                t, a, tn, b, eligible, deltaIndex, p["clearAngle_rad"]
            )
        breakpoints = [
            p["faultStart_s"], p["faultStart_s"] + p["voltageRamp_s"],
            eligible, p["clearTime_s"], p["clearTime_s"] + p["voltageRamp_s"],
        ]
        state, t, events = self.integrate(
            time_s, x0, refs, 1e-3 / (2 * np.pi * self.base["frequency_Hz"]),
            breakpoints, eventFcn,
        )
        if p["clearMode"] == "angle" and np.size(events["time_s"]):
            clearingTime_s = float(events["time_s"])
            p["clearTime_s"] = clearingTime_s
            refs[sourceIndex] = lambda value: self.voltageReference(value, p)
            remaining = np.unique(np.r_[clearingTime_s, time_s[time_s > clearingTime_s]])
            if remaining.size > 1:
                recovery, recoveryTime, _ = self.integrate(
                    remaining, state[-1], refs,
                    1e-3 / (2 * np.pi * self.base["frequency_Hz"]),
                    [clearingTime_s + p["voltageRamp_s"]], None,
                )
                state = np.vstack((state, recovery[1:]))
                t = np.r_[t, recoveryTime[1:]]
        networkSignals = self.calculateNetworkSignals(t, state, refs)
        signals = self.calculateSignals(t, state, networkSignals)
        result = {
            "time_s": t, "state": state, "stateNames": self.stateNames,
            "signals": signals, "referenceNames": self.referenceNames,
            "referenceTrace": networkSignals["referenceTrace"],
            "initialization": None, "events": events,
            "parameters": self.parameters,
            "simulationTime_s": perf_counter() - started,
            "clearingTime_s": clearingTime_s,
        }
        if saveSnapshot:
            _, result["frontendDescriptor"] = self.outputJsonFactory.saveSnapshot(result)
        return result

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
