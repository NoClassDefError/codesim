import type { SignalDescriptor } from './types';

export interface PlotDefinition {
  id: string;
  title: string;
  signalIds: string[];
}

type DefaultPlotKind = 'voltage' | 'current' | 'power' | 'angle';

function signalKind(signal: SignalDescriptor): DefaultPlotKind | undefined {
  if (signal.category === 'state') {
    return undefined;
  }

  const id = signal.id.toLowerCase();
  const labelPrefix = signal.label.trim().toLowerCase().split('-', 1)[0].trim();
  if (
    labelPrefix === '|v|' ||
    id.includes('busvoltagemagnitude')
  ) {
    return 'voltage';
  }
  if (
    labelPrefix === 'i' ||
    id.includes('linecurrentmagnitude') ||
    id.includes('line-current')
  ) {
    return 'current';
  }
  if (
    labelPrefix === 'p' ||
    labelPrefix === 'q' ||
    id.includes('activepower') ||
    id.includes('reactivepower')
  ) {
    return 'power';
  }
  if (
    labelPrefix === 'theta' ||
    labelPrefix === 'θ' ||
    id.includes('busvoltageangledeg')
  ) {
    return 'angle';
  }
  return undefined;
}

export function defaultPlots(signals: SignalDescriptor[]): PlotDefinition[] {
  const idsFor = (kind: DefaultPlotKind) => signals
    .filter((signal) => signalKind(signal) === kind)
    .map((signal) => signal.id);

  return [
    {
      id: 'plot-voltage',
      title: 'Bus voltage magnitude',
      signalIds: idsFor('voltage'),
    },
    {
      id: 'plot-current',
      title: 'Line current',
      signalIds: idsFor('current'),
    },
    {
      id: 'plot-power',
      title: 'Device active / reactive power',
      signalIds: idsFor('power'),
    },
    {
      id: 'plot-angle',
      title: 'Bus voltage angle',
      signalIds: idsFor('angle'),
    },
  ];
}

export function mergeSimulationSignals(
  current: SignalDescriptor[],
  incoming: SignalDescriptor[],
  reset: boolean,
): SignalDescriptor[] {
  const signals = new Map(
    (reset ? [] : current).map((signal) => [signal.id, signal]),
  );
  for (const signal of incoming) {
    const existing = signals.get(signal.id);
    signals.set(signal.id, existing ? {
      ...existing,
      time: [...existing.time, ...signal.time],
      values: [...existing.values, ...signal.values],
    } : signal);
  }
  return [...signals.values()];
}
