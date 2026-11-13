import { useEffect, useMemo, useState } from 'react';
import { flushSync } from 'react-dom';
import {
  isInsideVsCode,
  onRMSChunk,
  onRMSStarted,
  onSimulationChunk,
  onSimulationStarted,
  onSystemSnapshot,
  requestSystemSnapshot,
} from './bridge/vscode';
import { InteractionAnalysisPanel } from './components/InteractionAnalysisPanel';
import { SmallSignalPanel } from './components/SmallSignalPanel';
import { Toolbar } from './components/Toolbar';
import { WaveformPanel } from './components/WaveformPanel';
import { mockSystem } from './model/mockSystem';
import { rmsPlotSignals, SimulationSignalBuffer } from './model/signalModel';
import type { RMSSimulationDescriptor, SystemSnapshot } from './model/types';

// Live plots are refreshed at most this often while a simulation streams.
// The interval grows with the measured render cost (render ≤ ~20 % of the
// time) so large systems stay responsive instead of re-rendering per chunk.
const minimumFlushInterval = 100;
const maximumFlushInterval = 1000;

/** RMS descriptor shown while an RMS run streams; chunks fill its signals. */
function liveRMSPlaceholder(): RMSSimulationDescriptor {
  return {
    available: true,
    streaming: true,
    model: 'RMS',
    differentialStateNames: [],
    algebraicStateNames: [],
    time_s: [],
    algebraicResidual: [],
    maxAlgebraicResidual: 0,
    signals: [],
  };
}

export function SignalsApp() {
  const [snapshot, setSnapshot] = useState<SystemSnapshot>(() => (
    isInsideVsCode() ? { ...mockSystem, signals: [] } : mockSystem
  ));
  const [activeTab, setActiveTab] = useState<'time' | 'small-signal' | 'interaction'>('time');

  useEffect(() => {
    // EMT and RMS runs stream into separate buffers that share one throttle.
    const buffer = new SimulationSignalBuffer();
    const rmsBuffer = new SimulationSignalBuffer();
    let timer: number | undefined;
    let interval = minimumFlushInterval;

    const cancelFlush = () => {
      if (timer !== undefined) {
        window.clearTimeout(timer);
        timer = undefined;
      }
    };
    const flush = () => {
      timer = undefined;
      if (document.hidden) {
        // Nothing is painted while the panel is hidden; catch up when shown.
        return;
      }
      const signals = buffer.take();
      const rmsSignals = rmsBuffer.take();
      if (!signals && !rmsSignals) {
        return;
      }
      const started = performance.now();
      flushSync(() => setSnapshot((current) => ({
        ...current,
        ...(signals ? { signals } : {}),
        ...(rmsSignals ? {
          rmsSimulation: { ...(current.rmsSimulation ?? liveRMSPlaceholder()), signals: rmsSignals },
        } : {}),
      })));
      const cost = performance.now() - started;
      interval = Math.min(maximumFlushInterval, Math.max(minimumFlushInterval, cost * 4));
    };
    const scheduleFlush = () => {
      if (timer === undefined) {
        timer = window.setTimeout(flush, interval);
      }
    };
    const onVisibilityChange = () => {
      if (!document.hidden && (buffer.pending || rmsBuffer.pending)) {
        cancelFlush();
        flush();
      }
    };

    const unsubscribeSnapshot = onSystemSnapshot((next) => {
      // Seed the buffers so later chunks extend the snapshot when reopening mid-run.
      cancelFlush();
      buffer.reset(next.signals);
      rmsBuffer.reset(next.rmsSimulation?.streaming ? next.rmsSimulation.signals : []);
      setSnapshot(next);
    });
    const unsubscribeStarted = onSimulationStarted(() => {
      cancelFlush();
      buffer.reset();
      interval = minimumFlushInterval;
      setActiveTab('time');
      setSnapshot((current) => ({ ...current, signals: [] }));
    });
    const unsubscribeChunk = onSimulationChunk((chunk) => {
      buffer.append(chunk.signals, chunk.sequence === 0);
      scheduleFlush();
    });
    // RMS waveforms stream into the time-domain plots like EMT ones.
    const unsubscribeRMSStarted = onRMSStarted(() => {
      cancelFlush();
      rmsBuffer.reset();
      interval = minimumFlushInterval;
      setActiveTab('time');
      setSnapshot((current) => ({ ...current, rmsSimulation: liveRMSPlaceholder() }));
    });
    const unsubscribeRMSChunk = onRMSChunk((chunk) => {
      rmsBuffer.append(chunk.signals, chunk.sequence === 0);
      scheduleFlush();
    });
    document.addEventListener('visibilitychange', onVisibilityChange);
    requestSystemSnapshot();
    return () => {
      cancelFlush();
      document.removeEventListener('visibilitychange', onVisibilityChange);
      unsubscribeSnapshot();
      unsubscribeStarted();
      unsubscribeChunk();
      unsubscribeRMSStarted();
      unsubscribeRMSChunk();
    };
  }, []);

  // EMT and RMS traces share the time-domain plots.
  const rmsSignals = useMemo(
    () => rmsPlotSignals(snapshot.rmsSimulation),
    [snapshot.rmsSimulation],
  );
  const timeDomainSnapshot = useMemo(
    () => (rmsSignals.length > 0
      ? { ...snapshot, signals: [...snapshot.signals, ...rmsSignals] }
      : snapshot),
    [rmsSignals, snapshot],
  );

  return (
    <main className="app-shell signals-shell">
      <Toolbar
        systemName={snapshot.system.name}
        view="signals"
        rmsResult={snapshot.rmsSimulation?.available && !snapshot.rmsSimulation.streaming
          ? snapshot.rmsSimulation
          : undefined}
      />
      <section className="results-body">
        <nav className="results-tabs" aria-label="Analysis views">
          <button
            type="button"
            className={activeTab === 'time' ? 'active' : ''}
            onClick={() => setActiveTab('time')}
          >
            Time domain
          </button>
          <button
            type="button"
            className={activeTab === 'small-signal' ? 'active' : ''}
            onClick={() => setActiveTab('small-signal')}
          >
            Small signal
          </button>
          <button
            type="button"
            className={activeTab === 'interaction' ? 'active' : ''}
            onClick={() => setActiveTab('interaction')}
          >
            Interaction analysis
          </button>
        </nav>
        {activeTab === 'time' ? (
          <WaveformPanel snapshot={timeDomainSnapshot} />
        ) : activeTab === 'small-signal' ? (
          <SmallSignalPanel snapshot={snapshot} />
        ) : (
          <InteractionAnalysisPanel snapshot={snapshot} />
        )}
      </section>
    </main>
  );
}
