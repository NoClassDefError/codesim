import { useMemo, useState } from 'react';
import type {
  ComplexValueDescriptor,
  InteractionAnalysisDescriptor,
  InteractionMatrixDescriptor,
  InteractionModeShift,
  SystemSnapshot,
} from '../model/types';
import { PoleZoomControls, usePolePan, usePoleZoom } from './PoleZoom';

type MatrixKey = keyof InteractionAnalysisDescriptor['matrices'];

const matrixOptions: Array<{ key: MatrixKey; label: string }> = [
  { key: 'dAll', label: 'Modal interaction matrix D′' },
  { key: 'aPartitioned', label: 'Partitioned state matrix' },
  { key: 'aBack', label: 'Reconstructed state matrix' },
  { key: 'aOriginal', label: 'Original state matrix' },
];

function formatNumber(value: number | null | undefined, digits = 4): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '—';
  }
  const magnitude = Math.abs(value);
  if ((magnitude > 0 && magnitude < 1e-3) || magnitude >= 1e4) {
    return value.toExponential(3);
  }
  return value.toFixed(digits).replace(/\.?0+$/, '');
}

function formatComplex(value: { realPart: number; imaginaryPart: number }): string {
  const sign = value.imaginaryPart >= 0 ? '+' : '−';
  return `${formatNumber(value.realPart)} ${sign} j${formatNumber(Math.abs(value.imaginaryPart))}`;
}

function heatColor(value: number, maximum: number): string {
  const ratio = maximum > 0
    ? Math.min(1, Math.max(0, Math.log10(1 + Math.abs(value)) / Math.log10(1 + maximum)))
    : 0;
  const red = Math.round(25 + ratio * 34);
  const green = Math.round(31 + ratio * 150);
  const blue = Math.round(42 + ratio * 205);
  return `rgb(${red}, ${green}, ${blue})`;
}

const polePlotWidth = 920;
const polePlotHeight = 500;
const polePlotMargin = { left: 86, right: 34, top: 30, bottom: 72 };

function parseComplex(value: string): ComplexValueDescriptor | null {
  const normalized = value.trim().replace(/\s/g, '').replace(/−/g, '-');
  const match = normalized.match(
    /^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)([+-](?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)j$/i,
  );
  if (!match) {
    return null;
  }
  const realPart = Number(match[1]);
  const imaginaryPart = Number(match[2]);
  if (!Number.isFinite(realPart) || !Number.isFinite(imaginaryPart)) {
    return null;
  }
  return { realPart, imaginaryPart, magnitude: Math.hypot(realPart, imaginaryPart) };
}

function validPoint(value: ComplexValueDescriptor | undefined): value is ComplexValueDescriptor {
  return Boolean(
    value
    && Number.isFinite(value.realPart)
    && Number.isFinite(value.imaginaryPart),
  );
}

function shiftPoint(
  mode: InteractionModeShift,
  key: 'localPoint' | 'fullPoint' | 'reducedPoint',
  fallback: 'localEigenvalue' | 'fullEigenvalue' | 'reducedEigenvalue',
): ComplexValueDescriptor | null {
  const point = mode[key];
  return validPoint(point) ? point : parseComplex(mode[fallback]);
}

function signedLog(value: number): number {
  return Math.sign(value) * Math.log10(1 + Math.abs(value));
}

function inverseSignedLog(value: number): number {
  return Math.sign(value) * (10 ** Math.abs(value) - 1);
}

function paddedLogExtent(values: number[]): [number, number] {
  let minimum = Math.min(0, ...values);
  let maximum = Math.max(0, ...values);
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {
    return [-1, 1];
  }
  if (minimum === maximum) {
    const padding = Math.max(Math.abs(minimum) * 0.12, 0.25);
    return [minimum - padding, maximum + padding];
  }
  const padding = Math.max((maximum - minimum) * 0.1, 0.04);
  return [minimum - padding, maximum + padding];
}

