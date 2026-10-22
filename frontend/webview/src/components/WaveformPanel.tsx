import { useEffect, useMemo, useRef, useState } from 'react';
import { SignalSidebar } from './SignalSidebar';
import type {
  DerivedSignalDefinition,
  SignalDescriptor,
  SignalOperation,
  SystemSnapshot,
} from '../model/types';
import { defaultPlots, type PlotDefinition } from '../model/signalModel';

const width = 1000;
const height = 224;
const margin = { left: 84, right: 84, top: 20, bottom: 42 };

interface ChartSeries {
  signal: SignalDescriptor;
  label: string;
  color: string;
  dashed?: boolean;
}

interface PlotPanelProps {
  active: boolean;
  title: string;
  yLabel: string;
  series: ChartSeries[];
  xRange: [number, number];
  rightSeries?: ChartSeries[];
  rightLabel?: string;
  selectedSignalId: string;
  onSelect: () => void;
  onClose: () => void;
  onRemoveSignal: (signalId: string) => void;
}

function finiteExtent(values: number[]): [number, number] {
  let minimum = Number.POSITIVE_INFINITY;
  let maximum = Number.NEGATIVE_INFINITY;
  for (const value of values) {
    if (Number.isFinite(value)) {
      minimum = Math.min(minimum, value);
      maximum = Math.max(maximum, value);
    }
  }
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {
    return [0, 1];
  }
  if (minimum === maximum) {
    const padding = Math.max(Math.abs(minimum) * 0.05, 0.05);
    minimum -= padding;
    maximum += padding;
  } else {
    const padding = (maximum - minimum) * 0.08;
    minimum -= padding;
    maximum += padding;
  }
  return [minimum, maximum];
}

function timeExtent(signals: SignalDescriptor[]): [number, number] {
  let minimum = Number.POSITIVE_INFINITY;
  let maximum = Number.NEGATIVE_INFINITY;
  for (const signal of signals) {
    for (const value of signal.time) {
      if (Number.isFinite(value)) {
        minimum = Math.min(minimum, value);
        maximum = Math.max(maximum, value);
      }
    }
  }
  return Number.isFinite(minimum) && Number.isFinite(maximum) && minimum !== maximum
    ? [minimum, maximum]
    : [0, 1];
}

function decimalPlacesForInterval(interval: number): number {
  const absolute = Math.abs(interval);
  if (!Number.isFinite(absolute) || absolute === 0) {
    return 2;
  }
  for (let places = 0; places <= 12; places += 1) {
    const scale = 10 ** places;
    const rounded = Math.round(absolute * scale) / scale;
    if (Math.abs(absolute - rounded) <= Math.max(absolute * 1e-9, 1e-15)) {
      return places;
    }
  }
  return 12;
}

function tickLabel(value: number, interval?: number): string {
  const magnitude = Math.abs(value);
  if (!Number.isFinite(value)) {
    return String(value);
  }
  if (interval !== undefined) {
    const places = decimalPlacesForInterval(interval);
    if (places > 10 || magnitude >= 1e9) {
      return value.toExponential(Math.min(6, Math.max(1, places - 1)));
    }
    return value.toFixed(places);
  }
  if ((magnitude > 0 && magnitude < 0.001) || magnitude >= 1000) {
    return value.toExponential(1);
  }
  return value.toFixed(magnitude < 10 ? 2 : 1).replace(/\.00$/, '');
}

