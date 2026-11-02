import { useEffect, useMemo, useState, type PointerEvent } from 'react';
import {
  isInsideVsCode,
  onBackendStatus,
  runTransientVoltage,
} from '../bridge/vscode';
import type {
  ComplexTraceDescriptor,
  SignalDescriptor,
  SystemSnapshot,
  TransientVoltageDescriptor,
} from '../model/types';
import { decimatedPath } from '../model/chartMath';

type TraceMetric = 'magnitude' | 'real' | 'imaginary';
type VisibleComponent = 'actual' | 'reconstructed' | 'qss' | 'firstOrder' | 'emt';

const componentMeta: Array<{
  key: VisibleComponent;
  label: string;
  shortLabel: string;
  description: string;
  color: string;
  dash?: string;
}> = [
  {
    key: 'actual',
    label: 'Actual voltage',
    shortLabel: 'Actual',
    description: 'Full nonlinear simulation',
    color: '#d7dae0',
  },
  {
    key: 'reconstructed',
    label: 'Reconstructed sum',
    shortLabel: 'Sum',
    description: 'QSS + first order + EMT',
    color: '#73c991',
    dash: '4 3',
  },
  {
    key: 'qss',
    label: 'QSS voltage',
    shortLabel: 'QSS',
    description: 'Fast states at equilibrium',
    color: '#4fc1ff',
  },
  {
    key: 'firstOrder',
    label: 'First-order component',
    shortLabel: 'First order',
    description: 'Linear tracking-lag correction',
    color: '#c586e0',
    dash: '8 5',
  },
  {
    key: 'emt',
    label: 'Fast EMT component',
    shortLabel: 'EMT',
    description: 'Fast-state replay residual',
    color: '#ffb454',
  },
];

const chartWidth = 1060;
const chartHeight = 390;
const chartMargin = { left: 72, right: 28, top: 24, bottom: 54 };
const stateChartHeight = 280;
const stateChartMargin = { left: 72, right: 28, top: 18, bottom: 54 };
const stateColors = [
  '#4fc1ff', '#c586e0', '#ffb454', '#73c991',
  '#f48771', '#dcdcaa', '#9cdcfe', '#ce9178',
];

interface SlowStateSeries {
  name: string;
  unit: string;
  time: number[];
  values: number[];
  color: string;
}

function formatNumber(value: number | null | undefined, digits = 5): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '—';
  }
  const magnitude = Math.abs(value);
  if ((magnitude > 0 && magnitude < 1e-4) || magnitude >= 1e4) {
    return value.toExponential(3);
  }
  return value.toFixed(digits).replace(/\.?0+$/, '');
}

function finiteExtent(...arrays: ReadonlyArray<readonly number[]>): [number, number] {
  let minimum = Number.POSITIVE_INFINITY;
  let maximum = Number.NEGATIVE_INFINITY;
  for (const values of arrays) {
    for (const value of values) {
      if (Number.isFinite(value)) {
        if (value < minimum) {
          minimum = value;
        }
        if (value > maximum) {
          maximum = value;
        }
      }
    }
  }
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {
    return [-1, 1];
  }
  if (minimum === maximum) {
    const padding = Math.max(Math.abs(minimum) * 0.08, 0.01);
    minimum -= padding;
    maximum += padding;
  } else {
    const padding = (maximum - minimum) * 0.08;
    minimum -= padding;
    maximum += padding;
  }
  return [minimum, maximum];
}

function column(trace: ComplexTraceDescriptor, metric: TraceMetric, busIndex: number): number[] {
  return trace[metric].map((row) => {
    const value = row[busIndex];
    return typeof value === 'number' ? value : Number.NaN;
  });
}

function nearestSample(time: number[], target: number): number {
  if (time.length < 2) {
    return 0;
  }
  let low = 0;
  let high = time.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (time[middle] < target) {
      low = middle + 1;
    } else {
      high = middle;
    }
  }
  if (low > 0 && Math.abs(time[low - 1] - target) < Math.abs(time[low] - target)) {
    return low - 1;
  }
  return low;
}

