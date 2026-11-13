export type ComponentKind =
  | 'bus'
  | 'grid'
  | 'gfm'
  | 'gfl'
  | 'generator'
  | 'load'
  | 'motor'
  | 'capacitor'
  | 'controller'
  | 'ground'
  | 'generic';

export type PortSide = 'top' | 'right' | 'bottom' | 'left';

export interface SourceReference {
  file: string;
  line: number;
  column?: number;
}

export type ParameterValue = string | number | boolean | null | ParameterValue[];

export interface ParameterDescriptor {
  id: string;
  label: string;
  value: ParameterValue;
  unit?: string;
  group?: string;
  source?: SourceReference;
  editable?: boolean;
}

export interface ComponentDescriptor {
  id: string;
  name: string;
  className: string;
  kind: ComponentKind;
  icon?: string;
  portType?: string;
  parameters: ParameterDescriptor[];
  classSource?: SourceReference;
  instanceSource?: SourceReference;
}

export interface ConnectionDescriptor {
  id: string;
  name: string;
  source: string;
  target: string;
  sourceHandle?: PortSide;
  targetHandle?: PortSide;
  parameters?: ParameterDescriptor[];
  sourceReference?: SourceReference;
}

export interface SnapshotLayout {
  version: 1;
  nodes: Record<string, {
    x: number;
    y: number;
    terminalSide?: PortSide;
  }>;
  edges: Record<string, {
    waypoint?: { x: number; y: number };
    /** Orthogonal route from the automatic layout, source to target, in flow coordinates. */
    points?: Array<{ x: number; y: number }>;
    sourceSide?: PortSide;
    targetSide?: PortSide;
  }>;
}

export interface SignalDescriptor {
  id: string;
  componentId?: string;
  ownerId?: string;
  ownerKind?: 'system' | 'component' | 'connection';
  category?: 'state' | 'output';
  label: string;
  unit: string;
  time: number[];
  values: number[];
}

export type SignalOperation = 'magnitude' | 'power' | 'error';

export interface DerivedSignalDefinition {
  id: string;
  leftId: string;
  rightId: string;
  operation: SignalOperation;
  label: string;
}

export interface SmallSignalMode {
  mode: number;
  realPart: number;
  imaginaryPart: number;
  frequencyHz: number;
  dampingRatio: number;
  stability: 'Stable' | 'Unstable' | 'Marginal' | string;
  dominantState: string;
  dominantParticipation: number;
}

/** A symbol of the symbolic model (state or input). */
export interface SymbolicSymbolDescriptor {
  name: string;
  latex: string;
}

export interface SymbolicStateDescriptor extends SymbolicSymbolDescriptor {
  /** Index into `stateBlocks`. */
  block: number;
  /** Role of the state in the RMS model. */
  rms: 'differential' | 'algebraic';
}

/** A named group of rows/columns (state block of one device, or output group). */
export interface SymbolicGroupDescriptor {
  name: string;
  indices: number[];
}

export interface SymbolicEquationDescriptor {
  id: string;
  label: string;
  rowGroups: 'states' | 'outputs';
  /** One row per state/output: `lhs = latex`. */
  rows: Array<{ lhs: string; latex: string }>;
}

/** `[row, column, latex, used intermediates]` of one nonzero entry. */
export type SymbolicJacobianEntry = [number, number, string, number[]];

/** Jacobian in CSE form: nonzero entries written with intermediates `w_k`. */
export interface SymbolicJacobianDescriptor {
  id: string;
  label: string;
  rowGroups: 'states';
  columnGroups: 'states' | 'inputs';
  shape: [number, number];
  entries: SymbolicJacobianEntry[];
  intermediates: Array<{ name: string; latex: string; uses: number[] }>;
}

export interface SymbolicModelVariantDescriptor {
  id: string;
  label: string;
  description: string;
  equations: SymbolicEquationDescriptor[];
  jacobians: SymbolicJacobianDescriptor[];
}

