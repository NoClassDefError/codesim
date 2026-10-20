import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react';

export type PlotRange = [number, number];

export interface PlotRanges {
  x: PlotRange;
  y: PlotRange;
}

const minimumScale = 1;
const maximumScale = 500;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function visibleRange(base: PlotRange, scale: number, centerRatio: number): PlotRange {
  const fullSpan = Math.max(base[1] - base[0], Number.EPSILON);
  const span = fullSpan / scale;
  const halfSpan = span / 2;
  const requestedCenter = base[0] + centerRatio * fullSpan;
  const center = clamp(requestedCenter, base[0] + halfSpan, base[1] - halfSpan);
  return [center - halfSpan, center + halfSpan];
}

export function usePoleZoom(base: PlotRanges) {
  const [scale, setScale] = useState(1);
  const [center, setCenter] = useState({ x: 0.5, y: 0.5 });
  const ranges = useMemo(() => ({
    x: visibleRange(base.x, scale, center.x),
    y: visibleRange(base.y, scale, center.y),
  }), [base.x, base.y, center.x, center.y, scale]);

  const zoomAt = useCallback((factor: number, anchorX = 0.5, anchorY = 0.5) => {
    const boundedAnchorX = clamp(anchorX, 0, 1);
    const boundedAnchorY = clamp(anchorY, 0, 1);
    setScale((currentScale) => {
      const nextScale = clamp(currentScale / factor, minimumScale, maximumScale);
      if (nextScale === currentScale) {
        return currentScale;
      }
      setCenter((currentCenter) => {
        const currentX = visibleRange(base.x, currentScale, currentCenter.x);
        const currentY = visibleRange(base.y, currentScale, currentCenter.y);
        const anchorValueX = currentX[0] + boundedAnchorX * (currentX[1] - currentX[0]);
        const anchorValueY = currentY[0] + boundedAnchorY * (currentY[1] - currentY[0]);
        const nextXSpan = (base.x[1] - base.x[0]) / nextScale;
        const nextYSpan = (base.y[1] - base.y[0]) / nextScale;
        const nextCenterX = anchorValueX + (0.5 - boundedAnchorX) * nextXSpan;
        const nextCenterY = anchorValueY + (0.5 - boundedAnchorY) * nextYSpan;
        return {
          x: clamp((nextCenterX - base.x[0]) / (base.x[1] - base.x[0]), 0, 1),
          y: clamp((nextCenterY - base.y[0]) / (base.y[1] - base.y[0]), 0, 1),
        };
      });
      return nextScale;
    });
  }, [base.x, base.y]);

  const reset = useCallback(() => {
    setScale(1);
    setCenter({ x: 0.5, y: 0.5 });
  }, []);

  const panBy = useCallback((horizontalFraction: number, verticalFraction: number) => {
    setCenter((currentCenter) => ({
      x: clamp(currentCenter.x - horizontalFraction / scale, 0, 1),
      y: clamp(currentCenter.y + verticalFraction / scale, 0, 1),
    }));
  }, [scale]);

  return {
    ranges,
    scale,
    canZoomIn: scale < maximumScale,
    canZoomOut: scale > minimumScale,
    zoomAt,
    zoomIn: () => zoomAt(0.625),
    zoomOut: () => zoomAt(1.6),
    panBy,
    reset,
  };
}

export function usePolePan({
  enabled,
  svgWidth,
  svgHeight,
  plotWidth,
  plotHeight,
  onPan,
}: {
  enabled: boolean;
  svgWidth: number;
  svgHeight: number;
  plotWidth: number;
  plotHeight: number;
  onPan: (horizontalFraction: number, verticalFraction: number) => void;
}) {
  const activePointer = useRef<{ id: number; x: number; y: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  const onPointerDown = useCallback((event: ReactPointerEvent<SVGSVGElement>) => {
    if (!enabled || event.button !== 0) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    activePointer.current = { id: event.pointerId, x: event.clientX, y: event.clientY };
    setDragging(true);
  }, [enabled]);

  const onPointerMove = useCallback((event: ReactPointerEvent<SVGSVGElement>) => {
    const active = activePointer.current;
    if (!active || active.id !== event.pointerId) {
      return;
    }
    const bounds = event.currentTarget.getBoundingClientRect();
    const horizontalFraction = ((event.clientX - active.x) / bounds.width)
      * (svgWidth / plotWidth);
    const verticalFraction = ((event.clientY - active.y) / bounds.height)
      * (svgHeight / plotHeight);
    activePointer.current = { id: event.pointerId, x: event.clientX, y: event.clientY };
    onPan(horizontalFraction, verticalFraction);
  }, [onPan, plotHeight, plotWidth, svgHeight, svgWidth]);

  const finishDrag = useCallback((event: ReactPointerEvent<SVGSVGElement>) => {
    if (activePointer.current?.id !== event.pointerId) {
      return;
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    activePointer.current = null;
    setDragging(false);
  }, []);

  return {
    dragging,
    onPointerDown,
    onPointerMove,
    onPointerUp: finishDrag,
    onPointerCancel: finishDrag,
  };
}

export function PoleZoomControls({
  scale,
  canZoomIn,
  canZoomOut,
  onZoomIn,
  onZoomOut,
  onReset,
}: {
  scale: number;
  canZoomIn: boolean;
  canZoomOut: boolean;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onReset: () => void;
}) {
  const label = scale >= 10 ? scale.toFixed(0) : scale.toFixed(1);
  return (
    <div className="pole-zoom-controls" aria-label="Pole plot zoom controls">
      <button type="button" onClick={onZoomOut} disabled={!canZoomOut} title="Zoom out">−</button>
      <button type="button" onClick={onZoomIn} disabled={!canZoomIn} title="Zoom in">+</button>
      <button type="button" onClick={onReset} disabled={!canZoomOut}>Reset</button>
      <output>{label}×</output>
    </div>
  );
}