// Time slots per trace; each keeps up to four samples (first/min/max/last).
const traceBuckets = 700;

function linearScale(
  domain: [number, number],
  start: number,
  length: number,
  inverted = false,
): (value: number) => number {
  const span = domain[1] - domain[0];
  return inverted
    ? (value) => start + (1 - (value - domain[0]) / span) * length
    : (value) => start + ((value - domain[0]) / span) * length;
}

function valueAt(
  result: TransientVoltageDescriptor,
  key: keyof TransientVoltageDescriptor['components'],
  metric: TraceMetric,
  busIndex: number,
  sampleIndex: number,
): number {
  const value = result.components[key][metric][sampleIndex]?.[busIndex];
  return typeof value === 'number' ? value : Number.NaN;
}

function VoltageChart({
  result,
  busIndex,
  metric,
  visible,
  selectedIndex,
  onSelect,
}: {
  result: TransientVoltageDescriptor;
  busIndex: number;
  metric: TraceMetric;
  visible: Set<VisibleComponent>;
  selectedIndex: number;
  onSelect: (index: number) => void;
}) {
  const plotWidth = chartWidth - chartMargin.left - chartMargin.right;
  const plotHeight = chartHeight - chartMargin.top - chartMargin.bottom;
  // Traces only depend on the data and display options; dragging the cursor
  // re-renders just the cursor instead of rebuilding every path.
  const chart = useMemo(() => {
    const series = componentMeta
      .filter(({ key }) => visible.has(key))
      .map((meta) => ({ ...meta, values: column(result.components[meta.key], metric, busIndex) }));
    const timeRange = finiteExtent(result.time_s);
    const valueRange = finiteExtent(...series.map((item) => item.values));
    const x = linearScale(timeRange, chartMargin.left, plotWidth);
    const y = linearScale(valueRange, chartMargin.top, plotHeight, true);
    return {
      series: series.map((item) => ({
        ...item,
        path: decimatedPath(result.time_s, item.values, x, y, traceBuckets),
      })),
      timeRange,
      valueRange,
      x,
      y,
    };
  }, [busIndex, metric, plotHeight, plotWidth, result, visible]);
  const { series, x, y } = chart;
  const [timeMinimum, timeMaximum] = chart.timeRange;
  const [valueMinimum, valueMaximum] = chart.valueRange;
  const ticks = Array.from({ length: 6 }, (_, index) => index / 5);
  const cursorIndex = Math.min(Math.max(selectedIndex, 0), result.time_s.length - 1);
  const cursorTime = result.time_s[cursorIndex];

  const selectFromPointer = (event: PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const viewX = ((event.clientX - bounds.left) / bounds.width) * chartWidth;
    const ratio = Math.min(1, Math.max(0, (viewX - chartMargin.left) / plotWidth));
    onSelect(nearestSample(result.time_s, timeMinimum + ratio * (timeMaximum - timeMinimum)));
  };

  return (
    <div className="transient-chart-scroll">
      <svg
        className="transient-chart"
        viewBox={`0 0 ${chartWidth} ${chartHeight}`}
        aria-label={`Transient voltage ${metric} chart`}
        onPointerDown={selectFromPointer}
        onPointerMove={(event) => {
          if (event.buttons === 1) {
            selectFromPointer(event);
          }
        }}
      >
        <rect
          className="chart-background"
          x={chartMargin.left}
          y={chartMargin.top}
          width={plotWidth}
          height={plotHeight}
        />
        {ticks.map((ratio) => {
          const position = chartMargin.left + ratio * plotWidth;
          const value = timeMinimum + ratio * (timeMaximum - timeMinimum);
          return (
            <g key={`transient-x-${ratio}`}>
              <line className="chart-grid chart-grid-vertical" x1={position} y1={chartMargin.top} x2={position} y2={chartMargin.top + plotHeight} />
              <text className="transient-chart-tick" x={position} y={chartHeight - 28} textAnchor="middle">{formatNumber(value, 3)}</text>
            </g>
          );
        })}
        {ticks.map((ratio) => {
          const position = chartMargin.top + (1 - ratio) * plotHeight;
          const value = valueMinimum + ratio * (valueMaximum - valueMinimum);
          return (
            <g key={`transient-y-${ratio}`}>
              <line className="chart-grid" x1={chartMargin.left} y1={position} x2={chartMargin.left + plotWidth} y2={position} />
              <text className="transient-chart-tick" x={chartMargin.left - 11} y={position + 4} textAnchor="end">{formatNumber(value, 3)}</text>
            </g>
          );
        })}
        <line className="chart-axis" x1={chartMargin.left} y1={chartMargin.top + plotHeight} x2={chartMargin.left + plotWidth} y2={chartMargin.top + plotHeight} />
        <line className="chart-axis" x1={chartMargin.left} y1={chartMargin.top} x2={chartMargin.left} y2={chartMargin.top + plotHeight} />
        {series.map((item) => (
          <path
            key={item.key}
            className={`transient-trace transient-trace-${item.key}`}
            d={item.path}
            stroke={item.color}
            strokeDasharray={item.dash}
          />
        ))}
        {Number.isFinite(cursorTime) && (
          <g className="transient-cursor">
            <line x1={x(cursorTime)} y1={chartMargin.top} x2={x(cursorTime)} y2={chartMargin.top + plotHeight} />
            {series.map((item) => {
              const value = item.values[cursorIndex];
              return Number.isFinite(value) ? (
                <circle key={item.key} cx={x(cursorTime)} cy={y(value)} r="4" fill={item.color} />
              ) : null;
            })}
          </g>
        )}
        <text className="transient-chart-label" x={chartMargin.left + plotWidth / 2} y={chartHeight - 7} textAnchor="middle">Time (s)</text>
        <text className="transient-chart-label" x={18} y={chartMargin.top + plotHeight / 2} textAnchor="middle" transform={`rotate(-90 18 ${chartMargin.top + plotHeight / 2})`}>
          {metric === 'magnitude' ? '|V| (pu)' : metric === 'real' ? 'Re(V) (pu)' : 'Im(V) (pu)'}
        </text>
      </svg>
    </div>
  );
}

