import { useEffect, useState } from 'react';
import {
  isInsideVsCode,
  loadSystemDescriptor,
  onBackendInfo,
  onBackendStatus,
  openSignalsView,
  requestBackendInfo,
  runAnalysis,
  startBackend,
  stopBackend,
} from '../bridge/vscode';

interface Props {
  systemName: string;
  onResetLayout?: () => void;
  onSaveLayout?: () => void;
  showSignalsButton?: boolean;
  view?: 'topology' | 'signals';
}

export function Toolbar({
  systemName,
  onResetLayout,
  onSaveLayout,
  showSignalsButton = false,
  view = 'topology',
}: Props) {
  const [systems, setSystems] = useState<string[]>([]);
  const [selectedSystem, setSelectedSystem] = useState('VSGSMIBSystem');
  const [backendRunning, setBackendRunning] = useState(false);
  const [running, setRunning] = useState(false);
  const [activeAction, setActiveAction] = useState<string>();

  useEffect(() => {
    const unsubscribeInfo = onBackendInfo((info) => {
      setSystems(info.systems);
      setSelectedSystem(info.selectedSystem || info.systems[0] || '');
      setBackendRunning(info.backendRunning);
      setRunning(info.running);
    });
    const unsubscribeStatus = onBackendStatus((status) => {
      if (status.backendRunning !== undefined) {
        setBackendRunning(status.backendRunning);
        if (!status.backendRunning) {
          setSystems([]);
        }
      }
      setRunning(status.running);
      setActiveAction(status.running ? status.action : undefined);
      if (status.selectedSystem) {
        setSelectedSystem(status.selectedSystem);
      }
    });
    requestBackendInfo();
    return () => {
      unsubscribeInfo();
      unsubscribeStatus();
    };
  }, []);

  const modelUnavailable = !backendRunning || running || systems.length === 0 || !selectedSystem;
  const selectSystem = (system: string) => {
    setSelectedSystem(system);
    loadSystemDescriptor(system);
  };
  const runLabel = (label: string, action: string) =>
    running && activeAction === action ? `${label}…` : label;

  return (
    <header className={`toolbar toolbar-${view}`}>
      <div className="toolbar-title">
        <strong>CodeSim</strong>
        <span>{systemName}</span>
      </div>
      <div className="toolbar-actions">
        {!isInsideVsCode() && <span className="dev-badge">Browser preview</span>}
        {view === 'topology' && (
          <button
            type="button"
            className={backendRunning ? 'toolbar-icon-button backend-toggle active' : 'toolbar-icon-button backend-toggle'}
            onClick={backendRunning ? stopBackend : startBackend}
            title={backendRunning ? 'Stop Python backend' : 'Start Python backend'}
            aria-label={backendRunning ? 'Stop Python backend' : 'Start Python backend'}
            aria-pressed={backendRunning}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 2.5v9M6.2 5.8a8 8 0 1 0 11.6 0" />
            </svg>
            <i />
          </button>
        )}
        <select
          aria-label="System class"
          value={selectedSystem}
          disabled={!backendRunning || running || systems.length === 0}
          onChange={(event) => selectSystem(event.target.value)}
          title="Select and load a system"
        >
          {systems.length === 0 && <option value="">No systems found</option>}
          {systems.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
        {view === 'signals' && (
          <div className="toolbar-analysis-actions">
            <button
              type="button"
              className="toolbar-analysis-button primary"
              disabled={modelUnavailable}
              onClick={() => runAnalysis('simulation', selectedSystem)}
              title="Run the time-domain simulation"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="m8 5 11 7-11 7V5Z" />
              </svg>
              {runLabel('Simulate', 'simulation')}
            </button>
            <button
              type="button"
              className="toolbar-analysis-button"
              disabled={modelUnavailable}
              onClick={() => runAnalysis('smallSignal', selectedSystem)}
              title="Run the small-signal analysis"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M3 12h3l2-5 4 10 3-8 2 5h4" />
              </svg>
              {runLabel('Small signal', 'smallSignal')}
            </button>
            <button
              type="button"
              className="toolbar-analysis-button"
              disabled={modelUnavailable || selectedSystem !== 'HybridSystem'}
              onClick={() => runAnalysis('interaction', selectedSystem)}
              title="Run modal interaction analysis for HybridSystem"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <circle cx="6" cy="7" r="2.5" />
                <circle cx="18" cy="7" r="2.5" />
                <circle cx="12" cy="17" r="2.5" />
                <path d="m8 8.4 2.7 6.2M16 8.4l-2.7 6.2M8.5 7h7" />
              </svg>
              {runLabel('Interaction', 'interaction')}
            </button>
          </div>
        )}
        {showSignalsButton && (
          <button
            type="button"
            className="toolbar-icon-button"
            onClick={openSignalsView}
            title="Open signals and results"
            aria-label="Open signals and results"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M3 12h3l2.2-6 4.1 12 2.5-8 1.8 4H21" />
            </svg>
          </button>
        )}
        {view === 'topology' && (
          <div className="toolbar-button-group">
            <button
              type="button"
              className="toolbar-icon-button"
              disabled={modelUnavailable}
              onClick={() => loadSystemDescriptor(selectedSystem)}
              title="Refresh the selected system"
              aria-label="Refresh the selected system"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M20 11a8 8 0 0 0-14.9-4M4 4v5h5M4 13a8 8 0 0 0 14.9 4M20 20v-5h-5" />
              </svg>
            </button>
            {onResetLayout && (
              <button
                type="button"
                className="toolbar-icon-button"
                onClick={onResetLayout}
                title="Automatically arrange the topology"
                aria-label="Automatically arrange the topology"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="3" y="4" width="6" height="5" rx="1" />
                  <rect x="15" y="4" width="6" height="5" rx="1" />
                  <rect x="9" y="15" width="6" height="5" rx="1" />
                  <path d="M6 9v3h12V9M12 12v3" />
                </svg>
              </button>
            )}
            {onSaveLayout && isInsideVsCode() && (
              <button
                type="button"
                className="toolbar-icon-button"
                onClick={onSaveLayout}
                title="Save the topology layout"
                aria-label="Save the topology layout"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 3h12l3 3v15H4V3h1Z" />
                  <path d="M8 3v6h8V3M8 21v-7h8v7" />
                </svg>
              </button>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
