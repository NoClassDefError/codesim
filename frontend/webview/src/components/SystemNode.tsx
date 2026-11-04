import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { SystemFlowNode } from '../model/flowModel';
import { GROUND_HEIGHT, GROUND_WIDTH, ICON_SIZE, kindLabels } from '../model/flowModel';
import type { PortSide } from '../model/types';

/*
 * One-line diagram symbols. Every symbol fills its node box exactly and runs
 * a lead out to the middle of each side a wire attaches to, so wires end on
 * the symbol rather than on an invisible box around it.
 *
 * Device symbols are drawn in a 44 x 44 box; the body occupies 8..36 and the
 * leads cover the rest.
 */

const C = ICON_SIZE / 2;
const BODY = 8;

const stroke = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
};

/** Lead from the symbol body out to the middle of one side of the box. */
function lead(side: PortSide, inset = BODY): string {
  switch (side) {
    case 'left':
      return `M0 ${C}H${inset}`;
    case 'right':
      return `M${ICON_SIZE - inset} ${C}H${ICON_SIZE}`;
    case 'top':
      return `M${C} 0V${inset}`;
    default:
      return `M${C} ${ICON_SIZE - inset}V${ICON_SIZE}`;
  }
}

/** Single-terminal sources and machines: body plus one lead towards their bus. */
function SourceBody({ icon }: { icon: string }) {
  switch (icon) {
    case 'grid':
      // External grid: hatched square.
      return (
        <>
          <rect x={BODY} y={BODY} width={28} height={28} {...stroke} />
          <path d="M8 22L22 8M8 36L36 8M22 36L36 22" {...stroke} strokeWidth={1.2} />
        </>
      );
    case 'converter':
    case 'inverter':
      // Converter: square with a diagonal, DC bar and AC wave.
      return (
        <>
          <rect x={BODY} y={BODY} width={28} height={28} rx={2} {...stroke} />
          <path d="M8 36L36 8" {...stroke} strokeWidth={1.2} />
          <path d="M12 15h8M12 18h8" {...stroke} strokeWidth={1.4} />
          <path d="M23 28c1.5-3 3-3 4.5 0s3 3 4.5 0" {...stroke} strokeWidth={1.4} />
        </>
      );
    case 'generator':
      return (
        <>
          <circle cx={C} cy={C} r={14} {...stroke} />
          <path d="M14 22c2.7-5 5.3-5 8 0s5.3 5 8 0" {...stroke} />
        </>
      );
    case 'motor':
      return (
        <>
          <circle cx={C} cy={C} r={14} {...stroke} />
          <path d="M16 29V15l6 8 6-8v14" {...stroke} />
        </>
      );
    default:
      return (
        <>
          <circle cx={C} cy={C} r={14} {...stroke} />
          <path d="M16 22h12" {...stroke} />
        </>
      );
  }
}

/** Shunt elements, drawn between their bus (top) and their ground (bottom). */
function ShuntBody({ icon }: { icon: string }) {
  if (icon === 'capacitor') {
    return <path d={`M${C} 0V19M10 19H34M10 25H34M${C} 25V${ICON_SIZE}`} {...stroke} />;
  }
  // Load: impedance box with a downward arrow.
  return (
    <>
      <path d={`M${C} 0V${BODY}M${C} ${ICON_SIZE - BODY}V${ICON_SIZE}`} {...stroke} />
      <rect x={14} y={BODY} width={16} height={28} rx={1} {...stroke} />
      <path d="M22 13V29M18 25l4 4 4-4" {...stroke} strokeWidth={1.4} />
    </>
  );
}

const ROTATION: Record<PortSide, number> = { top: 0, right: 90, bottom: 180, left: -90 };

function DeviceSymbol({ icon, role, terminalSide, hasGround }: {
  icon: string;
  role: string;
  terminalSide?: PortSide;
  hasGround?: boolean;
}) {
  if (role === 'shunt') {
    // Normally fed from the top; turned when the user fixed another side.
    const rotation = ROTATION[terminalSide ?? 'top'];
    return (
      <svg className={`system-node-icon icon-${icon}`} viewBox={`0 0 ${ICON_SIZE} ${ICON_SIZE}`} aria-hidden="true">
        <g transform={`rotate(${rotation} ${C} ${C})`}>
          <ShuntBody icon={icon} />
        </g>
      </svg>
    );
  }
  return (
    <svg className={`system-node-icon icon-${icon}`} viewBox={`0 0 ${ICON_SIZE} ${ICON_SIZE}`} aria-hidden="true">
      <SourceBody icon={icon} />
      <path d={lead(terminalSide ?? 'left')} {...stroke} />
      {hasGround && terminalSide !== 'bottom' && <path d={lead('bottom')} {...stroke} />}
    </svg>
  );
}

function GroundSymbol() {
  const x = GROUND_WIDTH / 2;
  return (
    <svg className="system-node-icon icon-ground" viewBox={`0 0 ${GROUND_WIDTH} ${GROUND_HEIGHT}`} aria-hidden="true">
      <path
        d={`M${x} 0V7M2 7H${GROUND_WIDTH - 2}M6.5 12.5H${GROUND_WIDTH - 6.5}M10.5 18H${GROUND_WIDTH - 10.5}`}
        {...stroke}
      />
    </svg>
  );
}

const handles = (['left', 'top', 'right', 'bottom'] as const).map((side) => {
  const position = {
    left: Position.Left,
    top: Position.Top,
    right: Position.Right,
    bottom: Position.Bottom,
  }[side];
  return (
    <span key={side}>
      <Handle id={`source-${side}`} type="source" position={position} isConnectable={false} />
      <Handle id={`target-${side}`} type="target" position={position} isConnectable={false} className="target-port" />
    </span>
  );
});

export function SystemNode({ data, selected }: NodeProps<SystemFlowNode>) {
  const { component, role, terminalSide, width, height } = data;
  const icon = component.icon ?? component.kind;
  const labelPlacement = role === 'bus'
    ? 'above'
    : role === 'shunt' || data.hasGround ? 'right' : 'below';

  return (
    <div
      className={`system-node role-${role} kind-${component.kind} ${selected ? 'selected' : ''}`}
      style={{ width, height }}
      title={role === 'ground' ? 'Ground' : undefined}
    >
      {handles}
      {role === 'bus' && <div className="system-node-busbar" />}
      {role === 'ground' && <GroundSymbol />}
      {(role === 'source' || role === 'shunt') && (
        <DeviceSymbol icon={icon} role={role} terminalSide={terminalSide} hasGround={data.hasGround} />
      )}
      {role !== 'ground' && (
        <div className={`system-node-label label-${labelPlacement}`}>
          <div className="system-node-name">{component.name}</div>
          <div className="system-node-kind">{kindLabels[component.kind]}</div>
        </div>
      )}
    </div>
  );
}
