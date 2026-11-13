"""CIGRE4__GFM_D_L_L__GFL_C_F_L: four-node CIGRE reduction with the direct linear-AVI GFM (no capacitor) and a GFL."""

import numpy as np

from ..components import Capacitor, GFL_C_F_L, GFM_D_L_L, Infbus, ZeroCurrent
from ..core import System
from .cigre14 import _CIGRE14, buildGFL
from .cigre4_gfm_a_c_lc import _CIGRE4GFMAdmittance


class CIGRE4__GFM_D_L_L__GFL_C_F_L(System):
    """CIGRE4 · GFM_D_L_L at bus 8 (through the embedded 8--9 line; internal voltage directly behind Rf + jLf,
    linear adaptive virtual impedance kVI max(0, |i_M| - Ith) e^(j thetaVI), no terminal capacitor) + GFL_C_F_L at
    bus 7 (current references, FRT current priority, PLL; bus-7 line capacitance only).

    Topology: infinite bus -- upstream equivalent -- bus 8 -- 7--8 line -- bus 7, with the line-charging
    capacitors of buses 7 and 8. Bus 9 is not a node: GFM_D_L_L embeds the 8--9 line, and its line-charging share
    is dropped. This is the slide's network: i_g = Y_g (v_t - v_g), i_M + i_L = i_g, v_M = v_t + Z_1 i_M (8--9
    line), the GFL measuring at bus 7 behind Z_2 (7--8 line).

    RMS model (:meth:`System.simulateRMS`): delta (GFM) and the PLL (theta, xPLL) are differential, every other
    state is algebraic.

    Options: ``gridImpedanceScale``, ``gridRX`` (upstream equivalent); GFM (GFM base) ``GFMRf``, ``GFMLf``,
    ``GFMKp``, ``GFMIth``, ``GFMkVI``, ``GFMthetaVI``, ``GFMImax``; references ``VSGPref``, ``VSGVref`` (internal EMF
    magnitude), ``VSGwref``; the GFL and fault options of :class:`_CIGRE14`.
    """

    @staticmethod
    def defaultParameters(overrides=None):
        overrides = dict(overrides or {})
        for name, value in (
            ("gridImpedanceScale", 1.0), ("gridRX", None),
            ("GFMRf", 0.1), ("GFMLf", 0.1), ("GFMKp", 0.05), ("GFMIth", 1.1),
            ("GFMkVI", 2.0), ("GFMthetaVI", 0.0), ("GFMImax", 1.5),
        ):
            overrides.setdefault(name, value)
        return _CIGRE14.defaultParameters(overrides)

    def __init__(self, p):
        incidence, branchR, branchL, busNames, busCapacitance = (
            _CIGRE4GFMAdmittance.buildReducedNetwork(p["gridImpedanceScale"], p["gridRX"])
        )
        _, bus7Node, bus8Node, _ = range(4)
        toGFM = p["VSGSbase_VA"] / p["Sbase_VA"]          # impedance: system pu -> GFM pu
        lineR, lineL = branchR[2], branchL[2]
        # Drop bus 9 and the 8--9 branch (index 2); GFM_D_L_L embeds the line.
        incidence, branchR, branchL = incidence[:3, :2], branchR[:2], branchL[:2]
        busNames = busNames[:3]
        self.lineImpedance = {"upstream": (branchR[0], branchL[0]), "7-8": (branchR[1], branchL[1]),
                              "8-9": (lineR, lineL)}

        source = Infbus(1, p["Sbase_VA"], "c4dll_infbus")
        source.p["kA"]["num"] = 100
        bus7 = Capacitor(1, p["Sbase_VA"], "c4dll_bus7_lineC")
        bus8 = Capacitor(1, p["Sbase_VA"], "c4dll_bus8_lineC")
        for capacitor, node in ((bus7, bus7Node), (bus8, bus8Node)):
            capacitor.p["C"]["num"] = busCapacitance[node]
            capacitor.p["Gd"]["num"] = 0
            capacitor.p["w"]["num"] = 1

        gfm = GFM_D_L_L(1, p["VSGSbase_VA"], "c4dll_gfm_bus8")
        for name, value in (
            ("Rg", lineR * toGFM), ("Lg", lineL * toGFM),
            ("Rf", p["GFMRf"]), ("Lf", p["GFMLf"]), ("Kp", p["GFMKp"]), ("Ith", p["GFMIth"]),
            ("kVI", p["GFMkVI"]), ("thetaVI", p["GFMthetaVI"]), ("Imax", p["GFMImax"]),
        ):
            gfm.p[name]["num"] = value
        gfl, gflReferences = buildGFL(p, "c4dll_gfl_bus7", GFL_C_F_L)

        references = {str(source.uref[0]): lambda t: self.sourceVoltage(t, p)}
        for symbol, value in zip(gfm.uref, (p["VSGPref"], p["VSGVref"], p["VSGwref"])):
            references[str(symbol)] = value
        for symbol, value in zip(gfl.uref, gflReferences):
            references[str(symbol)] = value

        currentDevices = [ZeroCurrent(1, p["Sbase_VA"], "c4dll_infbus_zero"), gfl, gfm]
        devices = {
            "Vdev": [source, bus7, bus8], "Idev": currentDevices,
            "source": source, "gfm": gfm, "gfl": gfl, "vsg": gfm,
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
        self.eventStateIndex = self.stateNames.index(f"delta{gfm.index}")

    def sourceVoltage(self, time_s, p):
        return _CIGRE14.sourceVoltage(self, time_s, p)

    def eventHandler(self, time_s, state):
        return _CIGRE14.eventHandler(self, time_s, state)

    def calculateSignals(self, time_s, state, networkSignals):
        """Bus signals plus frame-invariant converter signals (valid for EMT and RMS states).

        GFM (GFM base): ``gfmCurrentMagnitude`` |i_M|, ``gfmActivePower``/``gfmReactivePower`` at v_M (quasi-static
        v_M = v_t + (Rg + jLg) i_M), ``virtualResistance``/``virtualReactance``, ``delta`` (wrapped) and
        ``gfmAngle`` = delta + theta_GFM - theta_grid. GFL (GFL base): ``gflCurrentMagnitude``, ``gflVoltage``
        (measured |v|), ``pllFrequency_pu``, ``pllAngle`` = theta_PLL - theta_grid, ``frtMode`` (0 normal, 1 FRT).
        """
        state = np.asarray(state)
        signals = self.busSignals(networkSignals, np.arange(self.rlGrid.n), 0)
        gfm, gfl, source = self.devices["gfm"], self.devices["gfl"], self.devices["source"]
        column = lambda device, name: state[:, self.stateNames.index(f"{name}{device.index}")]
        wrap = lambda angle: (angle + np.pi) % (2 * np.pi) - np.pi
        thetaGrid = column(source, "theta")
        voltage = networkSignals["busVoltage"]

        num = lambda name: gfm.p[name]["num"]
        iM = column(gfm, "iMd") + 1j * column(gfm, "iMq")
        thetaM, delta = column(gfm, "theta"), column(gfm, "delta")
        vt = voltage[:, 2] * np.exp(-1j * thetaM) * gfm.Inputscale
        vM = vt + (num("Rg") + 1j * num("Lg")) * iM
        sM = vM * np.conj(iM)
        gain = gfm.virtualImpedanceGain(np.abs(iM), symbolic=False)

        g = lambda name: gfl.p[name]["num"]
        iL = column(gfl, "id") + 1j * column(gfl, "iq")
        thetaL, xPLL = column(gfl, "theta"), column(gfl, "xPLL")
        vL = voltage[:, 1] * np.exp(-1j * thetaL) * gfl.Inputscale + (g("Rg") + 1j * g("w0") * g("Lg")) * iL
        wPLL = np.clip(g("w0") + g("KpPll") * vL.imag + g("KiPll") * xPLL, g("wPllMin"), g("wPllMax"))
        signals.update({
            "gfmCurrentMagnitude": np.abs(iM), "gfmActivePower": sM.real, "gfmReactivePower": sM.imag,
            "gfmTerminalVoltage": np.abs(vM),
            "virtualResistance": gain * np.cos(num("thetaVI")), "virtualReactance": gain * np.sin(num("thetaVI")),
            "delta": wrap(delta), "gfmAngle": wrap(delta + thetaM - thetaGrid),
            "gflCurrentMagnitude": np.abs(iL), "gflVoltage": np.abs(vL),
            "pllFrequency_pu": wPLL, "pllAngle": wrap(thetaL - thetaGrid),
            "frtMode": (1 + np.tanh(50 * (g("Vth") - np.abs(vL)))) / 2,
        })
        return signals
