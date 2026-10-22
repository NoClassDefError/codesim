"""Transient bus-voltage decomposition."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import root


class TransientVoltageAnalyzer:
    """Split bus voltage into QSS, first-order, and EMT components."""

    _TOLERANCE = 1e-8
    _DIFFERENCE_STEP = 1e-6

    def __init__(self, system: Any) -> None:
        self.system = system
        self.latestDecomposition: dict[str, Any] = {}

    def decompose(
        self,
        result: Mapping[str, Any],
        slowStateNames: str | Iterable[str],
        *,
        angleStateName: str | None = None,
        angleRate_rad_s: float | Iterable[float] | None = None,
        busNames: str | Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Decompose every sample of a simulated voltage trajectory.

        The EMT voltage is obtained from an independent fast-state simulation
        with every named slow state fixed at its initial value.  At each sample,
        the QSS voltage is obtained by solving the fast-state equilibrium at
        the simulated slow-state values.  Linearization of that equilibrium for
        a constant angle rate gives the first-order tracking error.  These are
        independently calculated quantities, not an enforced additive identity.

        ``angleRate_rad_s`` defaults to the derivative of the simulated angle.
        A scalar applies the same constant rate to the complete trajectory.
        """
        state = np.asarray(result["state"], dtype=float)
        time = np.asarray(result["time_s"], dtype=float).reshape(-1)
        if state.shape != (time.size, len(self.system.stateNames)):
            raise ValueError("result state dimensions do not match the system")
        if time.size == 0 or np.any(np.diff(time) <= 0):
            raise ValueError("result time must be non-empty and strictly increasing")

        slowNames = (
            [slowStateNames]
            if isinstance(slowStateNames, str)
            else list(slowStateNames)
        )
        unknown = [name for name in slowNames if name not in self.system.stateNames]
        if not slowNames or unknown:
            raise ValueError(f"Invalid state names: {unknown or slowNames}")
        slowNames = list(dict.fromkeys(slowNames))
        slow = np.asarray([self.system.stateNames.index(name) for name in slowNames])
        fast = np.asarray(
            [i for i in range(state.shape[1]) if i not in set(slow)], dtype=int
        )
        if fast.size == 0:
            raise ValueError("At least one state must remain fast")

        if angleStateName is None:
            candidates = [name for name in slowNames if name.lower().startswith("delta")]
            if len(candidates) != 1:
                raise ValueError("Specify angleStateName when slow states contain multiple angles")
            angleStateName = candidates[0]
        if angleStateName not in slowNames:
            raise ValueError("angleStateName must be one of slowStateNames")
        angle = self.system.stateNames.index(angleStateName)

        selectedBuses = (
            list(self.system.busNames)
            if busNames is None
            else ([busNames] if isinstance(busNames, str) else list(busNames))
        )
        unknown = [name for name in selectedBuses if name not in self.system.busNames]
        if not selectedBuses or unknown:
            raise ValueError(f"Invalid bus names: {unknown or selectedBuses}")
        selectedBuses = list(dict.fromkeys(selectedBuses))
        buses = np.asarray([self.system.busNames.index(name) for name in selectedBuses])

        referenceTrace = np.asarray(result.get("referenceTrace", []), dtype=float)
        expectedReferenceShape = (time.size, len(self.system.referenceNames))
        if referenceTrace.shape != expectedReferenceShape:
            references = self.system.getReference()
            referenceTrace = np.asarray(
                [self.system.getReference(t, references) for t in time], dtype=float
            )

        if angleRate_rad_s is None:
            rate = (
                np.gradient(np.unwrap(state[:, angle]), time)
                if time.size > 1
                else np.zeros(1)
            )
        else:
            rate = np.asarray(angleRate_rad_s, dtype=float)
            rate = np.full(time.size, float(rate)) if rate.ndim == 0 else rate.reshape(-1)
            if rate.size != time.size:
                raise ValueError("angleRate_rad_s must be scalar or one value per sample")

        shape = (time.size, buses.size)
        actual = np.empty(shape, dtype=complex)
        qss = np.empty(shape, dtype=complex)
        firstOrder = np.empty(shape, dtype=complex)
        converged = np.empty(time.size, dtype=bool)
        residualNorm = np.empty(time.size)
        jacobianCondition = np.empty(time.size)
        qssState = np.empty_like(state)
        guess = None

        def voltage(sample: np.ndarray, reference: np.ndarray) -> np.ndarray:
            flat = np.asarray(
                self.system.rlGrid.g_numeric(sample, reference)[1], dtype=float
            )
            return (flat[0::2] + 1j * flat[1::2])[buses]

        frozenInitial = state[0].copy()

        def frozenDerivative(t: float, fastState: np.ndarray) -> np.ndarray:
            frozenState = frozenInitial.copy()
            frozenState[fast] = fastState
            reference = np.asarray(
                [np.interp(t, time, referenceTrace[:, j]) for j in range(referenceTrace.shape[1])]
            )
            return self.system.wBase * np.asarray(
                self.system.rlGrid.f_numeric(frozenState, reference), dtype=float
            )[fast]

        emtState = np.tile(frozenInitial, (time.size, 1))
        if time.size > 1:
            frozenSolution = solve_ivp(
                frozenDerivative,
                (time[0], time[-1]),
                frozenInitial[fast],
                t_eval=time,
                max_step=5e-3 / self.system.wBase,
                rtol=1e-6,
                atol=1e-9,
            )
            if not frozenSolution.success:
                raise RuntimeError(f"frozen EMT simulation failed: {frozenSolution.message}")
            emtState[:, fast] = frozenSolution.y.T
        emt = np.asarray(
            [voltage(sample, reference) for sample, reference in zip(emtState, referenceTrace)]
        )

        for i, (sample, reference) in enumerate(zip(state, referenceTrace)):
            actual[i] = voltage(sample, reference)
            equilibrium, converged[i], residualNorm[i] = self._qss(
                sample, fast, reference, guess
            )
            qssState[i] = equilibrium
            guess = equilibrium[fast]
            qss[i] = voltage(equilibrium, reference)
            firstOrder[i], jacobianCondition[i] = self._firstOrder(
                equilibrium, fast, angle, rate[i], reference, buses
            )

        decomposition = {
            "time_s": time,
            "busNames": selectedBuses,
            "slowStateNames": slowNames,
            "fastStateNames": [self.system.stateNames[i] for i in fast],
            "angleStateName": angleStateName,
            "angleRate_rad_s": rate,
            "actualVoltage": actual,
            "qssVoltage": qss,
            "firstOrderError": firstOrder,
            "emtVoltage": emt,
            "emtState": emtState,
            "qssState": qssState,
            "qssConverged": converged,
            "qssResidualNorm": residualNorm,
            "fastJacobianCondition": jacobianCondition,
        }
        self.latestDecomposition = decomposition
        return decomposition

    def _qss(
        self,
        state: np.ndarray,
        fast: np.ndarray,
        reference: np.ndarray,
        guess: np.ndarray | None,
    ) -> tuple[np.ndarray, bool, float]:
        """Solve the fast equilibrium while the slow states remain frozen."""
        equilibrium = state.copy()

        def residual(fastState: np.ndarray) -> np.ndarray:
            equilibrium[fast] = fastState
            return np.asarray(
                self.system.rlGrid.f_numeric(equilibrium, reference), dtype=float
            )[fast]

        solution = root(residual, state[fast] if guess is None else guess, tol=self._TOLERANCE)
        equilibrium[fast] = solution.x
        norm = float(np.linalg.norm(residual(solution.x), ord=np.inf))
        return equilibrium, bool(solution.success and norm <= 10 * self._TOLERANCE), norm

    def _firstOrder(
        self,
        qssState: np.ndarray,
        fast: np.ndarray,
        angle: int,
        rate_rad_s: float,
        reference: np.ndarray,
        buses: np.ndarray,
    ) -> tuple[np.ndarray, float]:
        """Return the voltage lag caused by constant motion along the QSS curve."""
        stateJacobian = self.system.rlGrid.getStateMatrix(qssState, reference)
        fastJacobian = stateJacobian[np.ix_(fast, fast)]
        anglePartial = stateJacobian[fast, angle]
        qssSlope = np.linalg.lstsq(fastJacobian, -anglePartial, rcond=None)[0]
        stateError = np.linalg.lstsq(
            fastJacobian, qssSlope * rate_rad_s / self.system.wBase, rcond=None
        )[0]

        direction = np.zeros_like(qssState)
        direction[fast] = stateError
        scale = self._DIFFERENCE_STEP / max(
            np.max(np.abs(direction)), self._DIFFERENCE_STEP
        )
        voltage = []
        for candidate in (qssState + scale * direction, qssState - scale * direction):
            flat = np.asarray(
                self.system.rlGrid.g_numeric(candidate, reference)[1], dtype=float
            )
            voltage.append((flat[0::2] + 1j * flat[1::2])[buses])
        error = (voltage[0] - voltage[1]) / (2 * scale)
        return error, float(np.linalg.cond(fastJacobian))
