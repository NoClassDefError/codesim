import { openSource } from '../bridge/vscode';
import type {
  ParameterDescriptor,
  PortSide,
  Selection,
  SourceReference,
  SystemSnapshot,
} from '../model/types';

interface Props {
  snapshot: SystemSnapshot;
  selection: Selection;
  connectionPorts?: {
    sourceSide?: PortSide;
    targetSide?: PortSide;
    sourceAutomatic: boolean;
    targetAutomatic: boolean;
  };
  onConnectionPortChange?: (
    connectionId: string,
    endpoint: 'source' | 'target',
    side?: PortSide,
  ) => void;
}

const portChoices: Array<{ side: PortSide; symbol: string; label: string }> = [
  { side: 'top', symbol: '↑', label: 'Top' },
  { side: 'right', symbol: '→', label: 'Right' },
  { side: 'bottom', symbol: '↓', label: 'Bottom' },
  { side: 'left', symbol: '←', label: 'Left' },
];

function PortSideControl({
  label,
  side,
  automatic,
  onChange,
}: {
  label: string;
  side?: PortSide;
  automatic: boolean;
  onChange: (side?: PortSide) => void;
}) {
  return (
    <div className="port-control-row">
      <span>{label}</span>
      <div className="port-direction-buttons">
        <button
          type="button"
          className={automatic ? 'active' : ''}
          onClick={() => onChange(undefined)}
          title="Choose the port side automatically"
        >
          Auto
        </button>
        {portChoices.map((choice) => (
          <button
            type="button"
            className={!automatic && side === choice.side ? 'active' : ''}
            key={choice.side}
            onClick={() => onChange(choice.side)}
            title={`${choice.label} port`}
            aria-label={`${label}: ${choice.label}`}
          >
            {choice.symbol}
          </button>
        ))}
      </div>
    </div>
  );
}

function SourceButton({ label, source }: { label: string; source?: SourceReference }) {
  if (!source) {
    return null;
  }

  return (
    <button type="button" className="source-button" onClick={() => openSource(source)}>
      {label} · line {source.line}
    </button>
  );
}

function ParameterTable({ parameters }: { parameters: ParameterDescriptor[] }) {
  if (parameters.length === 0) {
    return <div className="empty-note">No exposed parameters</div>;
  }

  return (
    <div className="parameter-table">
      {parameters.map((parameter) => (
        <button
          type="button"
          className="parameter-row"
          key={parameter.id}
          onClick={() => openSource(parameter.source)}
          disabled={!parameter.source}
        >
          <span>{parameter.label}</span>
          <strong>
            {Array.isArray(parameter.value)
              ? JSON.stringify(parameter.value)
              : String(parameter.value)}
            {parameter.unit ? ` ${parameter.unit}` : ''}
          </strong>
        </button>
      ))}
    </div>
  );
}

export function Inspector({
  snapshot,
  selection,
  connectionPorts,
  onConnectionPortChange,
}: Props) {
  if (!selection) {
    return (
      <aside className="panel inspector-panel">
        <div className="panel-title">Inspector</div>
        <h2>{snapshot.system.name}</h2>
        <div className="class-name">{snapshot.system.className}</div>
        <SourceButton label="Open system code" source={snapshot.system.source} />
        <div className="empty-note">Select a component or connection to inspect it.</div>
      </aside>
    );
  }

  if (selection.kind === 'component') {
    const component = snapshot.components.find((item) => item.id === selection.id);
    if (!component) {
      return null;
    }

    return (
      <aside className="panel inspector-panel">
        <div className="panel-title">Component</div>
        <h2>{component.name}</h2>
        <div className="class-name">{component.className}</div>
        <div className="source-stack">
          <SourceButton label="Open instance" source={component.instanceSource} />
          <SourceButton label="Open class" source={component.classSource} />
        </div>
        <h3>Input parameters</h3>
        <ParameterTable parameters={component.parameters} />
      </aside>
    );
  }

  const connection = snapshot.connections.find((item) => item.id === selection.id);
  if (!connection) {
    return null;
  }

  return (
    <aside className="panel inspector-panel">
      <div className="panel-title">Connection</div>
      <h2>{connection.name}</h2>
      <div className="class-name">{connection.source} → {connection.target}</div>
      {connectionPorts && onConnectionPortChange && (
        <div className="port-controls">
          <h3>Port orientation</h3>
          <PortSideControl
            label={connection.source}
            side={connectionPorts.sourceSide}
            automatic={connectionPorts.sourceAutomatic}
            onChange={(side) => onConnectionPortChange(connection.id, 'source', side)}
          />
          <PortSideControl
            label={connection.target}
            side={connectionPorts.targetSide}
            automatic={connectionPorts.targetAutomatic}
            onChange={(side) => onConnectionPortChange(connection.id, 'target', side)}
          />
        </div>
      )}
      <SourceButton label="Open connection code" source={connection.sourceReference} />
      <h3>Parameters</h3>
      <ParameterTable parameters={connection.parameters ?? []} />
    </aside>
  );
}