function pointsFor(
  signal: SignalDescriptor,
  xRange: [number, number],
  yRange: [number, number],
): string {
  const count = Math.min(signal.time.length, signal.values.length);
  if (count === 0) {
    return '';
  }
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xSpan = Math.max(xRange[1] - xRange[0], 1e-12);
  const ySpan = Math.max(yRange[1] - yRange[0], 1e-12);
  let firstVisible = -1;
  let lastVisible = -1;
  for (let index = 0; index < count; index += 1) {
    if (
      Number.isFinite(signal.time[index]) &&
      Number.isFinite(signal.values[index]) &&
      signal.time[index] >= xRange[0] &&
      signal.time[index] <= xRange[1]
    ) {
      firstVisible = firstVisible < 0 ? index : firstVisible;
      lastVisible = index;
    }
  }
  if (firstVisible < 0) {
    return '';
  }

  const step = Math.max(1, Math.ceil((lastVisible - firstVisible + 1) / 900));
  const indices: number[] = [];
  for (let index = firstVisible; index <= lastVisible; index += step) {
    if (Number.isFinite(signal.time[index]) && Number.isFinite(signal.values[index])) {
      indices.push(index);
    }
  }
  if (indices.at(-1) !== lastVisible) {
    indices.push(lastVisible);
  }

  return indices
    .map((index) => {
      const x = margin.left + ((signal.time[index] - xRange[0]) / xSpan) * plotWidth;
      const y = margin.top + (1 - (signal.values[index] - yRange[0]) / ySpan) * plotHeight;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
}

function PlotPanel({
  active,
  title,
  yLabel,
  series,
  xRange,
  rightSeries = [],
  rightLabel,
  selectedSignalId,
  onSelect,
  onClose,
  onRemoveSignal,
}: PlotPanelProps) {
  const allSeries = [...series, ...rightSeries];
  const leftRange = finiteExtent(series.flatMap((item) => item.signal.values));
  const rightRange = finiteExtent(rightSeries.flatMap((item) => item.signal.values));
  const xTicks = Array.from({ length: 5 }, (_, index) =>
    xRange[0] + ((xRange[1] - xRange[0]) * index) / 4,
  );
  const xTickInterval = (xRange[1] - xRange[0]) / 4;
  const yTicks = Array.from({ length: 5 }, (_, index) =>
    leftRange[0] + ((leftRange[1] - leftRange[0]) * index) / 4,
  );
  const rightTicks = Array.from({ length: 5 }, (_, index) =>
    rightRange[0] + ((rightRange[1] - rightRange[0]) * index) / 4,
  );
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;

  return (
    <section
      className={active ? 'plot-card active' : 'plot-card'}
      onClick={onSelect}
    >
      <div className="plot-heading">
        <div className="plot-title">
          <span>{title}</span>
          <button
            type="button"
            className="plot-close"
            onClick={(event) => {
              event.stopPropagation();
              onClose();
            }}
            title={`Close ${title}`}
            aria-label={`Close ${title}`}
          >
            ×
          </button>
        </div>
        <div className="plot-legend">
          {allSeries.map((item) => (
            <button
              type="button"
              key={item.signal.id}
              className={item.signal.id === selectedSignalId ? 'selected' : ''}
              onClick={(event) => {
                event.stopPropagation();
                onRemoveSignal(item.signal.id);
              }}
              title={`Remove ${item.label} from ${title}`}
            >
              <i
                style={{
                  color: item.color,
                  borderStyle: item.dashed ? 'dashed' : 'solid',
                }}
              />
              {item.label}
              <b>×</b>
            </button>
          ))}
        </div>
      </div>
      {allSeries.length === 0 ? (
        <div className="plot-empty">No matching signal in this snapshot.</div>
      ) : (
        <svg className="signal-chart" viewBox={`0 0 ${width} ${height}`} aria-label={title}>
          <rect
            className="chart-background"
            x={margin.left}
            y={margin.top}
            width={plotWidth}
            height={plotHeight}
          />
          {yTicks.map((tick, index) => {
            const y = margin.top + plotHeight - (plotHeight * index) / 4;
            return (
              <g key={`y-${tick}`}>
                <line
                  className="chart-grid"
                  x1={margin.left}
                  y1={y}
                  x2={width - margin.right}
                  y2={y}
                />
                <text className="chart-tick" x={margin.left - 10} y={y + 4} textAnchor="end">
                  {tickLabel(tick)}
                </text>
              </g>
            );
          })}
          {xTicks.map((tick, index) => {
            const x = margin.left + (plotWidth * index) / 4;
            return (
              <g key={`x-${tick}`}>
                <line
                  className="chart-grid chart-grid-vertical"
                  x1={x}
                  y1={margin.top}
                  x2={x}
                  y2={height - margin.bottom}
                />
                <text className="chart-tick" x={x} y={height - 9} textAnchor="middle">
                  {tickLabel(tick, xTickInterval)}
                </text>
              </g>
            );
          })}
          <line
            className="chart-axis"
            x1={margin.left}
            y1={height - margin.bottom}
            x2={width - margin.right}
            y2={height - margin.bottom}
          />
          <line
            className="chart-axis"
            x1={margin.left}
            y1={margin.top}
            x2={margin.left}
            y2={height - margin.bottom}
          />
          {rightSeries.length > 0 && (
            <>
              <line
                className="chart-axis"
                x1={width - margin.right}
                y1={margin.top}
                x2={width - margin.right}
                y2={height - margin.bottom}
              />
              {rightTicks.map((tick, index) => {
                const y = margin.top + plotHeight - (plotHeight * index) / 4;
                return (
                  <text
                    className="chart-tick chart-tick-right"
                    key={`right-${tick}`}
                    x={width - margin.right + 10}
                    y={y + 4}
                  >
                    {tickLabel(tick)}
                  </text>
                );
              })}
            </>
          )}
          {series.map((item) => (
            <polyline
              key={item.signal.id}
              points={pointsFor(item.signal, xRange, leftRange)}
              className={item.signal.id === selectedSignalId ? 'chart-line selected' : 'chart-line'}
              style={{ stroke: item.color }}
              strokeDasharray={item.dashed ? '9 6' : undefined}
            />
          ))}
          {rightSeries.map((item) => (
            <polyline
              key={item.signal.id}
              points={pointsFor(item.signal, xRange, rightRange)}
              className={item.signal.id === selectedSignalId ? 'chart-line selected' : 'chart-line'}
              style={{ stroke: item.color }}
              strokeDasharray={item.dashed ? '9 6' : undefined}
            />
          ))}
          <text
            className="chart-label"
            x={18}
            y={height / 2}
            textAnchor="middle"
            transform={`rotate(-90 18 ${height / 2})`}
          >
            {yLabel}
          </text>
          {rightLabel && rightSeries.length > 0 && (
            <text
              className="chart-label chart-label-right"
              x={width - 15}
              y={height / 2}
              textAnchor="middle"
              transform={`rotate(90 ${width - 15} ${height / 2})`}
            >
              {rightLabel}
            </text>
          )}
          <text className="chart-label" x={width / 2} y={height - 1} textAnchor="middle">
            Time (s)
          </text>
        </svg>
      )}
    </section>
  );
}

function asSeries(
  signals: SignalDescriptor[],
  label: (signal: SignalDescriptor, index: number) => string,
): ChartSeries[] {
  return signals.map((signal, index) => ({
    signal,
    label: label(signal, index),
    color: `hsl(${(index * 137.508 + 198) % 360} 72% 64%)`,
  }));
}

interface Props {
  snapshot: SystemSnapshot;
}

export function WaveformPanel({ snapshot }: Props) {
  const [plots, setPlots] = useState<PlotDefinition[]>(() => defaultPlots(snapshot.signals));
  const [selectedPlotId, setSelectedPlotId] = useState('plot-voltage');
  const [selectedSignalId, setSelectedSignalId] = useState('');
  const [derivedDefinitions, setDerivedDefinitions] = useState<DerivedSignalDefinition[]>([]);
  const [layoutSystemId, setLayoutSystemId] = useState(snapshot.system.id);
  const [layoutInitialized, setLayoutInitialized] = useState(snapshot.signals.length > 0);
  const plotCounter = useRef(5);
  const calculationCounter = useRef(1);

  const allSignals = useMemo(() => {
    const signals = [...snapshot.signals];
    const signalsById = new Map(signals.map((signal) => [signal.id, signal]));
    for (const definition of derivedDefinitions) {
      const left = signalsById.get(definition.leftId);
      const right = signalsById.get(definition.rightId);
      if (!left || !right) {
        continue;
      }
      const count = Math.min(
        left.time.length,
        left.values.length,
        right.time.length,
        right.values.length,
      );
      const values = Array.from({ length: count }, (_, index) => {
        const a = left.values[index];
        const b = right.values[index];
        if (definition.operation === 'magnitude') {
          return Math.hypot(a, b);
        }
        return definition.operation === 'power' ? a * b : a - b;
      });
      const sameUnit = left.unit === right.unit ? left.unit : '';
      const unit = definition.operation === 'power'
        ? [left.unit, right.unit].filter(Boolean).join('·')
        : sameUnit;
      const signal: SignalDescriptor = {
        id: definition.id,
        ownerId: snapshot.system.id,
        ownerKind: 'system',
        category: 'output',
        label: definition.label,
        unit,
        time: left.time.slice(0, count),
        values,
      };
      signals.push(signal);
      signalsById.set(signal.id, signal);
    }
    return signals;
  }, [derivedDefinitions, snapshot.signals, snapshot.system.id]);
  const fullTimeRange = useMemo(() => timeExtent(allSignals), [allSignals]);
  const [visibleTimeRange, setVisibleTimeRange] = useState<[number, number]>(fullTimeRange);

  useEffect(() => {
    setVisibleTimeRange(fullTimeRange);
  }, [fullTimeRange]);

  useEffect(() => {
    if (snapshot.system.id !== layoutSystemId) {
      const next = defaultPlots(snapshot.signals);
      setPlots(next);
      setSelectedPlotId(next[0]?.id ?? '');
      setSelectedSignalId('');
      setDerivedDefinitions([]);
      setLayoutSystemId(snapshot.system.id);
      setLayoutInitialized(snapshot.signals.length > 0);
      calculationCounter.current = 1;
    } else if (snapshot.signals.length === 0) {
      setLayoutInitialized(false);
    } else if (!layoutInitialized && snapshot.signals.length > 0) {
      const next = defaultPlots(snapshot.signals);
      setPlots(next);
      setSelectedPlotId(next[0]?.id ?? '');
      setLayoutInitialized(true);
    }
  }, [layoutInitialized, layoutSystemId, snapshot.signals, snapshot.system.id]);

  const signalsById = useMemo(
    () => new Map(allSignals.map((signal) => [signal.id, signal])),
    [allSignals],
  );
  const selectedPlot = plots.find((plot) => plot.id === selectedPlotId);
  const assignedSignalIds = new Set(selectedPlot?.signalIds ?? []);

  const addPlot = () => {
    const id = `plot-custom-${plotCounter.current}`;
    const next = { id, title: `Plot ${plotCounter.current}`, signalIds: [] };
    plotCounter.current += 1;
    setPlots((current) => [...current, next]);
    setSelectedPlotId(id);
  };

  const closePlot = (plotId: string) => {
    const next = plots.filter((plot) => plot.id !== plotId);
    setPlots(next);
    if (selectedPlotId === plotId) {
      setSelectedPlotId(next[0]?.id ?? '');
    }
  };

  const addSignal = (signal: SignalDescriptor) => {
    setSelectedSignalId(signal.id);
    if (!selectedPlot) {
      const id = `plot-custom-${plotCounter.current}`;
      plotCounter.current += 1;
      setPlots((current) => [...current, { id, title: 'New plot', signalIds: [signal.id] }]);
      setSelectedPlotId(id);
      return;
    }
    setPlots((current) => current.map((plot) =>
      plot.id === selectedPlot.id && !plot.signalIds.includes(signal.id)
        ? { ...plot, signalIds: [...plot.signalIds, signal.id] }
        : plot,
    ));
  };

  const removeSignal = (plotId: string, signalId: string) => {
    setPlots((current) => current.map((plot) =>
      plot.id === plotId
        ? { ...plot, signalIds: plot.signalIds.filter((id) => id !== signalId) }
        : plot,
    ));
    if (selectedSignalId === signalId) {
      setSelectedSignalId('');
    }
  };

  const calculateSignal = (
    leftId: string,
    rightId: string,
    operation: SignalOperation,
  ) => {
    const left = signalsById.get(leftId);
    const right = signalsById.get(rightId);
    if (!left || !right) {
      return;
    }
    const symbol = operation === 'magnitude' ? '√' : operation === 'power' ? '×' : '−';
    const label = operation === 'magnitude'
      ? `√(${left.label}² + ${right.label}²)`
      : `${left.label} ${symbol} ${right.label}`;
    const id = `calculated-${operation}-${calculationCounter.current}`;
    calculationCounter.current += 1;
    setDerivedDefinitions((current) => [...current, {
      id,
      leftId,
      rightId,
      operation,
      label,
    }]);
    setSelectedSignalId(id);
    if (!selectedPlot) {
      const plotId = `plot-custom-${plotCounter.current}`;
      plotCounter.current += 1;
      setPlots((current) => [...current, { id: plotId, title: 'New plot', signalIds: [id] }]);
      setSelectedPlotId(plotId);
      return;
    }
    setPlots((current) => current.map((plot) =>
      plot.id === selectedPlot.id
        ? { ...plot, signalIds: [...plot.signalIds, id] }
        : plot,
    ));
  };

  const fullSpan = fullTimeRange[1] - fullTimeRange[0];
  const visibleSpan = visibleTimeRange[1] - visibleTimeRange[0];
  const availablePan = Math.max(0, fullSpan - visibleSpan);
  const panPosition = availablePan > 0
    ? ((visibleTimeRange[0] - fullTimeRange[0]) / availablePan) * 1000
    : 0;

  const zoomTime = (scale: number) => {
    setVisibleTimeRange(([start, end]) => {
      const minimumSpan = Math.max(fullSpan / 500, Number.EPSILON);
      const nextSpan = Math.min(fullSpan, Math.max(minimumSpan, (end - start) * scale));
      const center = (start + end) / 2;
      const nextStart = Math.min(
        fullTimeRange[1] - nextSpan,
        Math.max(fullTimeRange[0], center - nextSpan / 2),
      );
      return [nextStart, nextStart + nextSpan];
    });
  };

  const panTime = (position: number) => {
    const start = fullTimeRange[0] + (availablePan * position) / 1000;
    setVisibleTimeRange([start, start + visibleSpan]);
  };

  return (
    <section className="signals-workspace">
      <section className="waveform-panel" aria-label="Simulation plots">
        <div className="waveform-header">
          <div className="waveform-title">
            <strong>Simulation results</strong>
            <span>Select a plot, then add signals from the right</span>
          </div>
          <div className="time-controls" aria-label="Plot and time controls">
            <button type="button" onClick={addPlot} title="Create a new empty plot">
              + Plot
            </button>
            <button
              type="button"
              onClick={() => zoomTime(2)}
              disabled={visibleSpan >= fullSpan}
              title="Zoom out horizontally"
            >
              −
            </button>
            <button
              type="button"
              onClick={() => zoomTime(0.5)}
              disabled={visibleSpan <= fullSpan / 500}
              title="Zoom in horizontally"
            >
              +
            </button>
            <button
              type="button"
              onClick={() => setVisibleTimeRange(fullTimeRange)}
              disabled={visibleSpan >= fullSpan}
            >
              Reset
            </button>
            <input
              type="range"
              min="0"
              max="1000"
              step="1"
              value={panPosition}
              onChange={(event) => panTime(Number(event.target.value))}
              disabled={availablePan <= 0}
              aria-label="Pan visible time window"
              title="Pan visible time window"
            />
            <output>
              {tickLabel(visibleTimeRange[0])}–{tickLabel(visibleTimeRange[1])} s
            </output>
          </div>
        </div>
        <div className="plot-stack">
          {plots.length === 0 && (
            <div className="plot-layout-empty">
              <span>No plots in the layout.</span>
              <button type="button" onClick={addPlot}>Create plot</button>
            </div>
          )}
          {plots.map((plot) => {
            const plotSignals = plot.signalIds
              .map((id) => signalsById.get(id))
              .filter((signal): signal is SignalDescriptor => Boolean(signal));
            const units = new Set(plotSignals.map((signal) => signal.unit).filter(Boolean));
            const yLabel = units.size === 1 ? `Value (${[...units][0]})` : 'Value';
            return (
              <PlotPanel
                key={plot.id}
                active={plot.id === selectedPlotId}
                title={plot.title}
                yLabel={yLabel}
                series={asSeries(plotSignals, (signal) => signal.label)}
                xRange={visibleTimeRange}
                selectedSignalId={selectedSignalId}
                onSelect={() => setSelectedPlotId(plot.id)}
                onClose={() => closePlot(plot.id)}
                onRemoveSignal={(signalId) => removeSignal(plot.id, signalId)}
              />
            );
          })}
        </div>
      </section>
      <SignalSidebar
        snapshot={{ ...snapshot, signals: allSignals }}
        selectedSignalId={selectedSignalId}
        assignedSignalIds={assignedSignalIds}
        targetLabel={selectedPlot?.title ?? 'a new plot'}
        onSelect={addSignal}
        onCalculate={calculateSignal}
      />
    </section>
  );
}