function PoleShiftPlot({ modes }: { modes: InteractionModeShift[] }) {
  const points = useMemo(() => modes.map((mode) => ({
    mode,
    local: shiftPoint(mode, 'localPoint', 'localEigenvalue'),
    full: shiftPoint(mode, 'fullPoint', 'fullEigenvalue'),
    reduced: shiftPoint(mode, 'reducedPoint', 'reducedEigenvalue'),
  })).filter((item) => item.local && item.full && item.reduced), [modes]);

  const baseRanges = useMemo(() => {
    const allPoints = points.flatMap((item) => [item.local, item.full, item.reduced])
      .filter((point): point is ComplexValueDescriptor => point !== null);
    return {
      x: paddedLogExtent(allPoints.map((point) => signedLog(point.realPart))),
      y: paddedLogExtent(allPoints.map((point) => signedLog(point.imaginaryPart))),
    };
  }, [points]);
  const zoom = usePoleZoom(baseRanges);
  const ranges = zoom.ranges;
  const plotWidth = polePlotWidth - polePlotMargin.left - polePlotMargin.right;
  const plotHeight = polePlotHeight - polePlotMargin.top - polePlotMargin.bottom;
  const pan = usePolePan({
    enabled: zoom.canZoomOut,
    svgWidth: polePlotWidth,
    svgHeight: polePlotHeight,
    plotWidth,
    plotHeight,
    onPan: zoom.panBy,
  });

  if (points.length === 0) {
    return (
      <section className="interaction-pole-card">
        <h2>Pole movement</h2>
        <div className="plot-empty">No numeric eigenvalue data is available.</div>
      </section>
    );
  }

  const x = (value: number) => polePlotMargin.left
    + ((signedLog(value) - ranges.x[0]) / (ranges.x[1] - ranges.x[0])) * plotWidth;
  const y = (value: number) => polePlotMargin.top
    + (1 - (signedLog(value) - ranges.y[0]) / (ranges.y[1] - ranges.y[0])) * plotHeight;
  const ticks = Array.from({ length: 7 }, (_, index) => index / 6);

  return (
    <section className="interaction-pole-card">
      <div className="pole-card-heading">
        <h2>Pole movement</h2>
        <PoleZoomControls
          scale={zoom.scale}
          canZoomIn={zoom.canZoomIn}
          canZoomOut={zoom.canZoomOut}
          onZoomIn={zoom.zoomIn}
          onZoomOut={zoom.zoomOut}
          onReset={zoom.reset}
        />
      </div>
      <div className="interaction-pole-scroll">
        <svg
          className={`interaction-pole-plot pole-pan-surface${zoom.canZoomOut ? ' can-pan' : ''}${pan.dragging ? ' dragging' : ''}`}
          viewBox={`0 0 ${polePlotWidth} ${polePlotHeight}`}
          aria-label="Interaction-analysis pole movement"
          onDoubleClick={zoom.reset}
          onPointerDown={pan.onPointerDown}
          onPointerMove={pan.onPointerMove}
          onPointerUp={pan.onPointerUp}
          onPointerCancel={pan.onPointerCancel}
        >
          <defs>
            <clipPath id="interaction-pole-clip">
              <rect x={polePlotMargin.left} y={polePlotMargin.top} width={plotWidth} height={plotHeight} />
            </clipPath>
            <marker id="interaction-arrow-full" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 8 4 L 0 8 z" className="interaction-arrow-full-head" />
            </marker>
            <marker id="interaction-arrow-reduced" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 8 4 L 0 8 z" className="interaction-arrow-reduced-head" />
            </marker>
          </defs>
          <rect className="chart-background" x={polePlotMargin.left} y={polePlotMargin.top} width={plotWidth} height={plotHeight} />
          {ticks.map((ratio) => {
            const logValue = ranges.x[0] + ratio * (ranges.x[1] - ranges.x[0]);
            const position = polePlotMargin.left + ratio * plotWidth;
            return (
              <g key={`pole-shift-x-${ratio}`}>
                <line className="chart-grid" x1={position} y1={polePlotMargin.top} x2={position} y2={polePlotHeight - polePlotMargin.bottom} />
                <text className="interaction-axis-tick" x={position} y={polePlotHeight - polePlotMargin.bottom + 22} textAnchor="middle">
                  {formatNumber(inverseSignedLog(logValue), 2)}
                </text>
              </g>
            );
          })}
          {ticks.map((ratio) => {
            const logValue = ranges.y[0] + ratio * (ranges.y[1] - ranges.y[0]);
            const position = polePlotMargin.top + (1 - ratio) * plotHeight;
            return (
              <g key={`pole-shift-y-${ratio}`}>
                <line className="chart-grid" x1={polePlotMargin.left} y1={position} x2={polePlotWidth - polePlotMargin.right} y2={position} />
                <text className="interaction-axis-tick" x={polePlotMargin.left - 11} y={position + 4} textAnchor="end">
                  {formatNumber(inverseSignedLog(logValue), 2)}
                </text>
              </g>
            );
          })}
          {ranges.x[0] <= 0 && ranges.x[1] >= 0 && (
            <line className="interaction-zero-axis" x1={x(0)} y1={polePlotMargin.top} x2={x(0)} y2={polePlotHeight - polePlotMargin.bottom} />
          )}
          {ranges.y[0] <= 0 && ranges.y[1] >= 0 && (
            <line className="interaction-zero-axis" x1={polePlotMargin.left} y1={y(0)} x2={polePlotWidth - polePlotMargin.right} y2={y(0)} />
          )}
          <g clipPath="url(#interaction-pole-clip)">
            {points.map(({ mode, local, full, reduced }) => {
              if (!local || !full || !reduced) {
                return null;
              }
              const localX = x(local.realPart);
              const localY = y(local.imaginaryPart);
              const fullX = x(full.realPart);
              const fullY = y(full.imaginaryPart);
              const reducedX = x(reduced.realPart);
              const reducedY = y(reduced.imaginaryPart);
              return (
                <g key={`pole-shift-${mode.mode}`} className="interaction-pole-mode">
                  <title>{`Mode ${mode.mode} · ${mode.relatedState || 'unassigned'}\nLocal: ${mode.localEigenvalue}\nActual: ${mode.fullEigenvalue}\nMasked: ${mode.reducedEigenvalue}`}</title>
                  <line className="interaction-shift-line full" x1={localX} y1={localY} x2={fullX} y2={fullY} markerEnd="url(#interaction-arrow-full)" />
                  <line className="interaction-shift-line reduced" x1={localX} y1={localY} x2={reducedX} y2={reducedY} markerEnd="url(#interaction-arrow-reduced)" />
                  <path className="interaction-pole-local" d={`M ${localX - 4} ${localY - 4} L ${localX + 4} ${localY + 4} M ${localX - 4} ${localY + 4} L ${localX + 4} ${localY - 4}`} />
                  <circle className="interaction-pole-full" cx={fullX} cy={fullY} r="4.5" />
                  <circle className="interaction-pole-reduced" cx={reducedX} cy={reducedY} r="3.5" />
                </g>
              );
            })}
          </g>
          <text className="interaction-axis-label" x={polePlotWidth / 2} y={polePlotHeight - 14} textAnchor="middle">Real(λ)</text>
          <text className="interaction-axis-label" x={20} y={polePlotHeight / 2} textAnchor="middle" transform={`rotate(-90 20 ${polePlotHeight / 2})`}>Imag(λ)</text>
        </svg>
      </div>
      <div className="interaction-pole-legend">
        <span className="local">× Local Λ′</span>
        <span className="full">○ Actual Λ</span>
        <span className="reduced">○ Masked Λ′</span>
        <span className="interaction-log-note">Signed-log axes</span>
        <span className="pole-zoom-hint">Drag to pan · double-click to reset</span>
      </div>
    </section>
  );
}

