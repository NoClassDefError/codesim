import sys
from collections.abc import Iterable, Mapping
from typing import Any, Callable

import numpy as np
from scipy.integrate import solve_ivp


class TransientVoltageAnalyzer:
    """EMT component of a simulated trajectory by fast-state replay.

    Along an accurately simulated slow-state trajectory, the slow states are
    held on that trajectory and only the fast states are simulated
    (:meth:`decompose`). The quasi-steady (QSS) and first-order voltage
    components are provided by the RMS model (``System.simulateRMS``) and its
    first-order correction (``System.correctRMS``).
    """

    def __init__(self, system: Any) -> None:
        self.system = system

    def heldAndFastIndices(self, slowStateNames: str | Iterable[str]) -> tuple[list[str], np.ndarray, np.ndarray]:
        """Partition the states into held (slow) and fast ones.

        Held states are the requested ``slowStateNames``, the system's
        ``qssRequiredSlowStateNames`` and every state without an
        initialization residual (frame angles). Returns the slow names
        (requested first), the sorted held indices and the fast indices.
        """
        requested = ([slowStateNames] if isinstance(slowStateNames, str)
                     else list(slowStateNames))
        required = list(getattr(self.system, "qssRequiredSlowStateNames", ()))
        slowNames = requested + [name for name in required if name not in requested]
        if (not requested or len(set(slowNames)) != len(slowNames)
                or any(n not in self.system.stateNames for n in slowNames)):
            raise ValueError("slowStateNames must contain unique, known states")
        count = len(self.system.stateNames)
        slow = {self.system.stateNames.index(n) for n in slowNames}
        held = np.array(sorted(slow | (set(range(count)) - set(self.system.rlGrid.fInitStateIndices))), dtype=int)
        fast = np.array([i for i in range(count) if i not in set(held)], dtype=int)
        if not fast.size:
            raise ValueError("at least one state must remain fast")
        return slowNames, held, fast

    def decompose(
        self,
        result: Mapping[str, Any],
        slowStateNames: str | Iterable[str],
        *,
        busNames: str | Iterable[str] | None = None,
        maxSamples: int | None = None,
        timeWindow_s: tuple[float, float] | None = None,
    ) -> dict[str, Any]:
        """EMT component of a simulated trajectory by fast-state replay.

        ``result`` is returned by ``system.simulate`` (``time_s``, ``state``
        and optionally ``referenceTrace``). Over the window
        ``timeWindow_s = (t0, t1)`` (default: the whole result) the held
        states (see :meth:`heldAndFastIndices`) and references follow the
        simulated trajectory, linearly interpolated between samples, while
        the fast states are integrated from their simulated value at ``t0``.

        ``emtVoltage`` is the bus voltage of the replayed state and
        ``replayError = actualVoltage - emtVoltage`` measures how well the
        held slow trajectory explains the fast response. Voltages are
        evaluated at up to ``maxSamples`` evenly spaced samples; the replay
        always uses the full window.
        """
        state = np.asarray(result["state"], dtype=float)
        time = np.asarray(result["time_s"], dtype=float).reshape(-1)
        if time.size == 0 or np.any(np.diff(time) <= 0) or state.shape != (time.size, len(self.system.stateNames)):
            raise ValueError("state and time must have matching dimensions and increasing time")
        references = np.asarray(result.get("referenceTrace", []), dtype=float)
        if references.shape != (time.size, len(self.system.referenceNames)):
            references = np.asarray([self.system.getReference(t) for t in time], dtype=float)
        if timeWindow_s is not None:
            start_s, stop_s = (float(value) for value in timeWindow_s)
            inside = (time >= start_s) & (time <= stop_s)
            if not inside.any():
                raise ValueError("timeWindow_s contains no simulated samples")
            time, state, references = time[inside], state[inside], references[inside]
        if maxSamples is not None and maxSamples < 1:
            raise ValueError("maxSamples must be positive")

        requestedSlowNames = ([slowStateNames] if isinstance(slowStateNames, str)
                              else list(slowStateNames))
        slowNames, _, fast = self.heldAndFastIndices(requestedSlowNames)
        selectedBuses = (list(self.system.busNames) if busNames is None
                         else [busNames] if isinstance(busNames, str) else list(busNames))
        if not selectedBuses or any(n not in self.system.busNames for n in selectedBuses):
            raise ValueError("busNames must contain known buses")
        buses = [self.system.busNames.index(n) for n in selectedBuses]
        sampleIndices = (np.arange(time.size) if maxSamples is None or maxSamples >= time.size
                         else np.linspace(0, time.size - 1, maxSamples, dtype=int))
        wBase = 2 * np.pi * self.system.base["frequency_Hz"]

        def reportProgress(message: str) -> None:
            print(f"[transient voltage] {message}", file=sys.stderr, flush=True)

        lastPercent = -1

        def reportEmtProgress(fraction: float) -> None:
            nonlocal lastPercent
            percent = min(100, max(0, int(fraction * 20) * 5))
            if percent > lastPercent:
                reportProgress(f"running EMT replay ({percent}%)")
                lastPercent = percent

        def voltage(x, u):
            flat = np.asarray(self.system.rlGrid.g_numeric(x, u)[1], dtype=float)
            return (flat[::2] + 1j * flat[1::2])[buses]

        reportProgress(f"starting EMT replay of {time.size} samples")
        reportEmtProgress(0.0)
        emtState = self._emt(
            state, time, wBase, fast, references, progress=reportEmtProgress,
        )[sampleIndices]
        reportEmtProgress(1.0)
        actual = np.asarray([voltage(state[k], references[k]) for k in sampleIndices])
        emt = np.asarray([voltage(x, references[k]) for x, k in zip(emtState, sampleIndices)])
        decomposition = {
            "time_s": time[sampleIndices], "sourceSampleCount": time.size,
            "sampleIndices": sampleIndices, "busNames": selectedBuses,
            "requestedSlowStateNames": requestedSlowNames,
            "slowStateNames": slowNames,
            "fastStateNames": [self.system.stateNames[i] for i in fast],
            "actualVoltage": actual, "emtVoltage": emt,
            "replayError": actual - emt, "emtState": emtState,
        }
        self.latestDecomposition = decomposition
        reportProgress("complete")
        return decomposition

    def _emt(
        self,
        state,
        time,
        wBase,
        fast,
        referenceTrace=None,
        progress: Callable[[float], None] | None = None,
    ):
        """Replay fast states using piecewise-linear held-state inputs."""
        state, time = np.asarray(state, dtype=float), np.asarray(time, dtype=float)
        fast = np.asarray(fast, dtype=int)
        fastSet = set(fast)
        held = np.asarray(
            [i for i in range(state.shape[1]) if i not in fastSet], dtype=int,
        )
        references = (np.asarray(referenceTrace, dtype=float) if referenceTrace is not None
                      else np.asarray([self.system.getReference(t) for t in time]))
        emtState = state.copy()
        if time.size > 1:
            # Prepare the line segments once. At each solver evaluation, locate
            # one interval and interpolate every held state/reference together.
            # This avoids a separate scalar interpolation for every input column.
            duration = np.diff(time)
            heldValues = state[:, held]
            heldSlopes = np.diff(heldValues, axis=0) / duration[:, None]
            referenceSlopes = np.diff(references, axis=0) / duration[:, None]
            sample = np.empty(state.shape[1])

            def derivative(t, x):
                if progress is not None:
                    progress((t - time[0]) / (time[-1] - time[0]))
                interval = min(
                    max(int(np.searchsorted(time, t, side="right")) - 1, 0),
                    time.size - 2,
                )
                offset = t - time[interval]
                sample[fast] = x
                sample[held] = heldValues[interval] + offset * heldSlopes[interval]
                reference = references[interval] + offset * referenceSlopes[interval]
                return wBase * np.asarray(
                    self.system.rlGrid.f_numeric(sample, reference), dtype=float,
                )[fast]

            solution = solve_ivp(
                derivative, (time[0], time[-1]), state[0, fast], t_eval=time,
                max_step=5e-3 / wBase, rtol=1e-6, atol=1e-9,
            )
            if not solution.success:
                raise RuntimeError(f"EMT simulation failed: {solution.message}")
            emtState[:, fast] = solution.y.T
        return emtState