/** Symbolic EMT and RMS models, organised in blocks (see serializeSymbolicModel). */
export interface SymbolicModelDescriptor {
  states: SymbolicStateDescriptor[];
  inputs: SymbolicSymbolDescriptor[];
  stateBlocks: SymbolicGroupDescriptor[];
  outputGroups: SymbolicGroupDescriptor[];
  models: SymbolicModelVariantDescriptor[];
}

export interface SmallSignalDescriptor {
  available: boolean;
  normalizedTime: boolean;
  unstablePoleCount: number;
  poleTolerance: number;
  modes: SmallSignalMode[];
  symbolicModel?: SymbolicModelDescriptor;
}

export interface ComplexValueDescriptor {
  realPart: number;
  imaginaryPart: number;
  magnitude: number;
}

export interface InteractionBlockDescriptor {
  name: string;
  startMode: number;
  endMode: number;
  stateNames: string[];
}

export interface InteractionModeShift {
  mode: number;
  relatedState: string;
  localEigenvalue: string;
  fullEigenvalue: string;
  reducedEigenvalue: string;
  deltaEigenvalue: string;
  localPoint?: ComplexValueDescriptor;
  fullPoint?: ComplexValueDescriptor;
  reducedPoint?: ComplexValueDescriptor;
  deltaPoint?: ComplexValueDescriptor;
}

export interface InteractionLocalMode {
  mode: number;
  label: string;
  eigenvalue: string;
  naturalFrequency: number;
  dampingRatio: number;
  dominantState: string;
}

export interface InteractionMatrixDescriptor {
  rowLabels: string[];
  columnLabels: string[];
  real: number[][];
  imaginary: number[][];
  magnitude: number[][];
}

export interface InteractionAnalysisDescriptor {
  available: boolean;
  parameterName: string;
  parameterValue: number | null;
  partition: number[];
  partitionStateNames: string[];
  blockStarts: number[];
  blocks: InteractionBlockDescriptor[];
  maskedRows: number[];
  maskedColumns: number[];
  estimatedShift: ComplexValueDescriptor | null;
  reconstructionErrorFro: number;
  modeShifts: InteractionModeShift[];
  localModes: InteractionLocalMode[];
  matrices: {
    dAll: InteractionMatrixDescriptor;
    aOriginal: InteractionMatrixDescriptor;
    aPartitioned: InteractionMatrixDescriptor;
    aBack: InteractionMatrixDescriptor;
  };
}

/** RMS (phasor) run and its optional first-order RMS+Δ correction. */
export interface RMSSimulationDescriptor {
  available: boolean;
  /** True while an RMS run streams; only `signals` is filled until it completes. */
  streaming?: boolean;
  model: 'RMS' | 'RMS+Delta';
  simulationTime_s?: number;
  differentialStateNames: string[];
  algebraicStateNames: string[];
  time_s: number[];
  algebraicResidual: Array<number | null>;
  maxAlgebraicResidual: number;
  /** RMS signals; corrected ones carry an `[RMS+Δ]` label suffix. */
  signals: SignalDescriptor[];
  cutoff_Hz?: number;
  correctionTime_s?: number;
  quasiStaticModeCount?: number[];
  maxQuasiStaticModeCount?: number;
}

export interface SystemSnapshot {
  schemaVersion: number;
  system: {
    id: string;
    name: string;
    className: string;
    parameterNames?: string[];
    parameters?: ParameterDescriptor[];
    source?: SourceReference;
  };
  components: ComponentDescriptor[];
  connections: ConnectionDescriptor[];
  signals: SignalDescriptor[];
  smallSignal?: SmallSignalDescriptor;
  interactionAnalysis?: InteractionAnalysisDescriptor;
  rmsSimulation?: RMSSimulationDescriptor;
  layout?: SnapshotLayout;
}

export type Selection =
  | { kind: 'component'; id: string }
  | { kind: 'connection'; id: string }
  | null;
