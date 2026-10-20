import type { Selection, SystemSnapshot } from '../model/types';
import { kindLabels } from '../model/flowModel';
import { SystemParameterEditor } from './SystemParameterEditor';

interface Props {
  snapshot: SystemSnapshot;
  selection: Selection;
  onSelect: (selection: Selection) => void;
}

export function SystemTree({ snapshot, selection, onSelect }: Props) {
  return (
    <aside className="panel tree-panel">
      <div className="panel-title">System</div>
      <button
        className="tree-system"
        type="button"
        onClick={() => onSelect(null)}
      >
        {snapshot.system.name}
      </button>

      <details className="tree-group" open>
        <summary className="tree-section">
          <span>System parameters</span>
          <small>{snapshot.system.parameters?.length ?? 0}</small>
        </summary>
        <SystemParameterEditor parameters={snapshot.system.parameters ?? []} />
      </details>

      <details className="tree-group" open>
        <summary className="tree-section">
          <span>Components</span>
          <small>{snapshot.components.length}</small>
        </summary>
        {snapshot.components.map((component) => (
          <button
            type="button"
            key={component.id}
            className={
              selection?.kind === 'component' && selection.id === component.id
                ? 'tree-item active'
                : 'tree-item'
            }
            onClick={() => onSelect({ kind: 'component', id: component.id })}
          >
            <span>{component.name}</span>
            <small>{kindLabels[component.kind]}</small>
          </button>
        ))}
      </details>

      <details className="tree-group" open>
        <summary className="tree-section">
          <span>Connections</span>
          <small>{snapshot.connections.length}</small>
        </summary>
        {snapshot.connections.map((connection) => (
          <button
            type="button"
            key={connection.id}
            className={
              selection?.kind === 'connection' && selection.id === connection.id
                ? 'tree-item active'
                : 'tree-item'
            }
            onClick={() => onSelect({ kind: 'connection', id: connection.id })}
          >
            <span>{connection.name}</span>
            <small>{connection.source} → {connection.target}</small>
          </button>
        ))}
      </details>
    </aside>
  );
}