function SlowStateChart({
  analysisTime,
  series,
  selectedIndex,
  onSelect,
}: {
  analysisTime: number[];
  series: SlowStateSeries[];
  selectedIndex: number;
  onSelect: (index: number) => void;
}) {
  const plotWidth = chartWidth - stateChartMargin.left - stateChartMargin.right;
  const plotHeight = stateChartHeight - stateChartMargin.top - stateChartMargin.bottom;
  const chart = useMemo(() => {
    const timeRange = finiteExtent(analysisTime);
    const valueRange = finiteExtent(...series.map((item) => item.values));
    const x = linearScale(timeRange, stateChartMargin.left, plotWidth);
    const y = linearScale(valueRange, stateChartMargin.top, plotHeight, true);
    return {
      paths: new Map(series.map((item) => [
        item.name,
        decimatedPath(item.time, item.values, x, y, traceBuckets),
      ])),
      timeRange,
      valueRange,
      x,
      y,
    };
  }, [analysisTime, plotHeight, plotWidth, series]);
  const { x, y } = chart;
  const [timeMinimum, timeMaximum] = chart.timeRange;
  const [valueMinimum, valueMaximum] = chart.valueRange;
  const ticks = Array.from({ length: 6 }, (_, index) => index / 5);
  const cursorIndex = Math.min(Math.max(selectedIndex, 0), analysisTime.length - 1);
  const cursorTime = analysisTime[cursorIndex];

  const selectFromPointer = (event: PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const viewX = ((event.clientX - bounds.left) / bounds.width) * chartWidth;
    const ratio = Math.min(1, Math.max(
      0,
      (viewX - stateChartMargin.left) / plotWidth,
    ));
    onSelect(nearestSample(
      analysisTime,
      timeMinimum + ratio * (timeMaximum - timeMinimum),
    ));
  };

  return (
    <div className="transient-state-subplot">
      <div className="transient-subplot-heading">
        <div>
          <span className="transient-kicker">State trajectories</span>
          <h3>Selected slow states</h3>
        </div>
        <div className="transient-state-legend">
          {series.map((item) => {
            const sampleIndex = nearestSample(item.time, cursorTime);
            const value = item.values[sampleIndex];
            return (
              <span key={item.name}>
                <i style={{ background: item.color }} />
                <b>{item.name}</b>
                <em>{formatNumber(value)}{item.unit ? ` ${item.unit}` : ''}</em>
              </span>
            );
          })}
        </div>
      </div>
      {series.length === 0 ? (
        <div className="transient-state-empty">
          Select at least one available state to display its trajectory.
        </div>
      ) : (
        <div className="transient-chart-scroll">
          <svg
            className="transient-chart transient-state-chart"
            viewBox={`0 0 ${chartWidth} ${stateChartHeight}`}
            aria-label="Selected slow-state trajectories"
            onPointerDown={selectFromPointer}
            onPointerMove={(event) => {
              if (event.buttons === 1) {
                selectFromPointer(event);
              }
            }}
          >
            <rect
              className="chart-background"
              x={stateChartMargin.left}
              y={stateChartMargin.top}
              width={plotWidth}
              height={plotHeight}
            />
            {ticks.map((ratio) => {
              const position = stateChartMargin.left + ratio * plotWidth;
              const value = timeMinimum + ratio * (timeMaximum - timeMinimum);
              return (
                <g key={`state-x-${ratio}`}>
                  <line className="chart-grid chart-grid-vertical" x1={position} y1={stateChartMargin.top} x2={position} y2={stateChartMargin.top + plotHeight} />
                  <text className="transient-chart-tick" x={position} y={stateChartHeight - 28} textAnchor="middle">{formatNumber(value, 3)}</text>
                </g>
              );
            })}
            {ticks.map((ratio) => {
              const position = stateChartMargin.top + (1 - ratio) * plotHeight;
              const value = valueMinimum + ratio * (valueMaximum - valueMinimum);
              return (
                <g key={`state-y-${ratio}`}>
                  <line className="chart-grid" x1={stateChartMargin.left} y1={position} x2={stateChartMargin.left + plotWidth} y2={position} />
                  <text className="transient-chart-tick" x={stateChartMargin.left - 11} y={position + 4} textAnchor="end">{formatNumber(value, 3)}</text>
                </g>
              );
            })}
            <line className="chart-axis" x1={stateChartMargin.left} y1={stateChartMargin.top + plotHeight} x2={stateChartMargin.left + plotWidth} y2={stateChartMargin.top + plotHeight} />
            <line className="chart-axis" x1={stateChartMargin.left} y1={stateChartMargin.top} x2={stateChartMargin.left} y2={stateChartMargin.top + plotHeight} />
            {series.map((item) => (
              <path
                key={item.name}
                className="transient-trace transient-state-trace"
                d={chart.paths.get(item.name)}
                stroke={item.color}
              />
            ))}
            {Number.isFinite(cursorTime) && (
              <g className="transient-cursor">
                <line x1={x(cursorTime)} y1={stateChartMargin.top} x2={x(cursorTime)} y2={stateChartMargin.top + plotHeight} />
                {series.map((item) => {
                  const sampleIndex = nearestSample(item.time, cursorTime);
                  const sampleTime = item.time[sampleIndex];
                  const value = item.values[sampleIndex];
                  return Number.isFinite(sampleTime) && Number.isFinite(value) ? (
                    <circle key={item.name} cx={x(sampleTime)} cy={y(value)} r="4" fill={item.color} />
                  ) : null;
                })}
              </g>
            )}
            <text className="transient-chart-label" x={stateChartMargin.left + plotWidth / 2} y={stateChartHeight - 7} textAnchor="middle">Time (s)</text>
            <text className="transient-chart-label" x={18} y={stateChartMargin.top + plotHeight / 2} textAnchor="middle" transform={`rotate(-90 18 ${stateChartMargin.top + plotHeight / 2})`}>
              State value
            </text>
          </svg>
        </div>
      )}
    </div>
  );
}

