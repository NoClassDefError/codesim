import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { SystemFlowNode } from '../model/flowModel';
import { kindLabels } from '../model/flowModel';

function DeviceIcon({ name }: { name: string }) {
  const common = {
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.7,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };

  const graphic = (() => {
    switch (name) {
      case 'bus':
        return <rect x="5" y="5" width="14" height="14" rx="1" {...common} strokeWidth={2.2} />;
      case 'grid':
        return (
          <>
            <circle cx="12" cy="12" r="9" {...common} />
            <path d="M5 12c2.2-4 4.4-4 6.6 0s4.4 4 7 0" {...common} />
          </>
        );
      case 'inverter':
        return (
          <>
            <circle cx="9" cy="12" r="6.5" {...common} />
            <circle cx="15" cy="12" r="6.5" {...common} />
            <path d="M5.5 12h7M8.2 9.3v5.4M12.5 12c1.6-2.8 3.2-2.8 4.8 0" {...common} />
          </>
        );
      case 'generator':
        return (
          <>
            <circle cx="12" cy="12" r="9" {...common} />
            <path d="M7 12c1.7-3.2 3.4-3.2 5.1 0s3.4 3.2 5.1 0" {...common} />
          </>
        );
      case 'motor':
        return (
          <>
            <circle cx="12" cy="12" r="9" {...common} />
            <path d="M8 16V8l4 5 4-5v8" {...common} />
          </>
        );
      case 'capacitor':
        return (
          <>
            <path d="M12 2v7M6 9h12M6 13h12M12 13v7M8 21h8" {...common} />
          </>
        );
      case 'load':
        return <path d="M12 2v15M7 12l5 5 5-5M7 21h10" {...common} />;
      case 'zero-current':
        return (
          <>
            <circle cx="12" cy="12" r="9" {...common} />
            <path d="M8 16l8-8" {...common} />
          </>
        );
      default:
        return (
          <>
            <circle cx="12" cy="12" r="8" {...common} />
            <path d="M8 12h8" {...common} />
          </>
        );
    }
  })();

  return (
    <svg className={`system-node-icon icon-${name}`} viewBox="0 0 24 24" aria-hidden="true">
      {graphic}
    </svg>
  );
}

export function SystemNode({ data, selected }: NodeProps<SystemFlowNode>) {
  const { component, terminalSide } = data;
  const icon = component.icon ?? component.kind;
  const rotation = ['load', 'capacitor', 'zero-current'].includes(icon)
    ? terminalSide === 'right'
      ? 90
      : terminalSide === 'bottom'
        ? 180
        : terminalSide === 'left'
          ? -90
          : 0
    : 0;

  return (
    <div className={`system-node kind-${component.kind} ${selected ? 'selected' : ''}`}>
      <Handle id="source-left" type="source" position={Position.Left} isConnectable={false} />
      <Handle id="target-left" type="target" position={Position.Left} isConnectable={false} className="target-port" />
      <Handle id="source-top" type="source" position={Position.Top} isConnectable={false} />
      <Handle id="target-top" type="target" position={Position.Top} isConnectable={false} className="target-port" />

      <div className="system-node-symbol" style={{ transform: `rotate(${rotation}deg)` }}>
        <DeviceIcon name={icon} />
      </div>
      <div className="system-node-label">
        <div className="system-node-name">{component.name}</div>
        <div className="system-node-kind">{kindLabels[component.kind]}</div>
      </div>

      <Handle id="source-right" type="source" position={Position.Right} isConnectable={false} />
      <Handle id="target-right" type="target" position={Position.Right} isConnectable={false} className="target-port" />
      <Handle id="source-bottom" type="source" position={Position.Bottom} isConnectable={false} />
      <Handle id="target-bottom" type="target" position={Position.Bottom} isConnectable={false} className="target-port" />
    </div>
  );
}
