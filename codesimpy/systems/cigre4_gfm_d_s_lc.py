"""CIGRE4__GFM_D_S_LC__GFL_C_F_LC: four-node CIGRE reduction with the smooth-CLC GFM and both filter capacitors."""

import numpy as np

from ..components import Capacitor, GFL_C_F_L, GFM_D_S_LC, Infbus, ZeroCurrent
from ..core import System
from .cigre14 import _CIGRE14, buildGFL
from .cigre4_gfm_a_c_lc import _CIGRE4GFMAdmittance


class CIGRE4__GFM_D_S_LC__GFL_C_F_LC(System):
    """CIGRE4 · GFM_D_S_LC + GFL_C_F_LC.

    GFM_D_S_LC (internal voltage directly behind Rf + jLf, smooth circular CLC
    Phi(r) = r / tanh(r / Imax) - Imax on the unlimited current, Z_VI = Phi (Rf + jLf)/Imax by default) is
    connected at bus 8 through the 8--9 line, which it embeds, with its filter capacitor ``gfmFilterC``
    (default 0.1 pu, GFM base) plus the bus-9 line capacitance. GFL_C_F_L (current references, FRT current
    priority) is at bus 7 with its filter capacitor ``gflFilterC`` (default 0.068 pu, GFL base) plus the
    bus-7 line capacitance. Both filter capacitors must be > 0.

    Options: ``gridImpedanceScale``, ``gridRX`` (upstream equivalent, as in CIGRE4__GFM_A_C_LC__GFL_C_F_L);
    GFM ``GFMRf``, ``GFMLf``, ``GFMKp``, ``GFMImax``, ``GFMkVI``/``GFMthetaVI`` (``None``: kVI = |Rf + jLf| / Imax,
    thetaVI = atan2(Lf, Rf)); references ``VSGPref``, ``VSGVref`` (internal EMF magnitude), ``VSGwref``.
    """

    @staticmethod
    def defaultParameters(overrides=None):
        overrides = dict(overrides or {})
        for name, value in (
            ("gridImpedanceScale", 1.0), ("gridRX", None),
            ("GFMRf", 0.1), ("GFMLf", 0.1), ("GFMKp", 0.05), ("GFMImax", 1.5),
            ("GFMkVI", None), ("GFMthetaVI", None),
            ("gfmFilterC", 0.1), ("gflFilterC", 0.068),
        ):
            overrides.setdefault(name, value)
        p = _CIGRE14.defaultParameters(overrides)
        for name in ("gfmFilterC", "gflFilterC"):
            if not p[name] > 0:
                raise ValueError(f"CIGRE4__GFM_D_S_LC__GFL_C_F_LC needs {name} > 0 (both units include their filter capacitor)")
        if p["GFMkVI"] is None:
            p["GFMkVI"] = float(np.hypot(p["GFMRf"], p["GFMLf"]) / p["GFMImax"])
        if p["GFMthetaVI"] is None:
            p["GFMthetaVI"] = float(np.arctan2(p["GFMLf"], p["GFMRf"]))
        return p

    def __init__(self, p):
        incidence, branchR, branchL, busNames, busCapacitance = (
            _CIGRE4GFMAdmittance.buildReducedNetwork(p["gridImpedanceScale"], p["gridRX"])
        )
        # Drop bus 9 and the 8--9 branch (index 2); GFM_D_S_LC embeds both.
        sourceNode, gflNode, middleNode, gfmNode = range(4)
        toGFM = p["VSGSbase_VA"] / p["Sbase_VA"]          # impedance: system pu -> GFM pu
        lineR, lineL = branchR[2], branchL[2]
        incidence, branchR, branchL = incidence[:3, :2], branchR[:2], branchL[:2]
        busNames = busNames[:3]

        source = Infbus(1, p["Sbase_VA"], "hybrid_avi_infbus")
        source.p["kA"]["num"] = 100
        bus7 = Capacitor(1, p["Sbase_VA"], "hybrid_avi_bus7_lineC")
        bus8 = Capacitor(1, p["Sbase_VA"], "hybrid_avi_bus8_lineC")
        gflFilterC = p["gflFilterC"] * p["GFLSbase_VA"] / p["Sbase_VA"]   # GFL pu -> system pu
        for capacitor, node, extra in ((bus7, gflNode, gflFilterC), (bus8, middleNode, 0.0)):
            capacitor.p["C"]["num"] = busCapacitance[node] + extra
            capacitor.p["Gd"]["num"] = 0
            capacitor.p["w"]["num"] = 1

        gfl, gflReferences = buildGFL(p, "hybrid_avi_gfl_bus7", GFL_C_F_L)

        gfm = GFM_D_S_LC(1, p["VSGSbase_VA"], "hybrid_avi_gfm_bus9")
        for name, value in (
            ("C", busCapacitance[gfmNode] / toGFM + p["gfmFilterC"]), ("Rg", lineR * toGFM), ("Lg", lineL * toGFM),
            ("Rf", p["GFMRf"]), ("Lf", p["GFMLf"]), ("Kp", p["GFMKp"]), ("Imax", p["GFMImax"]),
            ("kVI", p["GFMkVI"]),
            ("thetaVI", p["GFMthetaVI"]),
        ):
            gfm.p[name]["num"] = value

        voltageDevices = [source, bus7, bus8]
        currentDevices = [
            ZeroCurrent(1, p["Sbase_VA"], "hybrid_avi_infbus_zero"),
            gfl,
            gfm,
        ]
        clearingTime_s = np.inf if p["clearMode"] == "angle" else p["recoveryStart_s"]
        references = {
            str(source.uref[0]): lambda t: self.sourceVoltage(t, p),
            str(gfl.uref[0]): gflReferences[0],
            str(gfl.uref[1]): gflReferences[1],
            str(gfm.uref[0]): p["VSGPref"],
            str(gfm.uref[1]): p["VSGVref"],
            str(gfm.uref[2]): p["VSGwref"],
        }
        devices = {
            "Vdev": voltageDevices, "Idev": currentDevices,
            "source": source, "gfl": gfl, "gfm": gfm, "vsg": gfm,
        }
        network = {"A": incidence, "R": branchR, "L": branchL, "busNames": busNames}
        super().__init__(
            type(self).__name__, network, devices,
            {"Vbase": 1, "Sbase": p["Sbase_VA"], "frequency_Hz": p["frequency_Hz"]},
            references,
        )
        self.solverSettings["max_step"] = p["maximumStep_tau"] / (2 * np.pi * p["frequency_Hz"])
        self.parameters, self.parameterNames = p, list(p)
        self.busCapacitance = busCapacitance[:3]
        self.gfmBusCapacitance = busCapacitance[gfmNode]
        self.qssRequiredSlowStateNames = []   # GFL_C_F_L has no outer-loop integrators
        self.eventName = "faultClearing"
        self.eventDirection = 1
        self.eventTime_s = clearingTime_s
        if p["clearMode"] == "angle":
            self.eventStartTime_s = p["angleClearEligible_s"]
        self.eventStateIndex = self.stateNames.index(f"delta{gfm.index}")

    def sourceVoltage(self, time_s, p):
        return _CIGRE14.sourceVoltage(self, time_s, p)

    def eventHandler(self, time_s, state):
        return _CIGRE14.eventHandler(self, time_s, state)

    def calculateSignals(self, time_s, state, networkSignals):
        """Bus signals plus the GFM quantities on the GFM base.

        ``unlimitedCurrentMagnitude`` is ``|(E - v_C) / (Rf + j Lf)|``, the input of
        the circular CLC (laws 1, 2); ``filterCurrentMagnitude`` is ``|i_ref|``.
        ``virtualResistance``/``virtualReactance`` are the adaptive VI components.
        """
        time_s, state = np.asarray(time_s), np.asarray(state)
        signals = self.busSignals(networkSignals, np.arange(self.rlGrid.n), 0)
        gfm, p = self.devices["gfm"], self.parameters
        column = lambda name: state[:, self.stateNames.index(f"{name}{gfm.index}")]
        vc = np.column_stack((column("vCd"), column("vCq")))
        iref = np.column_stack((column("iRefd"), column("iRefq")))
        ig = np.column_stack((column("iGd"), column("iGq")))
        delta = column("delta")
        rf, lf = gfm.p["Rf"]["num"], gfm.p["Lf"]["num"]
        error = p["VSGVref"] * np.column_stack((np.cos(delta), np.sin(delta))) - vc
        unlimited = np.linalg.solve(np.array([[rf, -lf], [lf, rf]]), error.T).T
        unlimitedMagnitude = np.hypot(unlimited[:, 0], unlimited[:, 1])
        filterMagnitude = np.hypot(iref[:, 0], iref[:, 1])
        limiterInput = filterMagnitude if int(gfm.p["aviLaw"]["num"]) == 0 else unlimitedMagnitude
        gain = gfm.p["kVI"]["num"] * gfm.viGain(np.maximum(limiterInput, 1e-12), symbolic=False)
        signals.update({
            "gfmPccVoltage": np.hypot(vc[:, 0], vc[:, 1]),
            "irefDQ": iref, "gridCurrentDQ": ig,
            "filterCurrentMagnitude": filterMagnitude,
            "unlimitedCurrentMagnitude": unlimitedMagnitude,
            "gridCurrentMagnitude": np.hypot(ig[:, 0], ig[:, 1]),
            "virtualResistance": gain * np.cos(gfm.p["thetaVI"]["num"]),
            "virtualReactance": gain * np.sin(gfm.p["thetaVI"]["num"]),
            "gfmActivePower": np.sum(vc * ig, axis=1),
            "delta": (delta + np.pi) % (2 * np.pi) - np.pi,
        })
        return signals
