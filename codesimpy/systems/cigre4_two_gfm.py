"""Two identical adaptive-VI GFMs on the CIGRE GFM/GFL corridor, optionally R/X-matched."""

import numpy as np

from ..components import Capacitor, GFMAVI, Infbus, ZeroCurrent
from ..core import System
from .cigre_mv14_system import CIGREMV14System
from .hybrid_gfm_gfl_system import HybridGFMGFLSystem
from .hybrid_gfmavi_gfl_system import HybridGFMAVIGFLSystem


class ParallelGFMAVISystem(System):
    """:class:`HybridGFMAVIGFLSystem` with the bus-7 GFL replaced by a second ``GFMAVI``.

    Topology: infinite bus -- upstream equivalent -- bus 8 -- 7--8 line -- bus 7.
    ``gfm1`` connects at bus 8 and embeds the 8--9 line, as in
    :class:`HybridGFMAVIGFLSystem`. ``gfm2`` is an identical device (same base,
    parameters, references and embedded line) connected at bus 7. Bus 7 and bus 8
    keep their line-charging capacitors.

    ``matchRX`` makes every series impedance proportional to the grid impedance
    ``Z_g`` (upstream equivalent seen from bus 8), the condition of Lemma 1/2
    (slides 14-15). With ``matchRX=True`` the defaults change to:

    * ``GFMRf = rx * GFMLf`` (rx = R/X of ``Z_g``), so the converter filter has the
      grid R/X; ``kVI``/``thetaVI`` follow (circular-CLC choice);
    * ``lineRX = rx``: the 7--8 and 8--9 lines get the grid R/X at constant |Z|;
    * ``GFMaviLaw = 2`` (hard CLC): the virtual impedance is exactly zero below
      ``Imax``. The smooth law 1 adds a static, current-dependent impedance even at
      nominal current, which is not proportional to ``Z_g(s)``;
    * ``GFMCf = 0.01`` (GFM base): moves the Lf--C resonance far above the EMT band;
    * ``lineCScale = 0.01``: the line-charging shunts are not part of ``Z_g``/``Z_M``, so
      they are reduced to make the network as close to homogeneous R/X as possible.

    Each of these can be overridden. With ``matchRX=False`` all values are those of
    :class:`HybridGFMAVIGFLSystem` (CIGRE line R/X, ``Rf = Lf``, law 1, ``Cf = 0.1``).

    ``lineCScale`` multiplies all line-charging capacitances (the bus-7/bus-8 shunts and the
    bus-9 share inside the GFMs); 1 keeps the CIGRE values.

    ``gfm2Connected=False`` replaces ``gfm2`` by ``ZeroCurrent`` (bus 7 and the 7--8
    line stay, unloaded), the disconnection test of case 4.
    """

    @staticmethod
    def gridRX(p):
        _, R, L, _, _ = HybridGFMGFLSystem.buildReducedNetwork(
            p.get("upstreamScale", 1.0), p.get("upstreamRX"))
        return float(R[0] / L[0])

    @staticmethod
    def defaultParameters(overrides=None):
        overrides = dict(overrides or {})
        overrides.setdefault("matchRX", True)
        overrides.setdefault("gfm2Connected", True)
        overrides.setdefault("gflModel", "GFLVSCNoOuterLoop")   # unused; keeps the parent defaults valid
        if overrides["matchRX"]:
            rx = ParallelGFMAVISystem.gridRX(overrides)
            overrides.setdefault("GFMRf", rx * overrides.get("GFMLf", 0.1))
            overrides.setdefault("lineRX", rx)
            overrides.setdefault("GFMaviLaw", 2)
            overrides.setdefault("GFMCf", 0.01)
            overrides.setdefault("lineCScale", 0.01)
        overrides.setdefault("lineRX", None)
        overrides.setdefault("lineCScale", 1.0)
        return HybridGFMAVIGFLSystem.defaultParameters(overrides)

    @staticmethod
    def setRX(R, L, rx):
        """Same |Z| with R/X = ``rx``."""
        magnitude = np.hypot(R, L)
        L = magnitude / np.hypot(rx, 1.0)
        return rx * L, L

    def __init__(self, p):
        incidence, branchR, branchL, busNames, busCapacitance = (
            HybridGFMGFLSystem.buildReducedNetwork(p.get("upstreamScale", 1.0), p.get("upstreamRX"))
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
            gfm = GFMAVI(1, p["VSGSbase_VA"], name)
            for parameter, value in (
                ("C", busCapacitance[lineNode] / toGFM + p["GFMCf"]),
                ("Rg", lineR * toGFM), ("Lg", lineL * toGFM),
                ("Rf", p["GFMRf"]), ("Lf", p["GFMLf"]), ("Kp", p["GFMKp"]), ("Imax", p["GFMImax"]),
                ("aviLaw", p["GFMaviLaw"]), ("Ith", p["GFMIth"]), ("kVI", p["GFMkVI"]),
                ("thetaVI", p["GFMthetaVI"]),
            ):
                gfm.p[parameter]["num"] = value
            return gfm

        gfm1 = buildGFM("parallel_avi_gfm1_bus8")
        gfm2 = buildGFM("parallel_avi_gfm2_bus7") if p["gfm2Connected"] else None
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
            "ParallelGFMAVISystem", network, devices,
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
        return CIGREMV14System.sourceVoltage(self, time_s, p)

    def eventHandler(self, time_s, state):
        return CIGREMV14System.eventHandler(self, time_s, state)

    def gfmSignals(self, gfm, state):
        """Per-GFM signals on the GFM base (see :meth:`HybridGFMAVIGFLSystem.calculateSignals`)."""
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
