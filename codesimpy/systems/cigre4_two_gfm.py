"""CIGRE4 and CIGRE4RX with two direct CLC GFMs (Lemma 1/2, tier C).

``CIGRE4__GFM_D_S_LC__GFM_D_S_LC``, ``CIGRE4__GFM_D_S_LC`` (second GFM removed),
``CIGRE4RX__GFM_D_H_LC__GFM_D_H_LC`` and ``CIGRE4RX__GFM_D_H_LC`` (second GFM removed).
"""

import numpy as np

from ..components import Capacitor, GFM_D_H_LC, GFM_D_S_LC, Infbus, ZeroCurrent
from ..core import System
from .cigre14 import _CIGRE14
from .cigre4_gfm_a_c_lc import _CIGRE4GFMAdmittance
from .cigre4_gfm_d_s_lc import CIGRE4__GFM_D_S_LC__GFL_C_F_LC


class _CIGRE4TwoGFM(System):
    """``CIGRE4__GFM_D_S_LC__GFL_C_F_LC`` with the bus-7 GFL replaced by a second, identical GFM.

    Topology: infinite bus -- upstream equivalent -- bus 8 -- 7--8 line -- bus 7. ``gfm1`` connects at
    bus 8 and embeds the 8--9 line; ``gfm2`` is an identical device (same base, parameters, references and
    embedded line) at bus 7. Bus 7 and bus 8 keep their line-charging capacitors. With ``SECOND = False``
    ``gfm2`` is replaced by ``ZeroCurrent`` (bus 7 and the 7--8 line stay, unloaded; case 4).

    ``MATCHED`` (network ``CIGRE4RX``) makes every series impedance proportional to the grid impedance
    ``Z_g`` (upstream equivalent seen from bus 8), the condition of Lemma 1/2 (slides 14-15). Its defaults:
    ``GFMRf = rx * GFMLf`` (rx = R/X of ``Z_g``; kVI/thetaVI follow), ``lineRX = rx`` (7--8 and 8--9 lines
    at the grid R/X, constant |Z|), ``gfmFilterC = 0.01`` (moves the Lf--C resonance above the EMT band) and
    ``lineCScale = 0.01`` (line charging is not part of Z_g/Z_M). The matched GFM is the hard CLC
    (GFM_D_H_LC): its virtual impedance is exactly zero below Imax, whereas the smooth law adds a static,
    current-dependent impedance at any current. Unmatched (``CIGRE4``): CIGRE line R/X, ``Rf = Lf``,
    smooth CLC (GFM_D_S_LC), ``gfmFilterC = 0.1``, ``lineCScale = 1``. All numeric defaults can be overridden.
    """
    DEVICE = GFM_D_S_LC
    MATCHED = False
    SECOND = True

    @staticmethod
    def gridRX(p):
        _, R, L, _, _ = _CIGRE4GFMAdmittance.buildReducedNetwork(
            p.get("gridImpedanceScale", 1.0), p.get("gridRX"))
        return float(R[0] / L[0])

    @classmethod
    def defaultParameters(cls, overrides=None):
        overrides = dict(overrides or {})
        if cls.MATCHED:
            rx = cls.gridRX(overrides)
            overrides.setdefault("GFMRf", rx * overrides.get("GFMLf", 0.1))
            overrides.setdefault("lineRX", rx)
            overrides.setdefault("gfmFilterC", 0.01)
            overrides.setdefault("lineCScale", 0.01)
        overrides.setdefault("lineRX", None)
        overrides.setdefault("lineCScale", 1.0)
        return CIGRE4__GFM_D_S_LC__GFL_C_F_LC.defaultParameters(overrides)

    @staticmethod
    def setRX(R, L, rx):
        """Same |Z| with R/X = ``rx``."""
        magnitude = np.hypot(R, L)
        L = magnitude / np.hypot(rx, 1.0)
        return rx * L, L

    def __init__(self, p):
        incidence, branchR, branchL, busNames, busCapacitance = (
            _CIGRE4GFMAdmittance.buildReducedNetwork(p["gridImpedanceScale"], p["gridRX"])
        )
        branchR, branchL = branchR.copy(), branchL.copy()
        busCapacitance = busCapacitance * p["lineCScale"]
        if p["lineRX"] is not None:
            for branch in (1, 2):
                branchR[branch], branchL[branch] = self.setRX(branchR[branch], branchL[branch], p["lineRX"])
        _, gfm2Node, gfm1Node, lineNode = range(4)
        toGFM = p["VSGSbase_VA"] / p["Sbase_VA"]          # impedance: system pu -> GFM pu
        lineR, lineL = branchR[2], branchL[2]
        incidence, branchR, branchL = incidence[:3, :2], branchR[:2], branchL[:2]
        busNames = busNames[:3]
        self.lineImpedance = {"upstream": (branchR[0], branchL[0]), "7-8": (branchR[1], branchL[1]),
                              "8-9": (lineR, lineL)}

        source = Infbus(1, p["Sbase_VA"], "parallel_avi_infbus")
        source.p["kA"]["num"] = 100
        bus7 = Capacitor(1, p["Sbase_VA"], "parallel_avi_bus7_lineC")
        bus8 = Capacitor(1, p["Sbase_VA"], "parallel_avi_bus8_lineC")
        for capacitor, node in ((bus7, gfm2Node), (bus8, gfm1Node)):
            capacitor.p["C"]["num"] = busCapacitance[node]
            capacitor.p["Gd"]["num"] = 0
            capacitor.p["w"]["num"] = 1

        def buildGFM(name):
            gfm = self.DEVICE(1, p["VSGSbase_VA"], name)
            for parameter, value in (
                ("C", busCapacitance[lineNode] / toGFM + p["gfmFilterC"]),
                ("Rg", lineR * toGFM), ("Lg", lineL * toGFM),
                ("Rf", p["GFMRf"]), ("Lf", p["GFMLf"]), ("Kp", p["GFMKp"]), ("Imax", p["GFMImax"]),
                ("kVI", p["GFMkVI"]),
                ("thetaVI", p["GFMthetaVI"]),
            ):
                gfm.p[parameter]["num"] = value
            return gfm

        gfm1 = buildGFM("parallel_avi_gfm1_bus8")
        gfm2 = buildGFM("parallel_avi_gfm2_bus7") if self.SECOND else None
        references = {str(source.uref[0]): lambda t: self.sourceVoltage(t, p)}
        for gfm in (gfm1, gfm2):
            if gfm is not None:
                for symbol, value in zip(gfm.uref, (p["VSGPref"], p["VSGVref"], p["VSGwref"])):
                    references[str(symbol)] = value

        currentDevices = [
            ZeroCurrent(1, p["Sbase_VA"], "parallel_avi_infbus_zero"),
            gfm2 if gfm2 is not None else ZeroCurrent(1, p["Sbase_VA"], "parallel_avi_bus7_zero"),
            gfm1,
        ]
        devices = {
            "Vdev": [source, bus7, bus8], "Idev": currentDevices,
            "source": source, "gfm1": gfm1, "gfm2": gfm2, "gfm": gfm1, "vsg": gfm1,
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
        self.qssRequiredSlowStateNames = []
        self.eventName = "faultClearing"
        self.eventDirection = 1
        self.eventTime_s = np.inf if p["clearMode"] == "angle" else p["recoveryStart_s"]
        if p["clearMode"] == "angle":
            self.eventStartTime_s = p["angleClearEligible_s"]
        self.eventStateIndex = self.stateNames.index(f"delta{gfm1.index}")

    def sourceVoltage(self, time_s, p):
        return _CIGRE14.sourceVoltage(self, time_s, p)

    def eventHandler(self, time_s, state):
        return _CIGRE14.eventHandler(self, time_s, state)

    def gfmSignals(self, gfm, state):
        """Per-GFM signals on the GFM base (see :meth:`CIGRE4__GFM_D_S_LC__GFL_C_F_LC.calculateSignals`)."""
        column = lambda name: state[:, self.stateNames.index(f"{name}{gfm.index}")]
        vc = np.column_stack((column("vCd"), column("vCq")))
        iref = np.column_stack((column("iRefd"), column("iRefq")))
        ig = np.column_stack((column("iGd"), column("iGq")))
        delta = column("delta")
        rf, lf = gfm.p["Rf"]["num"], gfm.p["Lf"]["num"]
        error = self.parameters["VSGVref"] * np.column_stack((np.cos(delta), np.sin(delta))) - vc
        unlimited = np.linalg.solve(np.array([[rf, -lf], [lf, rf]]), error.T).T
        return {
            "filterCurrentMagnitude": np.hypot(iref[:, 0], iref[:, 1]),
            "unlimitedCurrentMagnitude": np.hypot(unlimited[:, 0], unlimited[:, 1]),
            "gridCurrentMagnitude": np.hypot(ig[:, 0], ig[:, 1]),
            "gfmActivePower": np.sum(vc * ig, axis=1),
            "delta": (delta + np.pi) % (2 * np.pi) - np.pi,
        }

    def calculateSignals(self, time_s, state, networkSignals):
        """Bus signals plus, per GFM, the signals of :meth:`gfmSignals` as ``(n, nGFM)``
        columns in the order (gfm1, gfm2)."""
        state = np.asarray(state)
        signals = self.busSignals(networkSignals, np.arange(self.rlGrid.n), 0)
        gfms = [self.devices[key] for key in ("gfm1", "gfm2") if self.devices[key] is not None]
        perGFM = [self.gfmSignals(gfm, state) for gfm in gfms]
        for key in perGFM[0]:
            signals[key] = np.column_stack([item[key] for item in perGFM])
        signals["gfmNames"] = [key for key in ("gfm1", "gfm2") if self.devices[key] is not None]
        return signals


class CIGRE4__GFM_D_S_LC__GFM_D_S_LC(_CIGRE4TwoGFM):
    """CIGRE4 · two GFM_D_S_LC (direct, smooth circular CLC, LC filter): gfm1 at bus 8 (through the 8--9 line),
    gfm2 at bus 7. CIGRE line R/X, not impedance-matched (tier C, "2GFM-unmatched")."""
    DEVICE, MATCHED, SECOND = GFM_D_S_LC, False, True


class CIGRE4__GFM_D_S_LC(_CIGRE4TwoGFM):
    """CIGRE4 · one GFM_D_S_LC at bus 8; bus 7 and the 7--8 line stay, unloaded (tier C, the unmatched case with
    GFM2 removed)."""
    DEVICE, MATCHED, SECOND = GFM_D_S_LC, False, False


class CIGRE4RX__GFM_D_H_LC__GFM_D_H_LC(_CIGRE4TwoGFM):
    """CIGRE4RX · two GFM_D_H_LC (direct, hard circular CLC, LC filter) on the R/X-matched corridor: every series
    impedance (filter Rf + jLf, 7--8 and 8--9 lines) has the grid R/X, line charging reduced (tier C, "2GFM-matched")."""
    DEVICE, MATCHED, SECOND = GFM_D_H_LC, True, True


class CIGRE4RX__GFM_D_H_LC(_CIGRE4TwoGFM):
    """CIGRE4RX · one GFM_D_H_LC at bus 8 on the R/X-matched corridor; bus 7 and the 7--8 line stay, unloaded
    (tier C, the matched case with GFM2 removed)."""
    DEVICE, MATCHED, SECOND = GFM_D_H_LC, True, False
