import { useEffect, useRef, useState } from 'react';
import {
  isInsideVsCode,
  loadSystemDescriptor,
  onBackendInfo,
  onBackendStatus,
  openSignalsView,
  requestBackendInfo,
  runAnalysis,
  runRMS,
  startBackend,
  stopBackend,
} from '../bridge/vscode';
import type { RMSSimulationDescriptor } from '../model/types';

/** Algebraic residual (inf-norm) above which the RMS solve is flagged. */
const rmsResidualWarning = 1e-6;

function formatSeconds(value: number | undefined): string {
  if (value === undefined || !Number.isFinite(value)) {
    return '—';
  }
  return value < 1 ? `${(value * 1e3).toFixed(0)} ms` : `${value.toFixed(2)} s`;
}

function parsePositive(text: string): number | undefined {
  const value = Number(text);
  return text.trim() !== '' && Number.isFinite(value) && value > 0 ? value : undefined;
}

interface Props {
  systemName: string;
  onResetLayout?: () => void;
  onSaveLayout?: () => void;
  showSignalsButton?: boolean;
  view?: 'topology' | 'signals';
  /** Latest RMS run, summarised in the RMS options popover. */
  rmsResult?: RMSSimulationDescriptor;
}

export function Toolbar({
  systemName,
  onResetLayout,
  onSaveLayout,
  showSignalsButton = false,
  view = 'topology',
  rmsResult,
}: Props) {
  const [systems, setSystems] = useState<string[]>([]);
  const [selectedSystem, setSelectedSystem] = useState('SMIB__GFM_A_C_LC');
  const [backendRunning, setBackendRunning] = useState(false);
  const [running, setRunning] = useState(false);
  const [activeAction, setActiveAction] = useState<string>();
  const [rmsCorrection, setRmsCorrection] = useState(rmsResult?.model === 'RMS+Delta');
  const [rmsCutoffText, setRmsCutoffText] = useState(String(rmsResult?.cutoff_Hz ?? 1000));
  const [rmsMaxStepText, setRmsMaxStepText] = useState('');
  const [rmsOptionsOpen, setRmsOptionsOpen] = useState(false);
  const rmsGroupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!rmsOptionsOpen) {
      return undefined;
    }
    const closeOutside = (event: PointerEvent) => {
      if (!rmsGroupRef.current?.contains(event.target as Node)) {
        setRmsOptionsOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setRmsOptionsOpen(false);
      }
    };
    document.addEventListener('pointerdown', closeOutside);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOutside);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [rmsOptionsOpen]);

  useEffect(() => {
    const unsubscribeInfo = onBackendInfo((info) => {
      setSystems(info.systems);
      setSelectedSystem(info.systems.includes(info.selectedSystem)
        ? info.selectedSystem
        : info.systems[0] ?? '');
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
  const rmsCutoff_Hz = parsePositive(rmsCutoffText);
  const rmsMaxStep_ms = parsePositive(rmsMaxStepText);
  const rmsInputsValid = (!rmsCorrection || rmsCutoff_Hz !== undefined)
    && (rmsMaxStepText.trim() === '' || rmsMaxStep_ms !== undefined);
  const startRMS = () => {
    setRmsOptionsOpen(false);
    runRMS(selectedSystem, {
      correction: rmsCorrection,
      cutoff_Hz: rmsCorrection ? rmsCutoff_Hz : undefined,
      maxStep_s: rmsMaxStep_ms !== undefined ? rmsMaxStep_ms / 1e3 : undefined,
    });
  };

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
              title="Run the EMT time-domain simulation"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="m8 5 11 7-11 7V5Z" />
              </svg>
              {runLabel('EMT', 'simulation')}
            </button>
            <div className="toolbar-split-button" ref={rmsGroupRef}>
              <button
                type="button"
                className="toolbar-analysis-button primary"
                disabled={modelUnavailable || !rmsInputsValid}
                onClick={startRMS}
                title={rmsCorrection
                  ? `Run the RMS (phasor) simulation with the RMS+Δ correction (cutoff ${rmsCutoffText} Hz)`
                  : 'Run the RMS (phasor) simulation'}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="m8 5 11 7-11 7V5Z" />
                </svg>
                {runLabel(rmsCorrection ? 'RMS+Δ' : 'RMS', 'rms')}
              </button>
              <button
                type="button"
                className="toolbar-analysis-button primary toolbar-split-toggle"
                disabled={running}
                onClick={() => setRmsOptionsOpen((open) => !open)}
                title="RMS simulation options"
                aria-label="RMS simulation options"
                aria-expanded={rmsOptionsOpen}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="m7 10 5 5 5-5" />
                </svg>
              </button>
              {rmsOptionsOpen && (
                <div className="toolbar-popover" role="dialog" aria-label="RMS simulation options">
                  <p className="toolbar-popover-note">
                    Phasor model: network and fast filter states are algebraic, only slow
                    dynamics are integrated. Results appear in the Time domain plots.
                  </p>
                  <label className="toolbar-popover-check">
                    <input
                      type="checkbox"
                      checked={rmsCorrection}
                      onChange={(event) => setRmsCorrection(event.target.checked)}
                    />
                    <span>RMS+Δ correction</span>
                  </label>
                  <label>
                    <span>Correction cutoff (Hz)</span>
                    <input
                      type="number"
                      min="1"
                      step="100"
                      value={rmsCutoffText}
                      disabled={!rmsCorrection}
                      onChange={(event) => setRmsCutoffText(event.target.value)}
                    />
                  </label>
                  <label>
                    <span>Max step (ms)</span>
                    <input
                      type="number"
                      min="0"
                      step="0.5"
                      placeholder="1 (default)"
                      value={rmsMaxStepText}
                      onChange={(event) => setRmsMaxStepText(event.target.value)}
                    />
                  </label>
                  {!rmsInputsValid && (
                    <p className="toolbar-popover-error">Enter positive numbers.</p>
                  )}
                  {rmsResult && (
                    <dl className="toolbar-popover-stats">
                      <dt>Last run</dt>
                      <dd>{rmsResult.model === 'RMS+Delta' ? `RMS+Δ · ${rmsResult.cutoff_Hz} Hz` : 'RMS'}</dd>
                      <dt>Wall time</dt>
                      <dd>
                        {formatSeconds(rmsResult.simulationTime_s)}
                        {rmsResult.model === 'RMS+Delta' && ` + ${formatSeconds(rmsResult.correctionTime_s)}`}
                      </dd>
                      <dt>States</dt>
                      <dd title={rmsResult.differentialStateNames.join(', ')}>
                        {rmsResult.differentialStateNames.length} differential · {rmsResult.algebraicStateNames.length} algebraic
                      </dd>
                      <dt>Max residual</dt>
                      <dd className={rmsResult.maxAlgebraicResidual > rmsResidualWarning ? 'warning' : 'ok'}>
                        {rmsResult.maxAlgebraicResidual.toExponential(2)}
                      </dd>
                      {rmsResult.model === 'RMS+Delta' && (
                        <>
                          <dt>Quasi-static modes</dt>
                          <dd>{rmsResult.maxQuasiStaticModeCount ?? 0} (max)</dd>
                        </>
                      )}
                    </dl>
                  )}
                </div>
              )}
            </div>
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
              disabled={modelUnavailable}
              onClick={() => runAnalysis('interaction', selectedSystem)}
              title="Run modal interaction analysis (one block per device plus the network)"
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
