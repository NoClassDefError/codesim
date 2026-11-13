import { useMemo, useState, type CSSProperties } from 'react';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import type {
  SymbolicEquationDescriptor,
  SymbolicGroupDescriptor,
  SymbolicJacobianDescriptor,
  SymbolicModelDescriptor,
} from '../model/types';

// Rendered markup is cached: the panel re-mounts on every tab switch and the
// user flips between a few blocks. Least recently used entries are dropped.
const latexCache = new Map<string, string>();
const latexCacheLimit = 64;

function renderLatex(expression: string, displayMode: boolean): string {
  const key = `${displayMode ? 'D' : 'I'}${expression}`;
  const cached = latexCache.get(key);
  if (cached !== undefined) {
    latexCache.delete(key);
    latexCache.set(key, cached);
    return cached;
  }
  const markup = katex.renderToString(expression, {
    displayMode,
    throwOnError: false,
    strict: false,
    maxExpand: 10000,
  });
  latexCache.set(key, markup);
  if (latexCache.size > latexCacheLimit) {
    latexCache.delete(latexCache.keys().next().value as string);
  }
  return markup;
}

function Latex({ expression, display = false, className }: {
  expression: string;
  display?: boolean;
  className?: string;
}) {
  const markup = useMemo(() => renderLatex(expression, display), [display, expression]);
  return <span className={className} dangerouslySetInnerHTML={{ __html: markup }} />;
}

type Expression =
  | { kind: 'equation'; item: SymbolicEquationDescriptor }
  | { kind: 'jacobian'; item: SymbolicJacobianDescriptor };

/** Intermediates needed by `used`, including those they use themselves, in order. */
function intermediateClosure(jacobian: SymbolicJacobianDescriptor, used: Iterable<number>): number[] {
  const needed = new Set<number>();
  const stack = [...used];
  while (stack.length > 0) {
    const index = stack.pop() as number;
    if (needed.has(index)) {
      continue;
    }
    needed.add(index);
    stack.push(...(jacobian.intermediates[index]?.uses ?? []));
  }
  return [...needed].sort((a, b) => a - b);
}

function equationLatex(equation: SymbolicEquationDescriptor, rows: number[]): string {
  const lines = rows.map((row) => {
    const item = equation.rows[row];
    return item ? `${item.lhs} &= ${item.latex}` : '';
  });
  return String.raw`\begin{aligned}${lines.join(String.raw`\\[2pt]`)}\end{aligned}`;
}

function blockLatex(
  entries: Map<string, string>,
  rows: number[],
  columns: number[],
  rowLabels: string[],
  columnLabels: string[],
): string {
  const header = ['', ...columns.map((column) => columnLabels[column] ?? '')].join(' & ');
  const body = rows.map((row) => [
    rowLabels[row] ?? '',
    ...columns.map((column) => entries.get(`${row},${column}`) ?? String.raw`\cdot`),
  ].join(' & '));
  const columnSpec = `r|${'c'.repeat(columns.length)}`;
  return String.raw`\begin{array}{${columnSpec}}${header}\\\hline ${body.join(String.raw`\\[3pt]`)}\end{array}`;
}

