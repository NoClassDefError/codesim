import { memo, useMemo, useState } from 'react';
import type {
  ComponentDescriptor,
  ConnectionDescriptor,
  SignalDescriptor,
  SignalOperation,
} from '../model/types';

interface Props {
  systemName: string;
  components: ComponentDescriptor[];
  connections: ConnectionDescriptor[];
  signals: SignalDescriptor[];
  selectedSignalId: string;
  assignedSignalIds: Set<string>;
  targetLabel: string;
  onSelect: (signal: SignalDescriptor) => void;
  onCalculate: (leftId: string, rightId: string, operation: SignalOperation) => void;
}

interface SignalGroup {
  id: string;
  label: string;
  signals: SignalDescriptor[];
}

export const SignalSidebar = memo(function SignalSidebar({
  systemName,
  components,
  connections,
  signals,
  selectedSignalId,
  assignedSignalIds,
  targetLabel,
  onSelect,
  onCalculate,
}: Props) {
  const [selectedLeftId, setSelectedLeftId] = useState('');
  const [selectedRightId, setSelectedRightId] = useState('');
  const [operation, setOperation] = useState<SignalOperation>('magnitude');
  const signalIds = useMemo(() => new Set(signals.map((signal) => signal.id)), [signals]);
  const leftId = signalIds.has(selectedLeftId)
    ? selectedLeftId
    : signals[0]?.id ?? '';
  const rightId = signalIds.has(selectedRightId)
    ? selectedRightId
    : signals[1]?.id ?? signals[0]?.id ?? '';
  const formula = operation === 'magnitude'
    ? '√(A² + B²)'
    : operation === 'power' ? 'A × B' : 'A − B';
  const groups = useMemo(() => {
    const componentNames = new Map(components.map((item) => [item.id, item.name]));
    const connectionNames = new Map(connections.map((item) => [item.id, item.name]));
    const grouped = new Map<string, SignalGroup>();
    for (const signal of signals) {
      const ownerId = signal.ownerId ?? signal.componentId ?? 'system';
      const ownerKind = signal.ownerKind ?? 'component';
      const label = ownerKind === 'system'
        ? systemName
        : componentNames.get(ownerId) ?? connectionNames.get(ownerId) ?? 'System';
      const key = `${ownerKind}:${ownerId}`;
      const group = grouped.get(key) ?? { id: key, label, signals: [] };
      group.signals.push(signal);
      grouped.set(key, group);
    }
    return Array.from(grouped.values());
  }, [components, connections, signals, systemName]);
  const signalOptions = useMemo(() => signals.map((signal) => (
    <option key={signal.id} value={signal.id}>
      {signal.label}{signal.unit ? ` [${signal.unit}]` : ''}
    </option>
  )), [signals]);

  return (
    <aside className="panel signal-panel">
      <div className="signal-panel-heading">
        <div className="panel-title">Signals</div>
        <span>{signals.length}</span>
      </div>
      <div className="signal-target">Add to: <strong>{targetLabel}</strong></div>
      <section className="signal-calculator">
        <div className="signal-calculator-heading">
          <strong>Calculated signal</strong>
          <code>{formula}</code>
        </div>
        <label>
          <span>A</span>
          <select value={leftId} onChange={(event) => setSelectedLeftId(event.target.value)}>
            {signalOptions}
          </select>
        </label>
        <label>
          <span>f</span>
          <select
            value={operation}
            onChange={(event) => setOperation(event.target.value as SignalOperation)}
          >
            <option value="magnitude">Magnitude</option>
            <option value="power">Power</option>
            <option value="error">Error</option>
          </select>
        </label>
        <label>
          <span>B</span>
          <select value={rightId} onChange={(event) => setSelectedRightId(event.target.value)}>
            {signalOptions}
          </select>
        </label>
        <button
          type="button"
          disabled={signals.length < 2}
          onClick={() => onCalculate(leftId, rightId, operation)}
          title={`Create ${formula} and add it to ${targetLabel}`}
        >
          Create &amp; add
        </button>
      </section>
      {groups.length === 0 && <div className="empty-note">No simulation signals loaded.</div>}
      {groups.map((group) => (
        <section className="signal-group" key={group.id}>
          <div className="signal-group-title">{group.label}</div>
          {group.signals.map((signal) => (
            <button
              type="button"
              key={signal.id}
              className={signal.id === selectedSignalId ? 'signal-item active' : 'signal-item'}
              onClick={() => onSelect(signal)}
              title={`Add ${signal.label} to ${targetLabel}`}
            >
              <span>{signal.label}</span>
              <small>{assignedSignalIds.has(signal.id) ? '✓' : '+'} {signal.unit}</small>
            </button>
          ))}
        </section>
      ))}
    </aside>
  );
});
