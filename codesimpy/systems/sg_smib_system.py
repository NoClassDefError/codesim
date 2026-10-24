"""Synchronous generator connected to an infinite bus."""

from time import perf_counter

import numpy as np
from scipy.optimize import least_squares

from ..components import Capacitor, Infbus, SG, ZeroCurrent
from ..core import System


class SGSMIBSystem(System):
    def __init__(self, p):
        sg = SG(p["Vbase"], p["Sbase"], "1")
        sg.p["Ka"]["num"], sg.p["Vf0"]["num"] = p["Ka"], p["Vf0"]
        capacitor = Capacitor(p["Vbase"], p["Sbase"], "2")
        source = Infbus(p["Vbase"], p["Sbase"], "4")
        devices = {"Vdev": [capacitor, source],
                   "Idev": [sg, ZeroCurrent(p["Vbase"], p["Sbase"], "3")],
                   "sg": sg, "capacitor": capacitor, "source": source}
        refs = {str(sg.uref[0]): 0.0, str(sg.uref[1]): p["Vdref"], str(sg.uref[2]): 0.0,
                str(sg.uref[3]): 1.0, str(source.uref[0]): p["gridVoltage"]}
        network = {"A": np.array([[1.0], [-1.0]]), "R": [p["Rg"]], "L": [p["Lg"]],
                   "busNames": ["SG PCC", "Infinite bus"]}
        super().__init__("SGSMIBSystem", network, devices,
                         {"Vbase": p["Vbase"], "Sbase": p["Sbase"], "frequency_Hz": p["frequency_Hz"]}, refs)
        self.solverSettings["max_step"] = 5e-3 / (2 * np.pi * p["frequency_Hz"])
        self.parameters, self.parameterNames = p, list(p)

    def initialize(self, time_s=0.0, *, Reference=None, ResidualTolerance=1e-4):
        reference = self.getReference(time_s) if Reference is None else np.asarray(Reference, dtype=float)
        self.rlGrid.refreshParameters()
        started = perf_counter()
        dynamic = np.array(["theta" not in name for name in self.stateNames])
        speed = self.stateNames.index("w_1")
        solution = least_squares(
            lambda state: np.r_[self.rlGrid.f_numeric(state, reference)[dynamic],
                                state[speed] - self.devices["source"].p["w0"]["num"]],
            np.ones(len(self.stateNames)), method="trf", max_nfev=100_000,
            ftol=1e-10, xtol=1e-10, gtol=1e-10,
        )
        residual = np.r_[self.rlGrid.f_numeric(solution.x, reference)[dynamic],
                         solution.x[speed] - self.devices["source"].p["w0"]["num"]]
        info = {"exitflag": 1 if solution.success else -1,
                "output": {"message": solution.message, "nfev": solution.nfev},
                "residualInfNorm": float(np.linalg.norm(residual, np.inf))}
        if info["exitflag"] <= 0 or info["residualInfNorm"] >= ResidualTolerance:
            raise RuntimeError(f"initialization failed: exitflag={info['exitflag']}, residual={info['residualInfNorm']:.3e}")
        return {"state": np.real(solution.x), "reference": np.asarray(reference), "time_s": float(time_s),
                "initialization": info, "initializationTime_s": perf_counter() - started}

    def calculateSignals(self, time_s, state, networkSignals):
        signals = self.busSignals(networkSignals, np.arange(self.rlGrid.n), self.rlGrid.n - 1)
        idx = [self.stateNames.index(str(symbol)) for symbol in self.devices["sg"].x]
        signals["lineCurrentMagnitude"] = np.abs(networkSignals["branchCurrent"])
        signals["sgSpeed"] = np.asarray(state)[:, idx[7]]
        return signals