function SparsityMap({
  jacobian,
  rowGroups,
  columnGroups,
  selected,
  onSelect,
}: {
  jacobian: SymbolicJacobianDescriptor;
  rowGroups: SymbolicGroupDescriptor[];
  columnGroups: SymbolicGroupDescriptor[];
  selected: [number, number];
  onSelect: (row: number, column: number) => void;
}) {
  const counts = useMemo(() => {
    const rowOf = new Map<number, number>();
    rowGroups.forEach((group, index) => group.indices.forEach((row) => rowOf.set(row, index)));
    const columnOf = new Map<number, number>();
    columnGroups.forEach((group, index) => group.indices.forEach((column) => columnOf.set(column, index)));
    const grid = rowGroups.map(() => columnGroups.map(() => 0));
    for (const [row, column] of jacobian.entries) {
      const r = rowOf.get(row);
      const c = columnOf.get(column);
      if (r !== undefined && c !== undefined) {
        grid[r][c] += 1;
      }
    }
    return grid;
  }, [columnGroups, jacobian, rowGroups]);
  const maximum = Math.max(1, ...counts.flat());

  return (
    <div className="symbolic-sparsity" role="grid" aria-label={`${jacobian.label} block sparsity`}>
      <table>
        <thead>
          <tr>
            <th aria-label="Row block" />
            {columnGroups.map((group, column) => (
              <th key={group.name} title={group.name}>{column + 1}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rowGroups.map((rowGroup, row) => (
            <tr key={rowGroup.name}>
              <th title={rowGroup.name}>{row + 1}</th>
              {columnGroups.map((columnGroup, column) => {
                const count = counts[row][column];
                const active = selected[0] === row && selected[1] === column;
                return (
                  <td key={columnGroup.name}>
                    <button
                      type="button"
                      className={`${active ? 'active' : ''}${count === 0 ? ' empty' : ''}`}
                      style={{ '--fill': count / maximum } as CSSProperties}
                      onClick={() => onSelect(row, column)}
                      title={`${rowGroup.name} × ${columnGroup.name}: ${count} nonzero`}
                      aria-pressed={active}
                    >
                      {count || ''}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SymbolHeader({ model, rms }: { model: SymbolicModelDescriptor; rms: boolean }) {
  return (
    <div className="symbolic-symbols">
      <div className="symbolic-symbol-row">
        <span className="symbolic-symbol-label"><Latex expression={String.raw`\mathbf{x}`} /></span>
        <div className="symbolic-symbol-blocks">
          {model.stateBlocks.map((block, blockIndex) => (
            <div key={block.name} className="symbolic-symbol-block">
              <span className="symbolic-block-name">{blockIndex + 1}. {block.name}</span>
              <span className="symbolic-chips">
                {block.indices.map((index) => {
                  const state = model.states[index];
                  const differential = rms && state?.rms === 'differential';
                  return (
                    <span
                      key={index}
                      className={`symbolic-chip${differential ? ' differential' : ''}`}
                      title={`${state?.name ?? index}${rms ? ` (${state?.rms})` : ''}`}
                    >
                      <Latex expression={state?.latex ?? String(index)} />
                    </span>
                  );
                })}
              </span>
            </div>
          ))}
        </div>
      </div>
      <div className="symbolic-symbol-row">
        <span className="symbolic-symbol-label"><Latex expression={String.raw`\mathbf{u}`} /></span>
        <span className="symbolic-chips">
          {model.inputs.length === 0 && <span className="symbolic-muted">none</span>}
          {model.inputs.map((input) => (
            <span key={input.name} className="symbolic-chip input" title={input.name}>
              <Latex expression={input.latex} />
            </span>
          ))}
        </span>
      </div>
      {rms && (
        <p className="symbolic-muted">
          Highlighted states are differential in the RMS model; all others are algebraic.
        </p>
      )}
    </div>
  );
}

function SymbolicModelBody({ model }: { model: SymbolicModelDescriptor }) {
  const [variantId, setVariantId] = useState(model.models[0]?.id ?? 'emt');
  const variant = model.models.find((item) => item.id === variantId) ?? model.models[0];
  const expressions = useMemo<Array<{ id: string; label: string; value: Expression }>>(() => [
    ...(variant?.jacobians ?? []).map((item) => ({ id: item.id, label: item.id, value: { kind: 'jacobian' as const, item } })),
    ...(variant?.equations ?? []).map((item) => ({ id: item.id, label: item.id, value: { kind: 'equation' as const, item } })),
  ], [variant]);
  const [expressionId, setExpressionId] = useState(expressions[0]?.id ?? '');
  const expression = (expressions.find((item) => item.id === expressionId) ?? expressions[0])?.value;
  const [block, setBlock] = useState<[number, number]>([0, 0]);

  const inputGroups = useMemo<SymbolicGroupDescriptor[]>(
    () => [{ name: 'Inputs', indices: model.inputs.map((_, index) => index) }],
    [model.inputs],
  );
  const rowGroups = expression?.kind === 'equation' && expression.item.rowGroups === 'outputs'
    ? model.outputGroups
    : model.stateBlocks;
  const columnGroups = expression?.kind === 'jacobian'
    ? expression.item.columnGroups === 'inputs' ? inputGroups : model.stateBlocks
    : [];
  const rowBlock = Math.min(block[0], Math.max(0, rowGroups.length - 1));
  const columnBlock = Math.min(block[1], Math.max(0, columnGroups.length - 1));
  const stateLabels = useMemo(() => model.states.map((state) => state.latex), [model.states]);
  const inputLabels = useMemo(() => model.inputs.map((input) => input.latex), [model.inputs]);

  const rendered = useMemo(() => {
    if (!expression) {
      return null;
    }
    const rows = rowGroups[rowBlock]?.indices ?? [];
    if (expression.kind === 'equation') {
      return { body: equationLatex(expression.item, rows), where: [] as string[] };
    }
    const jacobian = expression.item;
    const columns = columnGroups[columnBlock]?.indices ?? [];
    const rowSet = new Set(rows);
    const columnSet = new Set(columns);
    const entries = new Map<string, string>();
    const used = new Set<number>();
    for (const [row, column, latex, uses] of jacobian.entries) {
      if (rowSet.has(row) && columnSet.has(column)) {
        entries.set(`${row},${column}`, latex);
        uses.forEach((index) => used.add(index));
      }
    }
    const columnLabels = jacobian.columnGroups === 'inputs' ? inputLabels : stateLabels;
    return {
      body: blockLatex(entries, rows, columns, stateLabels, columnLabels),
      where: intermediateClosure(jacobian, used).map((index) => {
        const item = jacobian.intermediates[index];
        return `${item.name} &= ${item.latex}`;
      }),
      nonzero: entries.size,
    };
  }, [columnBlock, columnGroups, expression, inputLabels, rowBlock, rowGroups, stateLabels]);

  const selectVariant = (id: string) => {
    setVariantId(id);
    setExpressionId('');
    setBlock([0, 0]);
  };

  return (
    <div className="symbolic-model-body">
      <SymbolHeader model={model} rms={variant?.id === 'rms'} />
      <div className="symbolic-controls">
        <div className="symbolic-segmented" role="group" aria-label="Model">
          {model.models.map((item) => (
            <button
              key={item.id}
              type="button"
              className={item.id === variant?.id ? 'active' : ''}
              onClick={() => selectVariant(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="symbolic-segmented" role="group" aria-label="Expression">
          {expressions.map((item) => (
            <button
              key={item.id}
              type="button"
              className={item.value === expression ? 'active' : ''}
              onClick={() => setExpressionId(item.id)}
              title={item.value.item.label}
            >
              {item.label}
            </button>
          ))}
        </div>
        <label>
          <span>Rows</span>
          <select value={rowBlock} onChange={(event) => setBlock([Number(event.target.value), columnBlock])}>
            {rowGroups.map((group, index) => (
              <option key={group.name} value={index}>{index + 1}. {group.name} ({group.indices.length})</option>
            ))}
          </select>
        </label>
        {expression?.kind === 'jacobian' && (
          <label>
            <span>Columns</span>
            <select value={columnBlock} onChange={(event) => setBlock([rowBlock, Number(event.target.value)])}>
              {columnGroups.map((group, index) => (
                <option key={group.name} value={index}>{index + 1}. {group.name} ({group.indices.length})</option>
              ))}
            </select>
          </label>
        )}
      </div>
      {variant && <p className="symbolic-muted">{variant.description}</p>}
      {expression && (
        <div className={`symbolic-view${expression.kind === 'jacobian' ? ' with-map' : ''}`}>
          {expression.kind === 'jacobian' && (
            <SparsityMap
              jacobian={expression.item}
              rowGroups={rowGroups}
              columnGroups={columnGroups}
              selected={[rowBlock, columnBlock]}
              onSelect={(row, column) => setBlock([row, column])}
            />
          )}
          <div className="symbolic-block">
            <div className="symbolic-block-title">
              <strong>{expression.item.label}</strong>
              <span>
                {rowGroups[rowBlock]?.name}
                {expression.kind === 'jacobian' && ` × ${columnGroups[columnBlock]?.name}`}
                {rendered && 'nonzero' in rendered && ` · ${rendered.nonzero} nonzero`}
              </span>
            </div>
            {rendered && (
              <div className="symbolic-equation-scroll">
                <Latex className="symbolic-equation-latex" expression={rendered.body} display />
                {rendered.where.length > 0 && (
                  <>
                    <div className="symbolic-where">where</div>
                    <Latex
                      className="symbolic-equation-latex"
                      expression={String.raw`\begin{aligned}${rendered.where.join(String.raw`\\[2pt]`)}\end{aligned}`}
                      display
                    />
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Symbolic EMT and RMS models. Matrices are shown one block at a time (device
 * block × device block), with the CSE intermediates that block uses, so even
 * large systems render quickly. Nothing renders until the card is opened.
 */
export function SymbolicModelPanel({ model }: { model: SymbolicModelDescriptor }) {
  const [opened, setOpened] = useState(false);
  return (
    <section className="symbolic-equations-card">
      <details
        className="symbolic-model-details"
        onToggle={(event) => setOpened(event.currentTarget.open)}
      >
        <summary>
          <h2>Symbolic model</h2>
          <span className="symbolic-muted">
            {model.states.length} states · {model.inputs.length} inputs · {model.stateBlocks.length} blocks · EMT and RMS
          </span>
        </summary>
        {opened && <SymbolicModelBody model={model} />}
      </details>
    </section>
  );
}