export function TransientVoltagePanel({ snapshot }: { snapshot: SystemSnapshot }) {
  const result = snapshot.transientVoltage?.available
    ? snapshot.transientVoltage
    : undefined;
  const systemClassName = snapshot.system.className.split('.').at(-1)
    ?? snapshot.system.name;
  const stateNames = useMemo(
    () => Array.from(new Set(snapshot.signals
      .filter((signal) => signal.category === 'state')
      .map((signal) => signal.label))),
    [snapshot.signals],
  );
  const preferredState = stateNames.find((name) => name.toLowerCase().startsWith('delta'))
    ?? stateNames[0]
    ?? '';
  const [slowStates, setSlowStates] = useState<string[]>(() => {
    const available = (result?.requestedSlowStateNames ?? result?.slowStateNames ?? [])
      .filter((name) => stateNames.includes(name));
    return available.length > 0 ? available : preferredState ? [preferredState] : [];
  });
  const [maxSamples, setMaxSamples] = useState(100);
  const [busName, setBusName] = useState(result?.busNames[0] ?? '');
  const [metric, setMetric] = useState<TraceMetric>('magnitude');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [visible, setVisible] = useState<Set<VisibleComponent>>(
    new Set(['actual', 'reconstructed', 'qss', 'firstOrder', 'emt']),
  );
  const [busy, setBusy] = useState(false);
  const [decomposing, setDecomposing] = useState(false);
  const slowStateSeries = useMemo(() => slowStates
    .map((name) => {
      const signal = snapshot.signals.find(
        (candidate: SignalDescriptor) => (
          candidate.category === 'state' && candidate.label === name
        ),
      );
      if (!signal) {
        return undefined;
      }
      return {
        name,
        unit: signal.unit,
        time: signal.time,
        values: signal.values,
        color: stateColors[
          Math.max(0, stateNames.indexOf(name)) % stateColors.length
        ],
      };
    })
    .filter((item): item is SlowStateSeries => item !== undefined), [
      slowStates,
      snapshot.signals,
      stateNames,
    ]);

  useEffect(() => onBackendStatus((status) => {
    setBusy(status.running);
    setDecomposing(status.running && status.action === 'transientVoltage');
  }), []);

  useEffect(() => {
    setSlowStates((current) => {
      const available = current.filter((name) => stateNames.includes(name));
      if (available.length > 0) {
        return available.length === current.length ? current : available;
      }
      const previous = (result?.requestedSlowStateNames ?? result?.slowStateNames ?? [])
        .filter((name) => stateNames.includes(name));
      return previous.length > 0 ? previous : preferredState ? [preferredState] : [];
    });
  }, [preferredState, result?.requestedSlowStateNames, result?.slowStateNames, stateNames]);

  useEffect(() => {
    if (!result) {
      return;
    }
    if (!result.busNames.includes(busName)) {
      setBusName(result.busNames[0] ?? '');
    }
    const busIndex = Math.max(0, result.busNames.indexOf(busName));
    const actual = column(result.components.actual, 'magnitude', busIndex);
    const reconstructed = column(result.components.reconstructed, 'magnitude', busIndex);
    let maximumIndex = 0;
    let maximumError = -1;
    actual.forEach((value, index) => {
      const error = Math.abs(value - (reconstructed[index] ?? value));
      if (Number.isFinite(error) && error > maximumError) {
        maximumError = error;
        maximumIndex = index;
      }
    });
    setSelectedIndex(maximumIndex);
  }, [busName, result]);

  const busIndex = Math.max(0, result?.busNames.indexOf(busName) ?? 0);
  const safeIndex = result
    ? Math.min(selectedIndex, Math.max(0, result.time_s.length - 1))
    : 0;
  // Summary figures depend only on the result, not on the scrubbed sample.
  const diagnostics = useMemo(() => {
    if (!result) {
      return { convergedCount: 0, firstOrderCount: 0, worstResidual: 0, worstReconstruction: 0 };
    }
    let worstReconstruction = 0;
    // A loop rather than Math.max(...values): spreading a large
    // samples × buses matrix into arguments overflows the call stack.
    for (const row of result.components.reconstructionError.magnitude) {
      for (const value of row) {
        if (typeof value === 'number' && Number.isFinite(value) && value > worstReconstruction) {
          worstReconstruction = value;
        }
      }
    }
    return {
      convergedCount: result.qssConverged.filter(Boolean).length,
      firstOrderCount: result.firstOrderAvailable?.filter(Boolean).length ?? result.time_s.length,
      worstResidual: result.qssResidualNorm.reduce(
        (maximum, value) => Number.isFinite(value) ? Math.max(maximum, value) : maximum,
        0,
      ),
      worstReconstruction,
    };
  }, [result]);
  const { convergedCount, firstOrderCount, worstResidual, worstReconstruction } = diagnostics;
  const toggle = (key: VisibleComponent) => {
    setVisible((current) => {
      const next = new Set(current);
      if (next.has(key) && next.size > 1) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };
  const toggleSlowState = (name: string) => {
    setSlowStates((current) => current.includes(name)
      ? current.filter((item) => item !== name)
      : [...current, name]);
  };

  return (
    <section className="transient-panel">
      <aside className="transient-controls">
        <div className="transient-control-heading">
          <span className="transient-kicker">Analysis setup</span>
          <h2>Voltage decomposition</h2>
          <p>Use selected slow-state trajectories to separate equilibrium tracking from fast EMT behavior.</p>
        </div>
        <fieldset className="transient-state-picker" disabled={busy || stateNames.length === 0}>
          <legend>Slow states</legend>
          <div>
            {stateNames.length === 0 ? (
              <span>Run a simulation first</span>
            ) : stateNames.map((name) => (
              <label key={name}>
                <input
                  type="checkbox"
                  checked={slowStates.includes(name)}
                  onChange={() => toggleSlowState(name)}
                />
                <span>{name}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <span className="transient-field-note">Selected states follow the simulation trajectory and drive the first-order correction.</span>
        <label htmlFor="transient-max-samples">Analysis samples</label>
        <input
          id="transient-max-samples"
          type="number"
          min="1"
          step="1"
          value={maxSamples}
          disabled={busy}
          onChange={(event) => setMaxSamples(Math.max(1, Math.floor(Number(event.target.value) || 1)))}
        />
        <span className="transient-field-note">The EMT replay uses the full trajectory; QSS is evaluated at up to this many samples.</span>
        <button
          type="button"
          className="transient-run-button"
          disabled={slowStates.length === 0 || busy || !isInsideVsCode()}
          onClick={() => runTransientVoltage(systemClassName, slowStates, maxSamples)}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7V5Z" /></svg>
          {decomposing ? 'Decomposing…' : result ? 'Recompute' : 'Run decomposition'}
        </button>
        {!isInsideVsCode() && <span className="transient-field-note">Preview data is shown in the browser.</span>}

        {result?.available && (
          <>
            <div className="transient-divider" />
            <label htmlFor="transient-bus">Inspected bus</label>
            <select id="transient-bus" value={busName} onChange={(event) => setBusName(event.target.value)}>
              {result.busNames.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
            <div className="transient-diagnostics">
              <div><span>Fast states</span><strong>{result.fastStateNames.length}</strong></div>
              <div><span>Analysis samples</span><strong>{result.time_s.length}/{result.sourceSampleCount ?? result.time_s.length}</strong></div>
              <div><span>QSS solved</span><strong className={convergedCount === result.time_s.length ? 'ok' : 'warning'}>{convergedCount}/{result.time_s.length}</strong></div>
              <div><span>First order</span><strong className={firstOrderCount === result.time_s.length ? 'ok' : 'warning'}>{firstOrderCount}/{result.time_s.length}</strong></div>
              <div><span>Worst solved residual</span><strong>{formatNumber(worstResidual, 3)}</strong></div>
              <div><span>Valid replay error</span><strong>{formatNumber(worstReconstruction, 3)} pu</strong></div>
            </div>
            <p className="transient-explanation">
              Where QSS converges, QSS + first order + EMT equals the replayed complex voltage. Replay error compares it with the original simulation.
            </p>
          </>
        )}
      </aside>

      {!result?.available ? (
        <div className="transient-empty">
          <div className="transient-empty-icon" aria-hidden="true">
            <svg viewBox="0 0 48 48"><path d="M5 27h8l5-15 10 28 6-19 4 9h5" /></svg>
          </div>
          <h2>Inspect three voltage time scales</h2>
          <p>Run a time-domain simulation, select its slow states, then calculate the QSS, first-order, and fast-state replay responses.</p>
          <div className="transient-method-preview">
            <span><i className="qss" />QSS equilibrium</span>
            <span><i className="first" />First-order lag</span>
            <span><i className="emt" />Fast EMT response</span>
          </div>
        </div>
      ) : (
        <div className="transient-content">
          <div className="transient-topline">
            <div>
              <span className="transient-kicker">{busName || 'Bus'}</span>
              <h2>Component comparison</h2>
            </div>
            <div className="transient-metric-switch" role="group" aria-label="Complex voltage component">
              {(['magnitude', 'real', 'imaginary'] as TraceMetric[]).map((option) => (
                <button
                  key={option}
                  type="button"
                  className={metric === option ? 'active' : ''}
                  onClick={() => setMetric(option)}
                >
                  {option === 'magnitude' ? '|V|' : option === 'real' ? 'Real' : 'Imag'}
                </button>
              ))}
            </div>
          </div>

          <section className="transient-chart-card">
            <VoltageChart
              result={result}
              busIndex={busIndex}
              metric={metric}
              visible={visible}
              selectedIndex={safeIndex}
              onSelect={setSelectedIndex}
            />
            <SlowStateChart
              analysisTime={result.time_s}
              series={slowStateSeries}
              selectedIndex={safeIndex}
              onSelect={setSelectedIndex}
            />
            <div className="transient-time-scrubber">
              <span>{formatNumber(result.time_s[0], 3)} s</span>
              <input
                type="range"
                min="0"
                max={Math.max(0, result.time_s.length - 1)}
                value={safeIndex}
                onChange={(event) => setSelectedIndex(Number(event.target.value))}
                aria-label="Inspected time sample"
              />
              <output>{formatNumber(result.time_s[safeIndex], 5)} s</output>
            </div>
          </section>

          <div className="transient-component-grid">
            {componentMeta.map((component) => {
              const active = visible.has(component.key);
              const value = valueAt(result, component.key, metric, busIndex, safeIndex);
              const correction = valueAt(
                result, 'firstOrderError', metric, busIndex, safeIndex,
              );
              return (
                <button
                  key={component.key}
                  type="button"
                  className={`transient-component-card${active ? ' active' : ''}`}
                  onClick={() => toggle(component.key)}
                  aria-pressed={active}
                >
                  <span className="transient-component-title">
                    <i style={{ background: component.color }} />
                    {component.label}
                    <em>{active ? 'Visible' : 'Hidden'}</em>
                  </span>
                  <strong>{formatNumber(value)} <small>pu</small></strong>
                  <span>{component.description}</span>
                  {component.key === 'firstOrder' && (
                    <span className="transient-correction">ΔV: {formatNumber(correction)} pu</span>
                  )}
                </button>
              );
            })}
          </div>

          <div className="transient-sample-details">
            <span><small>Sample</small><strong>{safeIndex + 1} / {result.time_s.length}</strong></span>
            <span><small>QSS residual</small><strong>{formatNumber(result.qssResidualNorm[safeIndex], 3)}</strong></span>
            <span><small>Fast Jacobian κ</small><strong>{formatNumber(result.fastJacobianCondition[safeIndex], 3)}</strong></span>
            <span className={result.qssConverged[safeIndex] && (result.firstOrderAvailable?.[safeIndex] ?? true) ? 'sample-ok' : 'sample-warning'}>
              <small>Status</small>
              <strong>{
                !result.qssConverged[safeIndex]
                  ? 'QSS not converged'
                  : !(result.firstOrderAvailable?.[safeIndex] ?? true)
                    ? 'First order unavailable'
                    : 'Available'
              }</strong>
            </span>
          </div>
        </div>
      )}
    </section>
  );
}
