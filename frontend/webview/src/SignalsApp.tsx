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
import { mergeSimulationSignals } from './model/signalModel';
import type { SystemSnapshot } from './model/types';

export function SignalsApp() {
  const [snapshot, setSnapshot] = useState<SystemSnapshot>(mockSystem);
  const [activeTab, setActiveTab] = useState<'time' | 'small-signal' | 'interaction'>('time');

  useEffect(() => {
    const unsubscribeSnapshot = onSystemSnapshot(setSnapshot);
    const unsubscribeStarted = onSimulationStarted(() => {
      setActiveTab('time');
    });
    const unsubscribeChunk = onSimulationChunk((chunk) => {
      setSnapshot((current) => ({
        ...current,
        signals: mergeSimulationSignals(
          current.signals,
          chunk.signals,
          chunk.sequence === 0,
        ),
      }));
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
