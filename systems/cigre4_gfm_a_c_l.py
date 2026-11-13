"""CIGRE4 and CIGRE4RX with the no-capacitor admittance GFM ``GFM_A_C_L`` (Lemma 1/2, tier C).

``CIGRE4__GFM_A_C_L__GFL_C_F_L``, ``CIGRE4__GFM_A_C_L__GFM_A_C_L``, ``CIGRE4__GFM_A_C_L`` (second unit
removed), ``CIGRE4RX__GFM_A_C_L__GFM_A_C_L`` and ``CIGRE4RX__GFM_A_C_L`` (second GFM removed).
"""

import numpy as np

from ..components import Capacitor, GFL_C_F_L, GFM_A_C_L, Infbus, ZeroCurrent
from ..core import System
from .cigre14 import _CIGRE14, buildGFL
from .cigre4_gfm_a_c_lc import _CIGRE4GFMAdmittance


class _CIGRE4GFMAdmittanceL(System):
    """Four-node CIGRE corridor with ``GFM_A_C_L`` at bus 8 and a second unit at bus 7.

    Topology: infinite bus -- upstream equivalent -- bus 8 -- 7--8 line -- bus 7. ``gfm1`` (GFM_A_C_L:
    virtual admittance Rv + jLv, current PI on the filter Lf, circular limit on the current reference, no
    terminal capacitor) connects at bus 8 and embeds the 8--9 line as its Rg/Lg. Bus 9 is therefore not a
    node and its line-charging share is dropped (GFM_A_C_L has no capacitor). The bus-7 unit is ``BUS7``:
    ``"GFL"`` (GFL_C_F_L, current references with FRT current priority), ``"GFM"`` (``gfm2``, a GFM_A_C_L
    identical to gfm1: same base, parameters, references and embedded line) or ``None`` (ZeroCurrent: bus 7
    and the 7--8 line stay, unloaded; case 4). Buses 7 and 8 keep their line-charging capacitors.

    With frozen delta and an ideal current loop the GFM output impedance seen from bus 8 is
    ``Rv + Lv (s + J) + Rg + Lg (s + J)``, an RL impedance. ``MATCHED`` (network ``CIGRE4RX``) makes it, and the
    7--8 line, proportional to the grid impedance ``Z_g`` (upstream equivalent seen from bus 8), the condition of
    Lemma 1/2 (slides 14-15). Its defaults: ``GFMRv = rx * GFMLv`` (rx = R/X of ``Z_g``), ``lineRX = rx``
    (7--8 and 8--9 lines at the grid R/X, constant |Z|) and ``lineCScale = 0.01`` (line charging is not part of
    Z_g/Z_M). Unmatched (``CIGRE4``): ``GFMRv = 0.1``, ``GFMLv = 0.3``, CIGRE line R/X, ``lineCScale = 1``.

    GFM options (GFM base): ``GFMRv``, ``GFMLv``, ``GFMLf``, ``GFMKp``, ``GFMImax``, ``GFMKpCc``, ``GFMKiCc``;
    references ``VSGPref``, ``VSGVref`` (internal EMF magnitude), ``VSGwref``. Network: ``gridImpedanceScale``,
    ``gridRX`` (upstream equivalent), ``lineRX``, ``lineCScale``. All numeric defaults can be overridden.
    """
    BUS7 = "GFL"
    MATCHED = False

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
            overrides.setdefault("GFMRv", rx * overrides.get("GFMLv", 0.3))
            overrides.setdefault("lineRX", rx)
            overrides.setdefault("lineCScale", 0.01)
        for name, value in (
            ("gridImpedanceScale", 1.0), ("gridRX", None), ("lineRX", None), ("lineCScale", 1.0),
            ("GFMRv", 0.1), ("GFMLv", 0.3), ("GFMLf", 0.07), ("GFMKp", 0.05), ("GFMImax", 1.5),
            ("GFMKpCc", 20.0), ("GFMKiCc", 5.0),
        ):
            overrides.setdefault(name, value)
        return _CIGRE14.defaultParameters(overrides)

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
        _, bus7Node, bus8Node, _ = range(4)
        toGFM = p["VSGSbase_VA"] / p["Sbase_VA"]          # impedance: system pu -> GFM pu
        lineR, lineL = branchR[2], branchL[2]
        # Drop bus 9 and the 8--9 branch (index 2); GFM_A_C_L embeds the line.
        incidence, branchR, branchL = incidence[:3, :2], branchR[:2], branchL[:2]
        busNames = busNames[:3]
        self.lineImpedance = {"upstream": (branchR[0], branchL[0]), "7-8": (branchR[1], branchL[1]),
                              "8-9": (lineR, lineL)}

        source = Infbus(1, p["Sbase_VA"], "cigre4l_infbus")
        source.p["kA"]["num"] = 100
        bus7 = Capacitor(1, p["Sbase_VA"], "cigre4l_bus7_lineC")
        bus8 = Capacitor(1, p["Sbase_VA"], "cigre4l_bus8_lineC")
        for capacitor, node in ((bus7, bus7Node), (bus8, bus8Node)):
            capacitor.p["C"]["num"] = busCapacitance[node]
            capacitor.p["Gd"]["num"] = 0
            capacitor.p["w"]["num"] = 1

        def buildGFM(name):
            gfm = GFM_A_C_L(1, p["VSGSbase_VA"], name)
            for parameter, value in (
                ("Rg", lineR * toGFM), ("Lg", lineL * toGFM),
                ("Rv", p["GFMRv"]), ("Lv", p["GFMLv"]), ("Lf", p["GFMLf"]), ("Kp", p["GFMKp"]),
                ("Imax", p["GFMImax"]), ("Kp_cc", p["GFMKpCc"]), ("Ki_cc", p["GFMKiCc"]),
            ):
                gfm.p[parameter]["num"] = value
            return gfm

        gfm1 = buildGFM("cigre4l_gfm1_bus8")
        gfm2 = buildGFM("cigre4l_gfm2_bus7") if self.BUS7 == "GFM" else None
        gfl, gflReferences = (buildGFL(p, "cigre4l_gfl_bus7", GFL_C_F_L) if self.BUS7 == "GFL"
                              else (None, None))
        references = {str(source.uref[0]): lambda t: self.sourceVoltage(t, p)}
        for gfm in (gfm1, gfm2):
            if gfm is not None:
                for symbol, value in zip(gfm.uref, (p["VSGPref"], p["VSGVref"], p["VSGwref"])):
                    references[str(symbol)] = value
        if gfl is not None:
            for symbol, value in zip(gfl.uref, gflReferences):
                references[str(symbol)] = value

        bus7Device = gfm2 or gfl or ZeroCurrent(1, p["Sbase_VA"], "cigre4l_bus7_zero")
        currentDevices = [ZeroCurrent(1, p["Sbase_VA"], "cigre4l_infbus_zero"), bus7Device, gfm1]
        devices = {
            "Vdev": [source, bus7, bus8], "Idev": currentDevices,
            "source": source, "gfm1": gfm1, "gfm2": gfm2, "gfl": gfl, "gfm": gfm1, "vsg": gfm1,
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
        self.qssRequiredSlowStateNames = []   # GFL_C_F_L has no outer-loop integrators
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
        """Per-GFM signals on the GFM base. ``unlimitedCurrentMagnitude`` is ``|i_ref|``, the input of the
        circular limit; ``filterCurrentMagnitude`` is the filter (= grid) current ``|i_L|``."""
        column = lambda name: state[:, self.stateNames.index(f"{name}{gfm.index}")]
        delta = column("delta")
        return {
            "unlimitedCurrentMagnitude": np.hypot(column("irefd"), column("irefq")),
            "filterCurrentMagnitude": np.hypot(column("iLd"), column("iLq")),
            "delta": (delta + np.pi) % (2 * np.pi) - np.pi,
        }

    def calculateSignals(self, time_s, state, networkSignals):
        """Bus signals plus, per GFM, the signals of :meth:`gfmSignals` as ``(n, nGFM)`` columns in the
        order (gfm1, gfm2)."""
        state = np.asarray(state)
        signals = self.busSignals(networkSignals, np.arange(self.rlGrid.n), 0)
        gfms = [self.devices[key] for key in ("gfm1", "gfm2") if self.devices[key] is not None]
        perGFM = [self.gfmSignals(gfm, state) for gfm in gfms]
        for key in perGFM[0]:
            signals[key] = np.column_stack([item[key] for item in perGFM])
        signals["gfmNames"] = [key for key in ("gfm1", "gfm2") if self.devices[key] is not None]
        return signals


class CIGRE4__GFM_A_C_L__GFL_C_F_L(_CIGRE4GFMAdmittanceL):
    """CIGRE4 · GFM_A_C_L at bus 8 (through the embedded 8--9 line; virtual admittance + current PI, circular
    current-reference limit, no terminal capacitor) + GFL_C_F_L at bus 7 (current references, FRT current
    priority; bus-7 line capacitance only). CIGRE line R/X, not impedance-matched (tier C, "GFM+GFL")."""
    BUS7, MATCHED = "GFL", False


class CIGRE4__GFM_A_C_L__GFM_A_C_L(_CIGRE4GFMAdmittanceL):
    """CIGRE4 · two identical GFM_A_C_L: gfm1 at bus 8 (through the 8--9 line), gfm2 at bus 7. CIGRE line R/X,
    not impedance-matched (tier C, "2GFM-unmatched")."""
    BUS7, MATCHED = "GFM", False


class CIGRE4__GFM_A_C_L(_CIGRE4GFMAdmittanceL):
    """CIGRE4 · one GFM_A_C_L at bus 8; bus 7 and the 7--8 line stay, unloaded (tier C, the unmatched case with
    GFM2 removed)."""
    BUS7, MATCHED = None, False


class CIGRE4RX__GFM_A_C_L__GFM_A_C_L(_CIGRE4GFMAdmittanceL):
    """CIGRE4RX · two identical GFM_A_C_L on the R/X-matched corridor: the virtual impedance Rv + jLv and the
    7--8 and 8--9 lines have the grid R/X, line charging reduced (tier C, "2GFM-matched")."""
    BUS7, MATCHED = "GFM", True


class CIGRE4RX__GFM_A_C_L(_CIGRE4GFMAdmittanceL):
    """CIGRE4RX · one GFM_A_C_L at bus 8 on the R/X-matched corridor; bus 7 and the 7--8 line stay, unloaded
    (tier C, the matched case with GFM2 removed)."""
    BUS7, MATCHED = None, True
