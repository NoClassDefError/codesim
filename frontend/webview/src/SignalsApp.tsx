import { useEffect, useState } from 'react';
import {
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
import type { SystemSnapshot } from './model/types';

export function SignalsApp() {
  const [snapshot, setSnapshot] = useState<SystemSnapshot>(mockSystem);
  const [activeTab, setActiveTab] = useState<'time' | 'small-signal' | 'interaction'>('time');

  useEffect(() => {
    const unsubscribeSnapshot = onSystemSnapshot(setSnapshot);
    const unsubscribeStarted = onSimulationStarted(() => {
      setSnapshot((current) => ({ ...current, signals: [] }));
      setActiveTab('time');
    });
    const unsubscribeChunk = onSimulationChunk((chunk) => {
      setSnapshot((current) => {
        const signals = new Map(current.signals.map((signal) => [signal.id, signal]));
        for (const incoming of chunk.signals) {
          const existing = signals.get(incoming.id);
          signals.set(incoming.id, existing ? {
            ...existing,
            time: [...existing.time, ...incoming.time],
            values: [...existing.values, ...incoming.values],
          } : incoming);
        }
        return { ...current, signals: [...signals.values()] };
      });
    });
    requestSystemSnapshot();
    return () => {
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
        ) : activeTab === 'small-signal' ? (
          <SmallSignalPanel snapshot={snapshot} />
        ) : (
          <InteractionAnalysisPanel snapshot={snapshot} />
        )}
      </section>
    </main>
  );
}
