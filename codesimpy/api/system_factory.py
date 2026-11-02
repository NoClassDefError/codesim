"""Defaults and construction for all migrated CodeSim systems."""

from typing import Any

import numpy as np

from ..systems import (CIGREMV14System, GFLLVRTSystem, HybridGFMGFLSystem,
                       HybridSystem, IEEE13System, ParallelVSGSystem, SGSMIBSystem,
                       VSGSMIBAVCSystem, VSGSMIBSystem)


class SystemFactory:
    systemNames = ["HybridSystem", "HybridGFMGFLSystem", "VSGSMIBSystem", "VSGSMIBAVCSystem", "GFLLVRTSystem",
                   "ParallelVSGSystem", "SGSMIBSystem", "IEEE13System", "CIGREMV14System"]
    systemClasses = {
        "HybridSystem": HybridSystem,
        "HybridGFMGFLSystem": HybridGFMGFLSystem,
        "VSGSMIBSystem": VSGSMIBSystem,
        "VSGSMIBAVCSystem": VSGSMIBAVCSystem,
        "GFLLVRTSystem": GFLLVRTSystem,
        "ParallelVSGSystem": ParallelVSGSystem,
        "SGSMIBSystem": SGSMIBSystem,
        "IEEE13System": IEEE13System,
        "CIGREMV14System": CIGREMV14System,
    }

    @classmethod
    def create(cls, systemName: str, parameters: dict[str, Any] | None = None,
               options: dict[str, Any] | None = None):
        parameters, options = cls.defaultParameters(systemName, parameters or {}, options or {})
        return cls.createSystem(systemName, parameters, options), parameters, options

    @staticmethod
    def createSystem(name, p, options):
        classes = {
            "HybridSystem": lambda: HybridSystem(p, EnableGFL=options["EnableGFL"]),
            "HybridGFMGFLSystem": lambda: HybridGFMGFLSystem(p),
            "HybridGFMGFLsystem": lambda: HybridGFMGFLSystem(p),
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

    @staticmethod
    def normalizeFaultParameters(name, supplied, defaults, faultMode):
        """Translate legacy fault inputs to the common time-domain schema."""
        values, original = dict(supplied), dict(supplied)

        def rename(old, new):
            if old in values and new not in values:
                values[new] = values[old]
            values.pop(old, None)

        if name == "HybridSystem":
            transition = values.pop("faultTransition_s", None)
            rename("faultEnd_s", "recoveryStart_s")
            if transition is not None:
                values.setdefault("faultComplete_s", values.get("faultStart_s", defaults["faultStart_s"]) + transition)
                values.setdefault("recoveryComplete_s", values.get("recoveryStart_s", defaults["recoveryStart_s"]) + transition)
        elif name in ("VSGSMIBSystem", "VSGSMIBAVCSystem"):
            ramp = values.pop("voltageRamp_s", defaults["faultComplete_s"] - defaults["faultStart_s"])
            rename("clearTime_s", "recoveryStart_s")
            rename("faultVoltage_pu", "faultVoltage")
            if "faultComplete_s" not in original and ("faultStart_s" in original or "voltageRamp_s" in original):
                values["faultComplete_s"] = values.get("faultStart_s", defaults["faultStart_s"]) + ramp
            if "recoveryComplete_s" not in original and ({"clearTime_s", "recoveryStart_s", "voltageRamp_s"} & original.keys()):
                values["recoveryComplete_s"] = values.get("recoveryStart_s", defaults["recoveryStart_s"]) + ramp
        elif name == "IEEE13System":
            for old, new in (("faultStartTime_s", "faultStart_s"),
                             ("faultCompleteTime_s", "faultComplete_s"),
                             ("recoveryStartTime_s", "recoveryStart_s"),
                             ("recoveryCompleteTime_s", "recoveryComplete_s")):
                rename(old, new)
        elif name in ("CIGREMV14System", "HybridGFMGFLSystem"):
            aliases = (
                (("faultStartAngle_s", "faultStart_s"), ("angleFaultVoltage_pu", "faultVoltage"))
                if faultMode == "angle" else
                (("fixedFaultStart_s", "faultStart_s"), ("fixedFaultComplete_s", "faultComplete_s"),
                 ("fixedClearStart_s", "recoveryStart_s"), ("fixedClearComplete_s", "recoveryComplete_s"),
                 ("fixedFaultVoltage_pu", "faultVoltage"))
            )
            for old, new in aliases:
                rename(old, new)
            for old in ("faultStartAngle_s", "angleFaultVoltage_pu", "fixedFaultStart_s",
                        "fixedFaultComplete_s", "fixedClearStart_s", "fixedClearComplete_s",
                        "fixedFaultVoltage_pu"):
                values.pop(old, None)
        return values

    @classmethod
    def defaultParameters(cls, name, supplied, inputOptions):
        options = {
            "RunTimeDomain": True, "RunSmallSignal": True, "RunInteractionAnalysis": False,
            "StartTime_s": 0.0, "EndTime_s": None, "OutputStep_s": None,
            "SolverSettings": None, "ResidualTolerance": None, "Breakpoints_s": None,
            "DeviceModel": "VSGCC", "ClearingState": "theta", "EnableGFL": True,
            "EnableConverters": False, "FaultMode": None,
        }
        options.update(inputOptions)
        p = cls.systemClasses[name].defaultParameters()
        faultMode = options["FaultMode"] or "time"
        if name in ("CIGREMV14System", "HybridGFMGFLSystem") and faultMode == "angle":
            if not any(key in supplied for key in ("faultStart_s", "faultStartAngle_s")):
                p["faultStart_s"] = 0.20
                p["faultComplete_s"] = 0.201
            if not any(key in supplied for key in ("faultVoltage", "angleFaultVoltage_pu")):
                p["faultVoltage"] = 0.0
        supplied = cls.normalizeFaultParameters(name, supplied, p, faultMode)
        if name == "IEEE13System" and options["EnableConverters"]:
            p.update(IEEE13System.converterDefaultParameters())
        p.update(supplied)
        if options["EndTime_s"] is not None:
            p["validationTime_s"] = options["EndTime_s"]
        p["wBase"] = 2 * np.pi * p["frequency_Hz"]
        if name in ("HybridSystem", "VSGSMIBSystem", "VSGSMIBAVCSystem", "GFLLVRTSystem", "SGSMIBSystem"):
            p["Lg"] = 1 / (p["SCR"] * np.sqrt(1 + p["rho"]**2)); p["Rg"] = p["rho"] * p["Lg"]
        if name == "HybridSystem":
            p["branchL"], p["branchR"] = p["Lg"], p["Rg"]
            eventTime = [0, p["faultStart_s"], p["faultComplete_s"], p["recoveryStart_s"],
                         p["recoveryComplete_s"], p["validationTime_s"]]
            if not p.get("gridVoltage"):
                p["gridVoltage"] = lambda t, times=eventTime, values=[1, 1, p["faultVoltage"], p["faultVoltage"], 1, 1]: cls.linearVoltage(t, times, values)
            outputStep, tolerance = 2e-3, 1e-4
        elif name in ("VSGSMIBSystem", "VSGSMIBAVCSystem"):
            if options["FaultMode"] is None: options["FaultMode"] = p["clearMode"]
            else: p["clearMode"] = options["FaultMode"]
            eventTime = [p["faultStart_s"], p["faultComplete_s"]]
            if p["clearMode"] == "time":
                eventTime += [p["recoveryStart_s"], p["recoveryComplete_s"]]
            else:
                eventTime += [p["faultStart_s"] + p["minimumFaultDuration_s"]]
            outputStep, tolerance = 1e-4, 1e-4
        elif name in ("GFLLVRTSystem", "ParallelVSGSystem", "SGSMIBSystem"):
            eventTime = [0, p["faultStart_s"], p["faultComplete_s"], p["recoveryStart_s"], p["recoveryComplete_s"], p["validationTime_s"]]
            if not p.get("gridVoltage"):
                p["gridVoltage"] = lambda t, times=eventTime, values=[1, 1, p["faultVoltage"], p["faultVoltage"], 1, 1]: cls.linearVoltage(t, times, values)
            outputStep = 5e-4 if name == "GFLLVRTSystem" else 2e-3
            tolerance = 1e-3 if name == "GFLLVRTSystem" else 1e-7 if name == "SGSMIBSystem" else 1e-4
        elif name == "IEEE13System":
            p["Zbase_ohm"] = p.get("Vbase", p["Vbase_LL_V"])**2 / p["Sbase_VA"]
            eventTime = [0, p["faultStart_s"], p["faultComplete_s"], p["recoveryStart_s"], p["recoveryComplete_s"], p["validationTime_s"]]
            if not p.get("infbusVoltage"):
                p["infbusVoltage"] = lambda t, times=eventTime, values=[1, 1, p["faultVoltage"], p["faultVoltage"], 1, 1]: cls.linearVoltage(t, times, values)
            outputStep, tolerance = 1e-3 / p["wBase"], 1e-4
        elif name in ("CIGREMV14System", "HybridGFMGFLSystem"):
            p["clearMode"] = faultMode
            eventTime = (
                [p["faultStart_s"], p["angleClearEligible_s"]]
                if p["clearMode"] == "angle" else
                [p["faultStart_s"], p["faultComplete_s"],
                 p["recoveryStart_s"], p["recoveryComplete_s"]]
            )
            outputStep = p["outputStep_s"]
            tolerance = 1e-4
        else:
            if options["OutputStep_s"] is not None: p["outputStep_s"] = options["OutputStep_s"]
            eventTime, outputStep, tolerance = [], p["outputStep_s"], 1e-4
        options["FaultMode"] = options["FaultMode"] or "time"
        options["EndTime_s"] = p["validationTime_s"] if options["EndTime_s"] is None else options["EndTime_s"]
        options["OutputStep_s"] = outputStep if options["OutputStep_s"] is None else options["OutputStep_s"]
        options["SolverSettings"] = dict(options["SolverSettings"] or {})
        options["ResidualTolerance"] = tolerance if options["ResidualTolerance"] is None else options["ResidualTolerance"]
        options["Breakpoints_s"] = eventTime if options["Breakpoints_s"] is None else options["Breakpoints_s"]
        return p, options
