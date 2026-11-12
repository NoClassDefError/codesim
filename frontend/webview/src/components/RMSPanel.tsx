import { useEffect, useMemo, useState } from 'react';
import { isInsideVsCode, onBackendStatus, runRMS } from '../bridge/vscode';
import type { SystemSnapshot } from '../model/types';
import { WaveformPanel } from './WaveformPanel';

/** Algebraic residual (inf-norm) above which the RMS solve is flagged. */
const residualWarning = 1e-6;

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

/**
 * RMS (phasor) simulation: differential states are the frame angles and each
 * device's `rmsDynamicStateNames`; every other state is solved algebraically.
 * Results are plotted with the regular waveform workspace.
 */
export function RMSPanel({ snapshot }: { snapshot: SystemSnapshot }) {
  const result = snapshot.rmsSimulation?.available ? snapshot.rmsSimulation : undefined;
  const systemClassName = snapshot.system.className.split('.').at(-1) ?? snapshot.system.name;
  const [correction, setCorrection] = useState(result?.model === 'RMS+Delta');
  const [cutoffText, setCutoffText] = useState(String(result?.cutoff_Hz ?? 1000));
  const [maxStepText, setMaxStepText] = useState('');
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | undefined>();

  useEffect(() => onBackendStatus((status) => {
    setBusy(status.running);
    setRunning(status.running && status.action === 'rms');
    if (status.running && status.action === 'rms') {
      setError(undefined);
    } else if (!status.running && status.finishedAction === 'rms') {
      setError(status.error);
    }
  }), []);

  const cutoff_Hz = parsePositive(cutoffText);
  const maxStep_ms = parsePositive(maxStepText);
  const inputsValid = (!correction || cutoff_Hz !== undefined)
    && (maxStepText.trim() === '' || maxStep_ms !== undefined);

  const plotSnapshot = useMemo(
    () => (result ? { ...snapshot, signals: result.signals } : undefined),
    [result, snapshot],
  );

  const run = () => runRMS(systemClassName, {
    correction,
    cutoff_Hz: correction ? cutoff_Hz : undefined,
    maxStep_s: maxStep_ms !== undefined ? maxStep_ms / 1e3 : undefined,
  });

  return (
    <section className="transient-panel rms-panel">
      <aside className="transient-controls">
        <div className="transient-control-heading">
          <span className="transient-kicker">Analysis setup</span>
          <h2>RMS simulation</h2>
          <p>Phasor model in a global DQ frame: network and fast filter states are algebraic, only slow dynamics are integrated.</p>
        </div>

        <label className="rms-check">
          <input
            type="checkbox"
            checked={correction}
            disabled={busy}
            onChange={(event) => setCorrection(event.target.checked)}
          />
          <span>RMS+Δ correction</span>
        </label>
        <span className="transient-field-note">First-order correction of the electrical states along the RMS trajectory.</span>

        <label htmlFor="rms-cutoff">Correction cutoff (Hz)</label>
        <input
          id="rms-cutoff"
          type="number"
          min="1"
          step="100"
          value={cutoffText}
          disabled={busy || !correction}
          onChange={(event) => setCutoffText(event.target.value)}
        />
        <span className="transient-field-note">Faster modes keep their quasi-static response.</span>

        <label htmlFor="rms-max-step">Max step (ms)</label>
        <input
          id="rms-max-step"
          type="number"
          min="0"
          step="0.5"
          placeholder="1 (default)"
          value={maxStepText}
          disabled={busy}
          onChange={(event) => setMaxStepText(event.target.value)}
        />
        <span className="transient-field-note">End time, output step and breakpoints follow the system parameters.</span>

        <button
          type="button"
          className="transient-run-button"
          disabled={busy || !inputsValid || !isInsideVsCode()}
          onClick={run}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7V5Z" /></svg>
          {running ? 'Simulating…' : result ? 'Rerun RMS' : 'Run RMS'}
        </button>
        {!isInsideVsCode() && <span className="transient-field-note">Runs are available inside VS Code.</span>}
        {error && <p className="rms-error">{error}</p>}

        {result && (
          <>
            <div className="transient-divider" />
            <div className="transient-diagnostics">
              <div><span>Model</span><strong>{result.model === 'RMS+Delta' ? 'RMS+Δ' : 'RMS'}</strong></div>
              <div><span>RMS wall time</span><strong>{formatSeconds(result.simulationTime_s)}</strong></div>
              {result.model === 'RMS+Delta' && (
                <div><span>Correction time</span><strong>{formatSeconds(result.correctionTime_s)}</strong></div>
              )}
              <div><span>Samples</span><strong>{result.time_s.length}</strong></div>
              <div><span>Differential states</span><strong>{result.differentialStateNames.length}</strong></div>
              <div><span>Algebraic states</span><strong>{result.algebraicStateNames.length}</strong></div>
              <div>
                <span>Max algebraic residual</span>
                <strong className={result.maxAlgebraicResidual > residualWarning ? 'warning' : 'ok'}>
                  {result.maxAlgebraicResidual.toExponential(2)}
                </strong>
              </div>
              {result.model === 'RMS+Delta' && (
                <>
                  <div><span>Cutoff</span><strong>{result.cutoff_Hz} Hz</strong></div>
                  <div><span>Quasi-static modes (max)</span><strong>{result.maxQuasiStaticModeCount ?? 0}</strong></div>
                </>
              )}
            </div>
            <details className="rms-state-list">
              <summary>Differential states ({result.differentialStateNames.length})</summary>
              <ul>
                {result.differentialStateNames.map((name) => <li key={name}>{name}</li>)}
              </ul>
            </details>
            <p className="transient-explanation">
              Only these states carry dynamics in RMS. Corrected traces are labelled [RMS+Δ].
            </p>
          </>
        )}
      </aside>

      {plotSnapshot && result ? (
        <WaveformPanel key={result.model} snapshot={plotSnapshot} />
      ) : (
        <div className="transient-empty">
          <div className="transient-empty-icon" aria-hidden="true">
            <svg viewBox="0 0 48 48"><path d="M4 24c5-12 10-12 15 0s10 12 15 0 7-9 10-6" /></svg>
          </div>
          <h2>No RMS result yet</h2>
          <p>Run an RMS simulation of the selected system with the current parameters. Optionally add the RMS+Δ correction to recover the fast electrical response.</p>
        </div>
      )}
    </section>
  );
}
