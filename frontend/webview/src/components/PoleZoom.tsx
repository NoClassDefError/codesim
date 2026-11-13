import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react';

export type PlotRange = [number, number];

export interface PlotRanges {
  x: PlotRange;
  y: PlotRange;
}

/** Plot area inside the SVG viewBox. */
export interface PlotArea {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Deepest zoom, as a fraction of the full span of an axis. */
const minimumSpanFraction = 1e-4;
/** Wheel sensitivity: one 100-pixel notch zooms by about 16 %. */
const wheelSensitivity = 0.0015;
/** Box drags smaller than this (SVG units) on an axis leave that axis unchanged. */
const minimumBoxSize = 6;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function span(range: PlotRange): number {
  return range[1] - range[0];
}

/** Shift `range` so that it lies inside `base` (it is never wider than `base`). */
function fitInto(range: PlotRange, base: PlotRange): PlotRange {
  const width = Math.min(span(range), span(base));
  const start = clamp(range[0], base[0], base[1] - width);
  return [start, start + width];
}

/** Scale `range` by `factor` around the point at `anchor` (0..1) of the range. */
function scaleRange(range: PlotRange, base: PlotRange, factor: number, anchor: number): PlotRange {
  const width = clamp(span(range) * factor, span(base) * minimumSpanFraction, span(base));
  const anchorValue = range[0] + anchor * span(range);
  return fitInto([anchorValue - anchor * width, anchorValue - anchor * width + width], base);
}

type Gesture =
  | { kind: 'box'; pointerId: number; startX: number; startY: number; currentX: number; currentY: number }
  | { kind: 'pan'; pointerId: number; lastX: number; lastY: number };

/**
 * Direct-manipulation zoom for the pole plots:
 * - mouse wheel zooms around the cursor (Shift: real axis only, Alt: imaginary axis only);
 * - dragging draws a box and zooms into it (a flat box zooms one axis only);
 * - Shift+drag or middle-button drag pans;
 * - double-click resets to the full view.
 * Ranges are in the plot's own axis units (linear or signed-log).
 */
export function usePlotZoom({
  base,
  svgWidth,
  svgHeight,
  plot,
}: {
  base: PlotRanges;
  svgWidth: number;
  svgHeight: number;
  plot: PlotArea;
}) {
  const [view, setView] = useState<PlotRanges | null>(null);
  const [gesture, setGesture] = useState<Gesture | null>(null);
  const [svg, setSvg] = useState<SVGSVGElement | null>(null);

  // New data gives new base ranges: show it in full.
  useEffect(() => setView(null), [base]);

  const ranges = view ?? base;
  // Latest ranges for the native wheel listener and gesture handlers.
  const rangesRef = useRef(ranges);
  useEffect(() => {
    rangesRef.current = ranges;
  }, [ranges]);

  /** Pointer position in SVG units and as fractions of the plot area (y downwards). */
  const locate = useCallback((element: SVGSVGElement, clientX: number, clientY: number) => {
    const bounds = element.getBoundingClientRect();
    const x = ((clientX - bounds.left) / Math.max(bounds.width, 1)) * svgWidth;
    const y = ((clientY - bounds.top) / Math.max(bounds.height, 1)) * svgHeight;
    return {
      x,
      y,
      fx: (x - plot.left) / plot.width,
      fy: (y - plot.top) / plot.height,
      inside: x >= plot.left && x <= plot.left + plot.width && y >= plot.top && y <= plot.top + plot.height,
    };
  }, [plot.height, plot.left, plot.top, plot.width, svgHeight, svgWidth]);

  const zoomAt = useCallback((factorX: number, factorY: number, fx: number, fy: number) => {
    const current = rangesRef.current;
    setView({
      x: scaleRange(current.x, base.x, factorX, clamp(fx, 0, 1)),
      // fy is measured downwards, the y axis upwards.
      y: scaleRange(current.y, base.y, factorY, 1 - clamp(fy, 0, 1)),
    });
  }, [base.x, base.y]);

  // React registers wheel listeners as passive, so the page would scroll as
  // well; attach a non-passive listener to keep the wheel on the plot.
  useEffect(() => {
    if (!svg) {
      return undefined;
    }
    const onWheel = (event: WheelEvent) => {
      const point = locate(svg, event.clientX, event.clientY);
      if (!point.inside) {
        return;
      }
      event.preventDefault();
      const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 400 : 1);
      const factor = Math.exp(clamp(pixels, -400, 400) * wheelSensitivity);
      zoomAt(event.altKey ? 1 : factor, event.shiftKey ? 1 : factor, point.fx, point.fy);
    };
    svg.addEventListener('wheel', onWheel, { passive: false });
    return () => svg.removeEventListener('wheel', onWheel);
  }, [locate, svg, zoomAt]);

