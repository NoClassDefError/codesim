import { useMemo, useState, type ReactNode } from 'react';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import type {
  SmallSignalMode,
  SymbolicExpressionDescriptor,
  SystemSnapshot,
} from '../model/types';
import { PoleZoomControls, usePolePan, usePoleZoom } from './PoleZoom';

const width = 820;
const height = 470;
const margin = { left: 78, right: 32, top: 28, bottom: 66 };

function paddedExtent(values: number[]): [number, number] {
  let minimum = Math.min(0, ...values);
  let maximum = Math.max(0, ...values);
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {
    return [-1, 1];
  }
  if (minimum === maximum) {
    const padding = Math.max(Math.abs(minimum) * 0.1, 1);
    return [minimum - padding, maximum + padding];
  }
  const padding = (maximum - minimum) * 0.1;
  return [minimum - padding, maximum + padding];
}

function formatNumber(value: number, digits = 4): string {
  const magnitude = Math.abs(value);
  if ((magnitude > 0 && magnitude < 1e-3) || magnitude >= 1e4) {
    return value.toExponential(3);
  }
  return value.toFixed(digits).replace(/\.?0+$/, '');
}

function eigenvalue(mode: SmallSignalMode): string {
  const sign = mode.imaginaryPart >= 0 ? '+' : '−';
  return `${formatNumber(mode.realPart)} ${sign} j${formatNumber(Math.abs(mode.imaginaryPart))}`;
}

// Symbolic matrices of larger systems produce very large KaTeX output, and the
// panel is re-mounted on every tab switch. Keep the last few renderings.
const latexCache = new Map<string, string>();
const latexCacheLimit = 12;

function renderLatex(expression: string): string {
  const cached = latexCache.get(expression);
  if (cached !== undefined) {
    latexCache.delete(expression);
    latexCache.set(expression, cached);
    return cached;
  }
  const markup = katex.renderToString(expression, {
    displayMode: true,
    throwOnError: false,
    strict: false,
    maxExpand: 10000,
  });
  latexCache.set(expression, markup);
  if (latexCache.size > latexCacheLimit) {
    latexCache.delete(latexCache.keys().next().value as string);
  }
  return markup;
}

function LatexExpression({ expression }: { expression: string }) {
  const markup = useMemo(() => renderLatex(expression), [expression]);

  return (
    <div
      className="symbolic-equation-latex"
      dangerouslySetInnerHTML={{ __html: markup }}
    />
  );
}

/** A <details> block that renders its body only once it has been opened. */
function LazyDetails({
  title,
  initiallyOpen,
  children,
}: {
  title: string;
  initiallyOpen: boolean;
  children: () => ReactNode;
}) {
  const [opened, setOpened] = useState(initiallyOpen);
  return (
    <details
      className="symbolic-equation"
      open={initiallyOpen}
      onToggle={(event) => {
        if (event.currentTarget.open) {
          setOpened(true);
        }
      }}
    >
      <summary>{title}</summary>
      {opened && children()}
    </details>
  );
}

function SymbolicExpressions({
  expressions,
}: {
  expressions: SymbolicExpressionDescriptor;
}) {
  const equations = [
    {
      id: 'a-sym',
      title: 'Symbolic state-space matrix A_sym',
      expression: String.raw`\mathbf{A}_{\mathrm{sym}} = ${expressions.aSymLatex}`,
      open: true,
    },
    {
      id: 'f',
      title: 'State equation f',
      expression: String.raw`\mathbf{f}(\mathbf{x},\mathbf{u}) = ${expressions.fLatex}`,
      open: false,
    },
    {
      id: 'g',
      title: 'Output equation g',
      expression: String.raw`\mathbf{g}(\mathbf{x},\mathbf{u}) = ${expressions.gLatex}`,
      open: false,
    },
  ];

  return (
    <section className="symbolic-equations-card">
      <h2>Symbolic model</h2>
      <p className="symbolic-equations-description">
        LaTeX expressions generated directly from RLGrid.A_sym, RLGrid.f and RLGrid.g.
      </p>
      <div className="symbolic-equations-list">
        {equations.map((equation) => (
          <LazyDetails
            key={equation.id}
            title={equation.title}
            initiallyOpen={equation.open}
          >
            {() => (
              <div className="symbolic-equation-scroll">
                <LatexExpression expression={equation.expression} />
              </div>
            )}
          </LazyDetails>
        ))}
      </div>
    </section>
  );
}