function InteractionHeatmap({
  matrix,
  title,
}: {
  matrix: InteractionMatrixDescriptor;
  title: string;
}) {
  const rows = matrix.magnitude.length;
  const columns = matrix.magnitude[0]?.length ?? 0;
  const cellSize = Math.max(15, Math.min(25, 500 / Math.max(rows, columns, 1)));
  const margin = { left: 86, right: 26, top: 46, bottom: 76 };
  const width = margin.left + columns * cellSize + margin.right;
  const height = margin.top + rows * cellSize + margin.bottom;
  const maximum = useMemo(
    () => Math.max(0, ...matrix.magnitude.flat().filter(Number.isFinite)),
    [matrix.magnitude],
  );
  const rowStep = Math.max(1, Math.ceil(rows / 12));
  const columnStep = Math.max(1, Math.ceil(columns / 12));

  return (
    <section className="interaction-matrix-card">
      <h2>{title}</h2>
      <div className="interaction-matrix-scroll">
        <svg
          className="interaction-heatmap"
          viewBox={`0 0 ${width} ${height}`}
          aria-label={title}
        >
          <rect
            className="chart-background"
            x={margin.left}
            y={margin.top}
            width={columns * cellSize}
            height={rows * cellSize}
          />
          {matrix.magnitude.map((row, rowIndex) => row.map((value, columnIndex) => {
            const real = matrix.real[rowIndex]?.[columnIndex] ?? 0;
            const imaginary = matrix.imaginary[rowIndex]?.[columnIndex] ?? 0;
            return (
              <rect
                key={`${rowIndex}-${columnIndex}`}
                className="interaction-cell"
                x={margin.left + columnIndex * cellSize}
                y={margin.top + rowIndex * cellSize}
                width={cellSize}
                height={cellSize}
                fill={heatColor(value, maximum)}
              >
                <title>{`${matrix.rowLabels[rowIndex] ?? rowIndex + 1} ← ${matrix.columnLabels[columnIndex] ?? columnIndex + 1}: ${formatNumber(real)} ${imaginary >= 0 ? '+' : '−'} j${formatNumber(Math.abs(imaginary))}; |·|=${formatNumber(value)}`}</title>
              </rect>
            );
          }))}
          {matrix.rowLabels.map((label, index) => (
            index % rowStep === 0 ? (
              <text
                key={`row-${index}`}
                className="interaction-axis-tick"
                x={margin.left - 8}
                y={margin.top + (index + 0.67) * cellSize}
                textAnchor="end"
              >
                {label}
              </text>
            ) : null
          ))}
          {matrix.columnLabels.map((label, index) => (
            index % columnStep === 0 ? (
              <text
                key={`column-${index}`}
                className="interaction-axis-tick"
                x={margin.left + (index + 0.5) * cellSize}
                y={margin.top + rows * cellSize + 10}
                textAnchor="end"
                transform={`rotate(-55 ${margin.left + (index + 0.5) * cellSize} ${margin.top + rows * cellSize + 10})`}
              >
                {label}
              </text>
            ) : null
          ))}
          <text
            className="interaction-axis-label"
            x={margin.left + (columns * cellSize) / 2}
            y={height - 10}
            textAnchor="middle"
          >
            Source mode / state
          </text>
          <text
            className="interaction-axis-label"
            x={18}
            y={margin.top + (rows * cellSize) / 2}
            textAnchor="middle"
            transform={`rotate(-90 18 ${margin.top + (rows * cellSize) / 2})`}
          >
            Affected mode / state
          </text>
        </svg>
      </div>
      <div className="interaction-scale">
        <span>0</span>
        <span className="interaction-scale-bar" />
        <span>{formatNumber(maximum)}</span>
        <span>|value|, logarithmic color</span>
      </div>
    </section>
  );
}