  const onPointerDown = useCallback((event: ReactPointerEvent<SVGSVGElement>) => {
    const pan = event.button === 1 || (event.button === 0 && event.shiftKey);
    if (!pan && event.button !== 0) {
      return;
    }
    const point = locate(event.currentTarget, event.clientX, event.clientY);
    if (!point.inside) {
      return;
    }
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setGesture(pan
      ? { kind: 'pan', pointerId: event.pointerId, lastX: point.x, lastY: point.y }
      : {
        kind: 'box', pointerId: event.pointerId,
        startX: point.x, startY: point.y, currentX: point.x, currentY: point.y,
      });
  }, [locate]);

  const onPointerMove = useCallback((event: ReactPointerEvent<SVGSVGElement>) => {
    if (!gesture || gesture.pointerId !== event.pointerId) {
      return;
    }
    const point = locate(event.currentTarget, event.clientX, event.clientY);
    if (gesture.kind === 'box') {
      setGesture({
        ...gesture,
        currentX: clamp(point.x, plot.left, plot.left + plot.width),
        currentY: clamp(point.y, plot.top, plot.top + plot.height),
      });
      return;
    }
    const current = rangesRef.current;
    const dx = ((point.x - gesture.lastX) / plot.width) * span(current.x);
    const dy = ((point.y - gesture.lastY) / plot.height) * span(current.y);
    setView({
      x: fitInto([current.x[0] - dx, current.x[1] - dx], base.x),
      y: fitInto([current.y[0] + dy, current.y[1] + dy], base.y),
    });
    setGesture({ ...gesture, lastX: point.x, lastY: point.y });
  }, [base.x, base.y, gesture, locate, plot.height, plot.left, plot.top, plot.width]);

  const finish = useCallback((event: ReactPointerEvent<SVGSVGElement>, apply: boolean) => {
    if (!gesture || gesture.pointerId !== event.pointerId) {
      return;
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setGesture(null);
    if (!apply || gesture.kind !== 'box') {
      return;
    }
    const width = Math.abs(gesture.currentX - gesture.startX);
    const height = Math.abs(gesture.currentY - gesture.startY);
    if (width < minimumBoxSize && height < minimumBoxSize) {
      return;
    }
    const current = rangesRef.current;
    const toX = (svgX: number) => current.x[0] + ((svgX - plot.left) / plot.width) * span(current.x);
    const toY = (svgY: number) => current.y[1] - ((svgY - plot.top) / plot.height) * span(current.y);
    const boxed = (a: number, b: number, baseRange: PlotRange): PlotRange => {
      const minimum = span(baseRange) * minimumSpanFraction;
      const start = Math.min(a, b);
      const end = Math.max(a, b, start + minimum);
      return fitInto([start, end], baseRange);
    };
    setView({
      x: width >= minimumBoxSize
        ? boxed(toX(gesture.startX), toX(gesture.currentX), base.x)
        : current.x,
      y: height >= minimumBoxSize
        ? boxed(toY(gesture.startY), toY(gesture.currentY), base.y)
        : current.y,
    });
  }, [base.x, base.y, gesture, plot.height, plot.left, plot.top, plot.width]);

  const reset = useCallback(() => setView(null), []);

  const marquee = gesture?.kind === 'box'
    ? {
      x: Math.min(gesture.startX, gesture.currentX),
      y: Math.min(gesture.startY, gesture.currentY),
      width: Math.abs(gesture.currentX - gesture.startX),
      height: Math.abs(gesture.currentY - gesture.startY),
    }
    : null;

  return {
    ranges,
    zoomed: view !== null,
    zoomX: span(base.x) / span(ranges.x),
    zoomY: span(base.y) / span(ranges.y),
    marquee,
    panning: gesture?.kind === 'pan',
    reset,
    svgRef: setSvg,
    surfaceProps: {
      onPointerDown,
      onPointerMove,
      onPointerUp: (event: ReactPointerEvent<SVGSVGElement>) => finish(event, true),
      onPointerCancel: (event: ReactPointerEvent<SVGSVGElement>) => finish(event, false),
      onDoubleClick: reset,
    },
  };
}

function formatZoom(value: number): string {
  return value >= 10 ? value.toFixed(0) : value.toFixed(1);
}

/** Zoom read-out and gesture hint shown in the plot heading. */
export function PoleZoomStatus({ zoom }: { zoom: ReturnType<typeof usePlotZoom> }) {
  return (
    <div className="pole-zoom-status" aria-live="polite">
      {zoom.zoomed
        ? <output>Re {formatZoom(zoom.zoomX)}× · Im {formatZoom(zoom.zoomY)}×</output>
        : null}
      <span className="pole-zoom-hint">
        {zoom.zoomed
          ? 'Shift+drag to pan · double-click to reset'
          : 'Scroll or drag a box to zoom'}
      </span>
    </div>
  );
}

/** The dashed box drawn while dragging. */
export function ZoomMarquee({ zoom }: { zoom: ReturnType<typeof usePlotZoom> }) {
  const box = zoom.marquee;
  return box ? <rect className="chart-marquee" {...box} /> : null;
}
