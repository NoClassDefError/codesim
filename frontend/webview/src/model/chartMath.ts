/**
 * Shared numeric helpers for the SVG charts.
 *
 * Simulation arrays are treated as append-only: streamed chunks are pushed
 * onto existing arrays and never rewritten in place. The caches below rely on
 * that, so they only scan the part of an array they have not seen yet.
 */

export type NumericRange = [number, number];

export interface ArrayStats {
  /** Number of leading entries already folded into these statistics. */
  length: number;
  /** Minimum over finite entries (Infinity when there are none). */
  minimum: number;
  /** Maximum over finite entries (-Infinity when there are none). */
  maximum: number;
  /** True while every entry is finite. */
  allFinite: boolean;
  /** True while finite entries never decrease. */
  ascending: boolean;
  lastFinite: number;
}

const statsCache = new WeakMap<readonly number[], ArrayStats>();

/** Incrementally maintained min/max/monotonicity of an append-only array. */
export function arrayStats(values: readonly number[]): ArrayStats {
  let stats = statsCache.get(values);
  if (!stats || stats.length > values.length) {
    stats = {
      length: 0,
      minimum: Number.POSITIVE_INFINITY,
      maximum: Number.NEGATIVE_INFINITY,
      allFinite: true,
      ascending: true,
      lastFinite: Number.NEGATIVE_INFINITY,
    };
    statsCache.set(values, stats);
  }
  for (let index = stats.length; index < values.length; index += 1) {
    const value = values[index];
    if (!Number.isFinite(value)) {
      stats.allFinite = false;
      continue;
    }
    if (value < stats.minimum) {
      stats.minimum = value;
    }
    if (value > stats.maximum) {
      stats.maximum = value;
    }
    if (value < stats.lastFinite) {
      stats.ascending = false;
    }
    stats.lastFinite = value;
  }
  stats.length = values.length;
  return stats;
}

/** First index in [low, high) whose value is >= target. */
export function lowerBound(
  values: readonly number[],
  target: number,
  low = 0,
  high = values.length,
): number {
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (values[middle] < target) {
      low = middle + 1;
    } else {
      high = middle;
    }
  }
  return low;
}

/** First index in [low, high) whose value is > target. */
export function upperBound(
  values: readonly number[],
  target: number,
  low = 0,
  high = values.length,
): number {
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (values[middle] <= target) {
      low = middle + 1;
    } else {
      high = middle;
    }
  }
  return low;
}

/**
 * Half-open index range [start, end) of samples whose time lies in
 * [minimum, maximum]. Uses binary search for sorted time axes (the normal
 * case) and falls back to a linear scan otherwise.
 */
export function visibleIndexRange(
  time: readonly number[],
  count: number,
  minimum: number,
  maximum: number,
): NumericRange {
  const stats = arrayStats(time);
  if (stats.ascending && stats.allFinite) {
    return [
      lowerBound(time, minimum, 0, count),
      upperBound(time, maximum, 0, count),
    ];
  }
  let first = -1;
  let last = -1;
  for (let index = 0; index < count; index += 1) {
    const value = time[index];
    if (Number.isFinite(value) && value >= minimum && value <= maximum) {
      first = first < 0 ? index : first;
      last = index;
    }
  }
  return first < 0 ? [0, 0] : [first, last + 1];
}

/**
 * Pick the sample indices to draw for [start, end).
 *
 * Short ranges are returned as-is. Longer ranges are split into `buckets`
 * time slots and each slot keeps its first, minimum, maximum and last sample,
 * so short spikes (fault instants, switching transients) survive the
 * reduction instead of being skipped by fixed-stride sampling.
 *
 * Non-finite samples break the line; a break is reported as -1.
 */
export function decimateIndices(
  time: readonly number[],
  values: readonly number[],
  start: number,
  end: number,
  buckets: number,
): number[] {
  const result: number[] = [];
  const count = end - start;
  if (count <= 0) {
    return result;
  }

  if (count <= buckets * 4) {
    let broken = false;
    for (let index = start; index < end; index += 1) {
      if (Number.isFinite(time[index]) && Number.isFinite(values[index])) {
        if (broken && result.length > 0) {
          result.push(-1);
        }
        broken = false;
        result.push(index);
      } else {
        broken = true;
      }
    }
    return result;
  }

  const startTime = time[start];
  const span = time[end - 1] - startTime;
  const byTime = Number.isFinite(startTime) && Number.isFinite(span) && span > 0;
  let bucket = -1;
  let first = -1;
  let low = -1;
  let high = -1;
  let last = -1;
  let broken = false;

  const flush = () => {
    if (first < 0) {
      return;
    }
    const picks = [first, low, high, last].sort((left, right) => left - right);
    let previous = -1;
    for (const pick of picks) {
      if (pick !== previous) {
        result.push(pick);
        previous = pick;
      }
    }
    first = -1;
  };

  for (let index = start; index < end; index += 1) {
    const sampleTime = time[index];
    const value = values[index];
    if (!Number.isFinite(sampleTime) || !Number.isFinite(value)) {
      flush();
      broken = true;
      continue;
    }
    const nextBucket = byTime
      ? Math.min(buckets - 1, Math.floor(((sampleTime - startTime) / span) * buckets))
      : Math.floor(((index - start) * buckets) / count);
    if (nextBucket !== bucket || broken) {
      flush();
      if (broken && result.length > 0) {
        result.push(-1);
      }
      broken = false;
      bucket = nextBucket;
      first = index;
      low = index;
      high = index;
      last = index;
    } else {
      last = index;
      if (value < values[low]) {
        low = index;
      }
      if (value > values[high]) {
        high = index;
      }
    }
  }
  flush();
  return result;
}

/** SVG path data ("M x y L x y ...") that starts a new segment at each gap. */
export function decimatedPath(
  time: readonly number[],
  values: readonly number[],
  x: (value: number) => number,
  y: (value: number) => number,
  buckets: number,
): string {
  const count = Math.min(time.length, values.length);
  const indices = decimateIndices(time, values, 0, count, buckets);
  const parts: string[] = [];
  let move = true;
  for (const index of indices) {
    if (index < 0) {
      move = true;
      continue;
    }
    parts.push(`${move ? 'M' : 'L'} ${x(time[index]).toFixed(2)} ${y(values[index]).toFixed(2)}`);
    move = false;
  }
  return parts.join(' ');
}