function PoleMap({ modes }: { modes: SmallSignalMode[] }) {
  const baseRanges = useMemo(() => ({
    x: paddedExtent(modes.map((mode) => mode.realPart)),
    y: paddedExtent(modes.map((mode) => mode.imaginaryPart)),
  }), [modes]);
  const zoom = usePoleZoom(baseRanges);
  const ranges = zoom.ranges;
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const pan = usePolePan({
    enabled: zoom.canZoomOut,
    svgWidth: width,
    svgHeight: height,
    plotWidth,
    plotHeight,
    onPan: zoom.panBy,
  });
  const x = (value: number) =>
    margin.left + ((value - ranges.x[0]) / (ranges.x[1] - ranges.x[0])) * plotWidth;
  const y = (value: number) =>
    margin.top + (1 - (value - ranges.y[0]) / (ranges.y[1] - ranges.y[0])) * plotHeight;
  const ticks = Array.from({ length: 7 }, (_, index) => index / 6);

  return (
    <section className="pole-map-card">
      <div className="pole-card-heading">
        <h2>Pole map</h2>
        <PoleZoomControls
          scale={zoom.scale}
          canZoomIn={zoom.canZoomIn}
          canZoomOut={zoom.canZoomOut}
          onZoomIn={zoom.zoomIn}
          onZoomOut={zoom.zoomOut}
          onReset={zoom.reset}
        />
      </div>
      <svg
        className={`pole-map pole-pan-surface${zoom.canZoomOut ? ' can-pan' : ''}${pan.dragging ? ' dragging' : ''}`}
        viewBox={`0 0 ${width} ${height}`}
        aria-label="Small-signal pole map"
        onDoubleClick={zoom.reset}
        onPointerDown={pan.onPointerDown}
        onPointerMove={pan.onPointerMove}
        onPointerUp={pan.onPointerUp}
        onPointerCancel={pan.onPointerCancel}
      >
        <defs>
          <clipPath id="small-signal-pole-clip">
            <rect x={margin.left} y={margin.top} width={plotWidth} height={plotHeight} />
          </clipPath>
        </defs>
        <rect
          className="chart-background"
          x={margin.left}
          y={margin.top}
          width={plotWidth}
          height={plotHeight}
        />
        {ticks.map((ratio) => {
          const value = ranges.x[0] + ratio * (ranges.x[1] - ranges.x[0]);
          const position = x(value);
          return (
            <g key={`x-${ratio}`}>
              <line className="chart-grid" x1={position} y1={margin.top} x2={position} y2={height - margin.bottom} />
              <text className="pole-tick" x={position} y={height - margin.bottom + 22} textAnchor="middle">
                {formatNumber(value, 2)}
              </text>
            </g>
          );
        })}
        {ticks.map((ratio) => {
          const value = ranges.y[0] + ratio * (ranges.y[1] - ranges.y[0]);
          const position = y(value);
          return (
            <g key={`y-${ratio}`}>
              <line className="chart-grid" x1={margin.left} y1={position} x2={width - margin.right} y2={position} />
              <text className="pole-tick" x={margin.left - 12} y={position + 5} textAnchor="end">
                {formatNumber(value, 2)}
              </text>
            </g>
          );
        })}
        {ranges.x[0] <= 0 && ranges.x[1] >= 0 && (
          <line className="pole-zero-axis" x1={x(0)} y1={margin.top} x2={x(0)} y2={height - margin.bottom} />
        )}
        {ranges.y[0] <= 0 && ranges.y[1] >= 0 && (
          <line className="pole-zero-axis" x1={margin.left} y1={y(0)} x2={width - margin.right} y2={y(0)} />
        )}
        <g clipPath="url(#small-signal-pole-clip)">
          {modes.map((mode) => {
            const cx = x(mode.realPart);
            const cy = y(mode.imaginaryPart);
            return (
              <g key={mode.mode} className={`pole-marker ${mode.stability.toLowerCase()}`}>
                <title>{`Mode ${mode.mode}: ${eigenvalue(mode)}; ${mode.stability}`}</title>
                <path d={`M ${cx - 6} ${cy - 6} L ${cx + 6} ${cy + 6} M ${cx - 6} ${cy + 6} L ${cx + 6} ${cy - 6}`} />
              </g>
            );
          })}
        </g>
        <text className="pole-axis-label" x={width / 2} y={height - 12} textAnchor="middle">
          Real part, Re(λ)
        </text>
        <text
          className="pole-axis-label"
          x={20}
          y={height / 2}
          textAnchor="middle"
          transform={`rotate(-90 20 ${height / 2})`}
        >
          Imaginary part, Im(λ)
        </text>
      </svg>
      <div className="pole-legend">
        <span className="stable">× Stable</span>
        <span className="marginal">× Marginal</span>
        <span className="unstable">× Unstable</span>
        <span className="pole-zoom-hint">Drag to pan · double-click to reset</span>
      </div>
    </section>
  );
}

export function SmallSignalPanel({ snapshot }: { snapshot: SystemSnapshot }) {
  const result = snapshot.smallSignal;
  const modes = result?.modes ?? [];

  if (!result?.available || modes.length === 0) {
    return (
      <section className="small-signal-empty">
        <h2>Small-signal analysis</h2>
        <p>Run the model&apos;s small-signal analysis and refresh the snapshot to display eigenvalues.</p>
      </section>
    );
  }

  return (
    <section className="small-signal-panel">
      <div className="small-signal-summary">
        <span><strong>{modes.length}</strong> modes</span>
        <span className={result.unstablePoleCount > 0 ? 'summary-unstable' : 'summary-stable'}>
          <strong>{result.unstablePoleCount}</strong> unstable
        </span>
        <span>{result.normalizedTime ? 'Normalized-time eigenvalues' : 'Eigenvalues'}</span>
      </div>
      <div className="small-signal-content">
        <PoleMap modes={modes} />
        <section className="mode-table-card">
          <h2>Eigenvalue list</h2>
          <div className="mode-table-scroll">
            <table className="mode-table">
              <thead>
                <tr>
                  <th>Mode</th>
                  <th>Eigenvalue</th>
                  <th>Frequency (Hz)</th>
                  <th>Damping</th>
                  <th>Stability</th>
                  <th>Dominant state</th>
                  <th>Participation</th>
                </tr>
              </thead>
              <tbody>
                {modes.map((mode) => (
                  <tr key={mode.mode} className={`mode-${mode.stability.toLowerCase()}`}>
                    <td>{mode.mode}</td>
                    <td>{eigenvalue(mode)}</td>
                    <td>{formatNumber(mode.frequencyHz)}</td>
                    <td>{formatNumber(mode.dampingRatio)}</td>
                    <td><span className="stability-badge">{mode.stability}</span></td>
                    <td>{mode.dominantState || '—'}</td>
                    <td>{formatNumber(mode.dominantParticipation)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        {result.symbolicExpressions && (
          <SymbolicExpressions expressions={result.symbolicExpressions} />
        )}
      </div>
    </section>
  );
}
