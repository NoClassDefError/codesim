import { useCallback } from 'react';
import {
  BaseEdge,
  EdgeLabelRenderer,
  useReactFlow,
  type EdgeProps,
} from '@xyflow/react';
import type { SystemFlowEdge, SystemFlowNode } from '../model/flowModel';

const PORT_STUB = 22;

function outwardPoint(x: number, y: number, side: string | undefined) {
  if (side === 'left') {
    return { x: x - PORT_STUB, y };
  }
  if (side === 'right') {
    return { x: x + PORT_STUB, y };
  }
  if (side === 'top') {
    return { x, y: y - PORT_STUB };
  }
  return { x, y: y + PORT_STUB };
}

/** Path through a layout route; the label sits on the middle of its longest segment. */
function routedPath(points: Array<{ x: number; y: number }>) {
  let label = points[0];
  let longest = -1;
  for (let index = 1; index < points.length; index += 1) {
    const from = points[index - 1];
    const to = points[index];
    const length = Math.abs(to.x - from.x) + Math.abs(to.y - from.y);
    if (length > longest) {
      longest = length;
      label = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
    }
  }
  return {
    path: points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' '),
    label,
  };
}

export function RoutedEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  data,
  markerEnd,
  selected,
}: EdgeProps<SystemFlowEdge>) {
  const { setEdges, screenToFlowPosition } =
    useReactFlow<SystemFlowNode, SystemFlowEdge>();

  const routed = data?.points && data.points.length >= 2
    ? routedPath(data.points)
    : undefined;
  const fallback = routed ? undefined : stubPath();
  const path = routed?.path ?? fallback!.path;
  const labelPosition = routed?.label ?? fallback!.label;

  /** Route without a layout: out of each port, across at the midpoint or the user's waypoint. */
  function stubPath() {
    const routeAxis = data?.routeAxis ??
      (Math.abs(targetX - sourceX) >= Math.abs(targetY - sourceY)
        ? 'horizontal'
        : 'vertical');
    const laneOffset = data?.laneOffset ?? 0;
    const waypoint = data?.waypoint;
    const trackX = waypoint?.x ?? (sourceX + targetX) / 2 + laneOffset;
    const trackY = waypoint?.y ?? (sourceY + targetY) / 2 + laneOffset;
    const sourceStub = outwardPoint(sourceX, sourceY, data?.sourceSide);
    const targetStub = outwardPoint(targetX, targetY, data?.targetSide);
    return {
      path: [
        `M ${sourceX} ${sourceY}`,
        `L ${sourceStub.x} ${sourceStub.y}`,
        `L ${trackX} ${sourceStub.y}`,
        `L ${trackX} ${trackY}`,
        `L ${targetStub.x} ${trackY}`,
        `L ${targetStub.x} ${targetStub.y}`,
        `L ${targetX} ${targetY}`,
      ].join(' '),
      label: routeAxis === 'horizontal'
        ? { x: trackX, y: (sourceY + targetY) / 2 }
        : { x: (sourceX + targetX) / 2, y: trackY },
    };
  }

  const startDragging = useCallback(
    (event: React.PointerEvent<HTMLButtonElement>) => {
      event.preventDefault();
      event.stopPropagation();

      const move = (pointerEvent: PointerEvent) => {
        const position = screenToFlowPosition({
          x: pointerEvent.clientX,
          y: pointerEvent.clientY,
        });

        setEdges((edges) =>
          edges.map((edge) =>
            edge.id === id
              ? {
                  ...edge,
                  data: {
                    label: edge.data?.label ?? '',
                    ...edge.data,
                    waypoint: position,
                    // A hand-placed waypoint replaces the automatic route.
                    points: undefined,
                  },
                }
              : edge,
          ),
        );
      };

      const stop = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', stop);
      };

      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop);
    },
    [id, screenToFlowPosition, setEdges],
  );

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        className={selected ? 'route-edge selected' : 'route-edge'}
        interactionWidth={18}
      />

      <EdgeLabelRenderer>
        <div
          className="edge-caption nodrag nopan"
          style={{
            transform: `translate(-50%, -50%) translate(${labelPosition.x}px, ${labelPosition.y}px)`,
          }}
        >
          {data?.label}
        </div>

        {selected && (
          <button
            type="button"
            className="edge-handle nodrag nopan"
            style={{
              transform: `translate(-50%, -50%) translate(${labelPosition.x}px, ${labelPosition.y}px)`,
            }}
            onPointerDown={startDragging}
            title="拖动以调整线路走向"
          />
        )}
      </EdgeLabelRenderer>
    </>
  );
}
