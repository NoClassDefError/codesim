"""CIGRE GFM/GFL reduction with the adaptive-VI (circular CLC) GFM."""

import numpy as np

from ..components import Capacitor, GFMAVI, Infbus, ZeroCurrent
from ..core import System
from .cigre_mv14_system import CIGREMV14System, buildGFL
from .hybrid_gfm_gfl_system import HybridGFMGFLSystem


class HybridGFMAVIGFLSystem(System):
    """Same corridor as :class:`HybridGFMGFLSystem`, with ``GFMAVI`` instead of ``VSGCC``.

    ``GFMAVI`` is a current device that embeds its PCC capacitor and its grid-side
    branch. It is therefore connected at bus 8: its capacitor is the bus-9 line
    capacitance and its ``Rg``/``Lg`` are the original 8--9 branch, both converted to
    the GFM base. Buses 7 and 8, the upstream equivalent (``upstreamScale``,
    ``upstreamRX``), the GFL, the fault and the clearing logic are unchanged.

    Converter filter capacitors: ``GFMCf`` (GFM base, default 0.1 as in Presentation
    2026-07-07) is added to the bus-9 line capacitance inside ``GFMAVI``; ``GFLCf`` (GFL
    base, default 0.068 as in ``GFLLVRTSystemCapacitor``) is added to the bus-7 line
    capacitance. Both sit at the converter terminal; 0 recovers the line-only model.

    GFM parameters (GFM base): ``GFMRf``, ``GFMLf``, ``GFMKp``, ``GFMImax``,
    ``GFMaviLaw`` (0 linear AVI, 1 smooth circular CLC, 2 hard circular CLC),
    ``GFMIth`` (law 0 only), and ``GFMkVI``/``GFMthetaVI``. When the last two are
    ``None`` they follow the circular-CLC choice ``kVI = |Rf + jLf| / Imax``,
    ``thetaVI = atan2(Lf, Rf)`` (Presentation 2026-07-07). References are
    ``VSGPref``, ``VSGVref`` (internal EMF magnitude) and ``VSGwref``.
    """

    @staticmethod
    def defaultParameters(overrides=None):
        overrides = dict(overrides or {})
        for name, value in (
            ("upstreamScale", 1.0), ("upstreamRX", None),
            ("GFMRf", 0.1), ("GFMLf", 0.1), ("GFMKp", 0.05), ("GFMImax", 1.5),
            ("GFMaviLaw", 1), ("GFMIth", 0.9), ("GFMkVI", None), ("GFMthetaVI", None),
            ("GFMCf", 0.1), ("GFLCf", 0.068),
        ):
            overrides.setdefault(name, value)
        p = CIGREMV14System.defaultParameters(overrides)
        if p["GFMkVI"] is None:
            p["GFMkVI"] = float(np.hypot(p["GFMRf"], p["GFMLf"]) / p["GFMImax"])
        if p["GFMthetaVI"] is None:
            p["GFMthetaVI"] = float(np.arctan2(p["GFMLf"], p["GFMRf"]))
        return p

    def __init__(self, p):
        incidence, branchR, branchL, busNames, busCapacitance = (
            HybridGFMGFLSystem.buildReducedNetwork(p.get("upstreamScale", 1.0), p.get("upstreamRX"))
        )
        # Drop bus 9 and the 8--9 branch (index 2); GFMAVI embeds both.
        sourceNode, gflNode, middleNode, gfmNode = range(4)
        toGFM = p["VSGSbase_VA"] / p["Sbase_VA"]          # impedance: system pu -> GFM pu
        lineR, lineL = branchR[2], branchL[2]
        incidence, branchR, branchL = incidence[:3, :2], branchR[:2], branchL[:2]
        busNames = busNames[:3]

        source = Infbus(1, p["Sbase_VA"], "hybrid_avi_infbus")
        source.p["kA"]["num"] = 100
        bus7 = Capacitor(1, p["Sbase_VA"], "hybrid_avi_bus7_lineC")
        bus8 = Capacitor(1, p["Sbase_VA"], "hybrid_avi_bus8_lineC")
        gflFilterC = p["GFLCf"] * p["GFLSbase_VA"] / p["Sbase_VA"]   # GFL pu -> system pu
        for capacitor, node, extra in ((bus7, gflNode, gflFilterC), (bus8, middleNode, 0.0)):
            capacitor.p["C"]["num"] = busCapacitance[node] + extra
            capacitor.p["Gd"]["num"] = 0
            capacitor.p["w"]["num"] = 1

        gfl, gflReferences = buildGFL(p, "hybrid_avi_gfl_bus7")

        gfm = GFMAVI(1, p["VSGSbase_VA"], "hybrid_avi_gfm_bus9")
        for name, value in (
            ("C", busCapacitance[gfmNode] / toGFM + p["GFMCf"]), ("Rg", lineR * toGFM), ("Lg", lineL * toGFM),
            ("Rf", p["GFMRf"]), ("Lf", p["GFMLf"]), ("Kp", p["GFMKp"]), ("Imax", p["GFMImax"]),
            ("aviLaw", p["GFMaviLaw"]), ("Ith", p["GFMIth"]), ("kVI", p["GFMkVI"]),
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
            "HybridGFMAVIGFLSystem", network, devices,
            {"Vbase": 1, "Sbase": p["Sbase_VA"], "frequency_Hz": p["frequency_Hz"]},
            references,
        )
        self.solverSettings["max_step"] = p["maximumStep_tau"] / (2 * np.pi * p["frequency_Hz"])
        self.parameters, self.parameterNames = p, list(p)
        self.busCapacitance = busCapacitance[:3]
        self.gfmBusCapacitance = busCapacitance[gfmNode]
        self.qssRequiredSlowStateNames = [
            str(gfl.x[4]), str(gfl.x[5]),
        ] if p.get("gflModel", "GFLVSC") == "GFLVSC" else []
        self.eventName = "faultClearing"
        self.eventDirection = 1
        self.eventTime_s = clearingTime_s
        if p["clearMode"] == "angle":
            self.eventStartTime_s = p["angleClearEligible_s"]
        self.eventStateIndex = self.stateNames.index(f"delta{gfm.index}")

    def sourceVoltage(self, time_s, p):
        return CIGREMV14System.sourceVoltage(self, time_s, p)

    def eventHandler(self, time_s, state):
        return CIGREMV14System.eventHandler(self, time_s, state)

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
