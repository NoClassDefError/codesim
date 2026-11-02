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

function appendInPlace(target: number[], source: readonly number[]): void {
  for (let index = 0; index < source.length; index += 1) {
    target.push(source[index]);
  }
}

/**
 * Accumulates streamed simulation chunks.
 *
 * Copying every trace on every chunk ([...old, ...chunk]) makes a run with N
 * samples cost O(N²) and allocates a fresh copy of every array per chunk.
 * Here each trace owns one array that grows in place, so a chunk costs only
 * its own length. React state receives new descriptor objects on each flush
 * (so memoized views notice the change) that share those growing arrays.
 */
export class SimulationSignalBuffer {
  private signals = new Map<string, SignalDescriptor>();
  private dirty = false;

  reset(initial: readonly SignalDescriptor[] = []): void {
    this.signals = new Map();
    this.append(initial, false);
    // A supplied snapshot is already displayed; only later chunks need a flush.
    this.dirty = false;
  }

  append(incoming: readonly SignalDescriptor[], reset: boolean): void {
    if (reset) {
      this.signals = new Map();
    }
    for (const signal of incoming) {
      const existing = this.signals.get(signal.id);
      if (existing) {
        appendInPlace(existing.time, signal.time);
        appendInPlace(existing.values, signal.values);
      } else {
        this.signals.set(signal.id, {
          ...signal,
          time: signal.time.slice(),
          values: signal.values.slice(),
        });
      }
    }
    this.dirty = true;
  }

  get pending(): boolean {
    return this.dirty;
  }

  /** Signals accumulated so far, or undefined when nothing changed since the last call. */
  take(): SignalDescriptor[] | undefined {
    if (!this.dirty) {
      return undefined;
    }
    this.dirty = false;
    return Array.from(this.signals.values(), (signal) => ({ ...signal }));
  }
}
