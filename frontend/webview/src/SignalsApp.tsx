import { useEffect, useState } from 'react';
import { flushSync } from 'react-dom';
import {
  isInsideVsCode,
  onSimulationChunk,
  onSimulationStarted,
  onSystemSnapshot,
  requestSystemSnapshot,
} from './bridge/vscode';
import { InteractionAnalysisPanel } from './components/InteractionAnalysisPanel';
import { SmallSignalPanel } from './components/SmallSignalPanel';
import { Toolbar } from './components/Toolbar';
import { TransientVoltagePanel } from './components/TransientVoltagePanel';
import { WaveformPanel } from './components/WaveformPanel';
import { mockSystem } from './model/mockSystem';
import { SimulationSignalBuffer } from './model/signalModel';
import type { SystemSnapshot } from './model/types';

// Live plots are refreshed at most this often while a simulation streams.
// The interval grows with the measured render cost (render ≤ ~20 % of the
// time) so large systems stay responsive instead of re-rendering per chunk.
const minimumFlushInterval = 100;
const maximumFlushInterval = 1000;

export function SignalsApp() {
  const [snapshot, setSnapshot] = useState<SystemSnapshot>(() => (
    isInsideVsCode() ? { ...mockSystem, signals: [] } : mockSystem
  ));
  const [activeTab, setActiveTab] = useState<'time' | 'transient-voltage' | 'small-signal' | 'interaction'>('time');

  useEffect(() => {
    const buffer = new SimulationSignalBuffer();
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
      if (!signals) {
        return;
      }
      const started = performance.now();
      flushSync(() => setSnapshot((current) => ({ ...current, signals })));
      const cost = performance.now() - started;
      interval = Math.min(maximumFlushInterval, Math.max(minimumFlushInterval, cost * 4));
    };
    const scheduleFlush = () => {
      if (timer === undefined) {
        timer = window.setTimeout(flush, interval);
      }
    };
    const onVisibilityChange = () => {
      if (!document.hidden && buffer.pending) {
        cancelFlush();
        flush();
      }
    };

    const unsubscribeSnapshot = onSystemSnapshot((next) => {
      // Seed the buffer so later chunks extend the snapshot when reopening mid-run.
      cancelFlush();
      buffer.reset(next.signals);
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
    document.addEventListener('visibilitychange', onVisibilityChange);
    requestSystemSnapshot();
    return () => {
      cancelFlush();
      document.removeEventListener('visibilitychange', onVisibilityChange);
      unsubscribeSnapshot();
      unsubscribeStarted();
      unsubscribeChunk();
    };
  }, []);

  return (
    <main className="app-shell signals-shell">
      <Toolbar systemName={snapshot.system.name} view="signals" />
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
            className={activeTab === 'transient-voltage' ? 'active' : ''}
            onClick={() => setActiveTab('transient-voltage')}
          >
            Voltage decomposition
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
          <WaveformPanel snapshot={snapshot} />
        ) : activeTab === 'transient-voltage' ? (
          <TransientVoltagePanel snapshot={snapshot} />
        ) : activeTab === 'small-signal' ? (
          <SmallSignalPanel snapshot={snapshot} />
        ) : (
          <InteractionAnalysisPanel snapshot={snapshot} />
        )}
      </section>
    </main>
  );
}
