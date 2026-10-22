"""Defaults and construction for all migrated CodeSim systems."""

from typing import Any

import numpy as np

from ..systems import (CIGREMV14System, GFLLVRTSystem, HybridSystem,
                       IEEE13System, ParallelVSGSystem, SGSMIBSystem,
                       VSGSMIBAVCSystem, VSGSMIBSystem)


class SystemFactory:
    systemNames = ["HybridSystem", "VSGSMIBSystem", "VSGSMIBAVCSystem", "GFLLVRTSystem",
                   "ParallelVSGSystem", "SGSMIBSystem", "IEEE13System", "CIGREMV14System"]

    @classmethod
    def create(cls, systemName: str, parameters: dict[str, Any] | None = None,
               options: dict[str, Any] | None = None):
        parameters, options = cls.defaultParameters(systemName, parameters or {}, options or {})
        return cls.createSystem(systemName, parameters, options), parameters, options

    @staticmethod
    def createSystem(name, p, options):
        classes = {
            "HybridSystem": lambda: HybridSystem(p, EnableGFL=options["EnableGFL"]),
            "VSGSMIBSystem": lambda: VSGSMIBSystem(p, DeviceModel=options["DeviceModel"], ClearingState=options["ClearingState"]),
            "VSGSMIBAVCSystem": lambda: VSGSMIBAVCSystem(p, ClearingState=options["ClearingState"]),
            "GFLLVRTSystem": lambda: GFLLVRTSystem(p),
            "ParallelVSGSystem": lambda: ParallelVSGSystem(p),
            "SGSMIBSystem": lambda: SGSMIBSystem(p),
            "IEEE13System": lambda: IEEE13System(p, EnableConverters=options["EnableConverters"]),
            "CIGREMV14System": lambda: CIGREMV14System(p),
        }
        return classes[name]()

    @staticmethod
    def linearVoltage(t, times, values):
        return float(np.interp(t, times, values, right=1))

    @classmethod
    def defaultParameters(cls, name, supplied, inputOptions):
        options = {
            "RunTimeDomain": True, "RunSmallSignal": True, "RunInteractionAnalysis": False,
            "StartTime_s": 0.0, "EndTime_s": None, "OutputStep_s": None,
            "MaxStep_s": None, "ResidualTolerance": None, "Breakpoints_s": None,
            "DeviceModel": "VSGCC", "ClearingState": "theta", "EnableGFL": True,
            "EnableConverters": False, "FaultMode": None,
        }
        options.update(inputOptions)
        defaults = {
            "HybridSystem": {
                "Vbase": 1, "Sbase": 25e6, "vsgSbase": 5e6, "gflSbase": 1.5e6, "frequency_Hz": 50,
                "gflPref": 1, "gflQref": 0, "gflVref": 1, "vsgPref": 1, "vsgVref": 1.10,
                "vsgImax": 1.5, "wref": 1, "vsgRv": 0.1, "vsgLv": 0.3, "vsgLf": 0.07,
                "vsgKpApc": 0.05, "vsgKpCc": 20, "vsgKiCc": 5, "gflLf": 0.07,
                "gflKpCc": 0.3, "gflKiCc": 1, "gflKpPll": 0.2, "gflKiPll": 0.02,
                "gflKpP": 0.02, "gflKiP": 0.02, "gflKpQ": 0.02, "gflKiQ": 0.02,
                "gflKq": 0.05, "validationTime_s": 1, "faultStart_s": 0.10,
                "faultEnd_s": 0.5, "faultTransition_s": 1e-3, "faultVoltage": 0.25, "SCR": 1.69, "rho": 1.0,
            },
            "VSGSMIBSystem": {
                "Vbase": 1, "Sbase": 8100, "frequency_Hz": 50, "SCR": 2, "rho": 0.1,
                "Pref": 1, "Vref": 1.1, "wref": 1, "clearMode": "time", "clearAngle_rad": -np.pi / 3,
                "clearTime_s": 1, "faultStart_s": 0.2, "minimumFaultDuration_s": 0.5,
                "faultVoltage_pu": 0.5, "voltageRamp_s": 0.001, "validationTime_s": 2,
            },
            "VSGSMIBAVCSystem": {
                "Vbase": 1, "Sbase": 8100, "frequency_Hz": 50, "SCR": 2, "rho": 0.1,
                "Pref": 1, "Vref": 1.1, "wref": 1, "clearMode": "time", "clearAngle_rad": -np.pi / 3,
                "clearTime_s": 1, "faultStart_s": 0.2, "minimumFaultDuration_s": 0.5,
                "faultVoltage_pu": 0.5, "voltageRamp_s": 0.001, "validationTime_s": 2,
            },
            "GFLLVRTSystem": {
                "SCR": 10, "rho": 0.25, "Pref": 1, "Qref": 0.1, "frequency_Hz": 50,
                "validationTime_s": 1, "faultStart_s": 0.3, "faultComplete_s": 0.301,
                "recoveryStart_s": 0.6, "recoveryComplete_s": 0.601, "faultVoltage": 0.5,
            },
            "ParallelVSGSystem": {
                "Vbase": 1, "Sbase": 8100, "frequency_Hz": 50, "Pref": [0.3, 0.3],
                "Vref": [1.1, 1.1], "wref": [1, 1], "branchL": [0.3, 0.3], "branchR": [0.1, 0.1],
                "validationTime_s": 0.4, "faultStart_s": 0.10, "faultComplete_s": 0.101,
                "recoveryStart_s": 0.20, "recoveryComplete_s": 0.201, "faultVoltage": 0.9,
            },
            "SGSMIBSystem": {
                "Vbase": 1, "Sbase": 8100, "frequency_Hz": 50, "SCR": 2, "rho": 0.25,
                "Ka": 0.5, "Vf0": 1.0, "Vdref": 1.2812, "validationTime_s": 0.4,
                "faultStart_s": 0.10, "faultComplete_s": 0.101, "recoveryStart_s": 0.20,
                "recoveryComplete_s": 0.201, "faultVoltage": 0.2,
            },
            "IEEE13System": {
                "Sbase_VA": 5e6, "Vbase_LL_V": 4.16e3, "frequency_Hz": 50, "validationTime_s": 0.5,
                "faultStartTime_s": 0.10, "faultCompleteTime_s": 0.101,
                "recoveryStartTime_s": 0.20, "recoveryCompleteTime_s": 0.201, "faultVoltage": 0.8,
            },
            "CIGREMV14System": {
                "Sbase_VA": 25e6, "VbaseLL_V": 20e3, "frequency_Hz": 50, "VSGSbase_VA": 5e6,
                "GFLSbase_VA": 1.5e6, "GFLPref": 1, "GFLQref": 0,
                "GFLLf": 0.07, "GFLKpCc": 0.3, "GFLKiCc": 1,
                "GFLKpPll": 0.2, "GFLKiPll": 0.02,
                "GFLKpP": 0.02, "GFLKiP": 0.02, "GFLKpQ": 0.02, "GFLKiQ": 0.02,
                "VSGPref": 1, "VSGVref": 1.1, "VSGwref": 1, "faultStartAngle_s": 0.20,
                "angleClearEligible_s": 0.25, "angleClearLower_rad": -np.pi / 3,
                "angleClearUpper_rad": 0, "angleFaultVoltage_pu": 0, "fixedFaultStart_s": 0.10,
                "fixedFaultComplete_s": 0.101, "fixedClearStart_s": 0.25, "fixedClearComplete_s": 0.2501,
                "fixedFaultVoltage_pu": 0.1, "validationTime_s": 1, "outputStep_s": 1e-4, "maximumStep_tau": 2e-3,
            },
        }
        p = defaults[name]
        if name == "IEEE13System" and options["EnableConverters"]:
            p.update({"Vbase": 4.16e3, "Sbase_Dev": 1e6, "GFMwref": 1, "GFMPref": 1, "GFMVref": 1.1,
                      "gflBusNames": ["645", "671"], "gflPref": [0.5, 0.5], "gflQref": [0, 0],
                      "gflKpPll": 0.2, "gflKiPll": 0.2, "gfl671Vth": 0.92, "gfl671K1": 1.0,
                      "bus671ActiveZFraction": 0.65, "bus671LineRScale": 0.5, "bus645Gd": 0.1,
                      "switchResistance_pu": 5e-5, "validationTime_s": 0.3, "faultVoltage": 0.5})
        p.update(supplied)
        if options["EndTime_s"] is not None:
            p["validationTime_s"] = options["EndTime_s"]
        p["wBase"] = 2 * np.pi * p["frequency_Hz"]
        if name in ("HybridSystem", "VSGSMIBSystem", "VSGSMIBAVCSystem", "GFLLVRTSystem", "SGSMIBSystem"):
            p["Lg"] = 1 / (p["SCR"] * np.sqrt(1 + p["rho"]**2)); p["Rg"] = p["rho"] * p["Lg"]
        if name == "HybridSystem":
            p["branchL"], p["branchR"] = p["Lg"], p["Rg"]
            eventTime = [0, p["faultStart_s"], p["faultStart_s"] + p["faultTransition_s"], p["faultEnd_s"],
                         p["faultEnd_s"] + p["faultTransition_s"], p["validationTime_s"]]
            if not p.get("gridVoltage"):
                p["gridVoltage"] = lambda t, times=eventTime, values=[1, 1, p["faultVoltage"], p["faultVoltage"], 1, 1]: cls.linearVoltage(t, times, values)
            outputStep, maxStep, tolerance = 2e-3, 5e-3 / p["wBase"], 1e-4
        elif name in ("VSGSMIBSystem", "VSGSMIBAVCSystem"):
            if options["FaultMode"] is None: options["FaultMode"] = p["clearMode"]
            else: p["clearMode"] = options["FaultMode"]
            eventTime = [p["faultStart_s"], p["faultStart_s"] + p["voltageRamp_s"],
                         p["faultStart_s"] + p["minimumFaultDuration_s"], p["clearTime_s"], p["clearTime_s"] + p["voltageRamp_s"]]
            outputStep, maxStep, tolerance = 1e-4, 5e-3 / p["wBase"], 1e-4
        elif name in ("GFLLVRTSystem", "ParallelVSGSystem", "SGSMIBSystem"):
            eventTime = [0, p["faultStart_s"], p["faultComplete_s"], p["recoveryStart_s"], p["recoveryComplete_s"], p["validationTime_s"]]
            if not p.get("gridVoltage"):
                p["gridVoltage"] = lambda t, times=eventTime, values=[1, 1, p["faultVoltage"], p["faultVoltage"], 1, 1]: cls.linearVoltage(t, times, values)
            outputStep = 5e-4 if name == "GFLLVRTSystem" else 2e-3
            maxStep = (0.5e-4 if name == "GFLLVRTSystem" else 5e-3) / p["wBase"]
            tolerance = 1e-3 if name == "GFLLVRTSystem" else 1e-7 if name == "SGSMIBSystem" else 1e-4
        elif name == "IEEE13System":
            p["Zbase_ohm"] = p.get("Vbase", p["Vbase_LL_V"])**2 / p["Sbase_VA"]
            eventTime = [0, p["faultStartTime_s"], p["faultCompleteTime_s"], p["recoveryStartTime_s"], p["recoveryCompleteTime_s"], p["validationTime_s"]]
            if not p.get("infbusVoltage"):
                p["infbusVoltage"] = lambda t, times=eventTime, values=[1, 1, p["faultVoltage"], p["faultVoltage"], 1, 1]: cls.linearVoltage(t, times, values)
            outputStep, maxStep, tolerance = 1e-3 / p["wBase"], 1e-3 / p["wBase"], 1e-4
        else:
            if options["OutputStep_s"] is not None: p["outputStep_s"] = options["OutputStep_s"]
            if options["MaxStep_s"] is not None: p["maximumStep_tau"] = options["MaxStep_s"] * p["wBase"]
            eventTime, outputStep, maxStep, tolerance = [], p["outputStep_s"], p["maximumStep_tau"] / p["wBase"], 1e-4
        options["FaultMode"] = options["FaultMode"] or "time"
        options["EndTime_s"] = p["validationTime_s"] if options["EndTime_s"] is None else options["EndTime_s"]
        options["OutputStep_s"] = outputStep if options["OutputStep_s"] is None else options["OutputStep_s"]
        options["MaxStep_s"] = maxStep if options["MaxStep_s"] is None else options["MaxStep_s"]
        options["ResidualTolerance"] = tolerance if options["ResidualTolerance"] is None else options["ResidualTolerance"]
        options["Breakpoints_s"] = eventTime if options["Breakpoints_s"] is None else options["Breakpoints_s"]
        return p, options
