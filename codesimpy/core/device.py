"""Common symbolic interface for voltage and current devices."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, Mapping

import numpy as np
import sympy as sp


class Device(ABC):
    """Base class for all converter, source, load, and passive devices.

    Concrete device classes only need to define their symbolic equations and
    initialization/power-flow relations. Symbolic expressions remain in memory;
    MATLAB's generated ``.m``/``.mat`` cache has deliberately not been ported.
    """

    def __init__(
        self,
        Vb: float,
        Sb: float,
        type: str,
        index: str | int,
        paramConfig: Mapping[str, Any] | Iterable[tuple[str, Any]],
        stateNames: Iterable[str],
        referenceNames: Iterable[str],
    ) -> None:
        if type not in {"Voltage", "Current"}:
            raise ValueError("type must be 'Voltage' or 'Current'")

        self.Vb = float(Vb)
        self.Sb = float(Sb)
        self.Ib = self.Sb / (np.sqrt(3 / 2) * self.Vb)
        self.type = type
        self.index = f"_{index}"
        self.Inputscale = 1.0
        self.Outputscale = 1.0

        if type == "Voltage":
            self.y = self._symbols(("va", "vb"))
            self.u = self._symbols(("ia", "ib"))
        else:
            self.y = self._symbols(("ia", "ib"))
            self.u = self._symbols(("va", "vb"))

        items = paramConfig.items() if isinstance(paramConfig, Mapping) else paramConfig
        self.p: dict[str, dict[str, Any]] = {}
        for name, value in items:
            array = np.asarray(value)
            if array.ndim == 0:
                symbol: Any = sp.Symbol(f"{name}{self.index}", real=True)
            else:
                symbol = np.asarray(
                    sp.symbols(f"{name}{self.index}_0:{array.size}", real=True),
                    dtype=object,
                ).reshape(array.shape, order="F")
            self.p[str(name)] = {"num": value, "sym": symbol}

        self.x = self._symbols(stateNames)
        self.uref = self._symbols(referenceNames)
        self.n = len(self.x)
        self.f, self.g = self.getStateAndOutputEquationsSym()
        self.f = sp.Matrix(self.f) if len(self.f) else sp.zeros(0, 1)
        self.g = sp.Matrix(self.g) if len(self.g) else sp.zeros(0, 1)
        self.f_core = None
        self.g_core = None
        self.parameterMap = self._parameter_map()

    def _symbols(self, names: Iterable[str]) -> tuple[sp.Symbol, ...]:
        return tuple(sp.Symbol(f"{name}{self.index}", real=True) for name in names)

    def _parameter_map(self) -> dict[str, Any]:
        symbols: list[sp.Expr] = []
        values: list[float] = []
        for parameter in self.p.values():
            symbols.extend(np.asarray(parameter["sym"], dtype=object).reshape(-1, order="F"))
            values.extend(np.asarray(parameter["num"], dtype=float).reshape(-1, order="F"))
        return {
            "parameterSymbols": tuple(symbols),
            "parameterValues": np.asarray(values, dtype=float),
        }

    def getStateMatrix(self) -> sp.Matrix:
        return self.f.jacobian(self.x)

    def convertToAnotherBase(self, Vbnew: float, Sbnew: float) -> None:
        voltageOutputScale = self.Vb / Vbnew
        newCurrentBase = Sbnew / (np.sqrt(3 / 2) * Vbnew)
        currentOutputScale = self.Ib / newCurrentBase
        if self.type == "Voltage":
            self.Inputscale = 1 / currentOutputScale
            self.Outputscale = voltageOutputScale
        else:
            self.Inputscale = 1 / voltageOutputScale
            self.Outputscale = currentOutputScale

    @abstractmethod
    def getStateAndOutputEquationsSym(self) -> tuple[Any, Any]:
        """Return symbolic state derivative ``f`` and port output ``g``."""

    @abstractmethod
    def getPowerFlowEquations(self) -> Any:
        """Return the device's steady-state power-flow equations."""

    @abstractmethod
    def initFromPowerFlow(self, P: float, Q: float, V: float, theta: float) -> Any:
        """Return an initial state estimate for a power-flow solution."""

    @abstractmethod
    def getFInit(self) -> Any:
        """Return symbolic steady-state initialization residuals."""
