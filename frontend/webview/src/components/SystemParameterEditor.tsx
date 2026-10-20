import { useEffect, useState } from 'react';
import { updateSystemParameter } from '../bridge/vscode';
import type { ParameterDescriptor, ParameterValue } from '../model/types';

function parameterText(value: ParameterValue): string {
  return Array.isArray(value) ? JSON.stringify(value) : String(value ?? '');
}

export function SystemParameterEditor({
  parameters,
}: {
  parameters: ParameterDescriptor[];
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setDrafts(Object.fromEntries(
      parameters.map((parameter) => [parameter.id, parameterText(parameter.value)]),
    ));
    setErrors({});
  }, [parameters]);

  if (parameters.length === 0) {
    return <div className="empty-note">No system parameters</div>;
  }

  const commit = (parameter: ParameterDescriptor) => {
    const text = drafts[parameter.id] ?? '';
    try {
      let value: ParameterValue;
      if (typeof parameter.value === 'number') {
        value = Number(text);
        if (!Number.isFinite(value)) {
          throw new Error('Expected a finite number.');
        }
      } else if (Array.isArray(parameter.value)) {
        value = JSON.parse(text) as ParameterValue;
        if (!Array.isArray(value)) {
          throw new Error('Expected a JSON array.');
        }
      } else {
        value = text;
      }
      setErrors((current) => ({ ...current, [parameter.id]: false }));
      updateSystemParameter(parameter.id, value);
    } catch {
      setErrors((current) => ({ ...current, [parameter.id]: true }));
    }
  };

  return (
    <div className="system-parameter-table">
      {parameters.map((parameter) => {
        const editable = parameter.editable !== false;
        return (
          <label className="system-parameter-row" key={parameter.id}>
            <span title={parameter.id}>{parameter.label}</span>
            {!editable ? (
              <code title="This parameter cannot be represented as a JSON override">
                {parameterText(parameter.value)}
              </code>
            ) : typeof parameter.value === 'boolean' ? (
              <select
                value={drafts[parameter.id] ?? String(parameter.value)}
                onChange={(event) => {
                  const value = event.target.value === 'true';
                  setDrafts((current) => ({
                    ...current,
                    [parameter.id]: event.target.value,
                  }));
                  updateSystemParameter(parameter.id, value);
                }}
              >
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            ) : (
              <input
                className={errors[parameter.id] ? 'invalid' : ''}
                type={typeof parameter.value === 'number' ? 'number' : 'text'}
                step="any"
                value={drafts[parameter.id] ?? ''}
                onChange={(event) => setDrafts((current) => ({
                  ...current,
                  [parameter.id]: event.target.value,
                }))}
                onBlur={() => commit(parameter)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.currentTarget.blur();
                  }
                }}
                title={errors[parameter.id] ? 'Enter a valid value' : parameter.id}
              />
            )}
          </label>
        );
      })}
    </div>
  );
}