export function InteractionAnalysisPanel({ snapshot }: { snapshot: SystemSnapshot }) {
  const result = snapshot.interactionAnalysis;
  const [matrixKey, setMatrixKey] = useState<MatrixKey>('dAll');

  if (!result?.available) {
    return (
      <section className="interaction-empty">
        <h2>Interaction analysis</h2>
        <p>Run the model&apos;s interaction analysis and refresh the snapshot to display modal coupling.</p>
      </section>
    );
  }

  const matrix = result.matrices[matrixKey];
  const matrixTitle = matrixOptions.find((option) => option.key === matrixKey)?.label ?? matrixKey;

  return (
    <section className="interaction-panel">
      <div className="interaction-summary">
        <span><strong>{result.blocks.length}</strong> subsystem blocks</span>
        <span><strong>{result.modeShifts.length}</strong> tracked modes</span>
        <span>
          <strong>{result.parameterName || 'Parameter'}</strong>
          {' = '}{formatNumber(result.parameterValue)}
        </span>
        <span>
          Estimated shift <strong>{formatComplex(result.estimatedShift)}</strong>
        </span>
        <span>Reconstruction error <strong>{formatNumber(result.reconstructionErrorFro)}</strong></span>
      </div>

      <div className="interaction-blocks">
        {result.blocks.map((block) => (
          <span key={`${block.name}-${block.startMode}`}>
            <strong>{block.name}</strong> · modes {block.startMode}–{block.endMode}
          </span>
        ))}
        <span className="interaction-mask">
          Masked rows [{result.maskedRows.join(', ')}] ← columns [{result.maskedColumns.join(', ')}]
        </span>
      </div>

      <div className="interaction-content">
        <div className="interaction-matrix-toolbar">
          <label htmlFor="interaction-matrix">Displayed matrix</label>
          <select
            id="interaction-matrix"
            value={matrixKey}
            onChange={(event) => setMatrixKey(event.target.value as MatrixKey)}
          >
            {matrixOptions.map((option) => (
              <option key={option.key} value={option.key}>{option.label}</option>
            ))}
          </select>
        </div>
        <PoleShiftPlot modes={result.modeShifts} />
        <InteractionHeatmap matrix={matrix} title={matrixTitle} />

        <section className="interaction-table-card">
          <h2>Eigenvalue shifts</h2>
          <div className="mode-table-scroll">
            <table className="mode-table">
              <thead>
                <tr>
                  <th>Mode</th>
                  <th>Related state</th>
                  <th>Local λ</th>
                  <th>Full λ</th>
                  <th>Masked λ</th>
                  <th>Full − masked</th>
                </tr>
              </thead>
              <tbody>
                {result.modeShifts.map((mode) => (
                  <tr key={mode.mode}>
                    <td>{mode.mode}</td>
                    <td>{mode.relatedState || '—'}</td>
                    <td>{mode.localEigenvalue}</td>
                    <td>{mode.fullEigenvalue}</td>
                    <td>{mode.reducedEigenvalue}</td>
                    <td>{mode.deltaEigenvalue}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="interaction-table-card">
          <h2>Local modal summary</h2>
          <div className="mode-table-scroll">
            <table className="mode-table">
              <thead>
                <tr>
                  <th>Mode</th>
                  <th>Eigenvalue</th>
                  <th>Natural frequency</th>
                  <th>Damping ratio</th>
                  <th>Dominant state</th>
                </tr>
              </thead>
              <tbody>
                {result.localModes.map((mode) => (
                  <tr key={`${mode.mode}-${mode.label}`}>
                    <td>{mode.label || mode.mode}</td>
                    <td>{mode.eigenvalue}</td>
                    <td>{formatNumber(mode.naturalFrequency)}</td>
                    <td>{formatNumber(mode.dampingRatio)}</td>
                    <td>{mode.dominantState || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </section>
  );
}
