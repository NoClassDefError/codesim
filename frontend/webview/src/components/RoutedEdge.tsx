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
  const path = [
    `M ${sourceX} ${sourceY}`,
    `L ${sourceStub.x} ${sourceStub.y}`,
    `L ${trackX} ${sourceStub.y}`,
    `L ${trackX} ${trackY}`,
    `L ${targetStub.x} ${trackY}`,
    `L ${targetStub.x} ${targetStub.y}`,
    `L ${targetX} ${targetY}`,
  ].join(' ');
  const labelPosition = routeAxis === 'horizontal'
    ? { x: trackX, y: (sourceY + targetY) / 2 }
    : { x: (sourceX + targetX) / 2, y: trackY };

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
