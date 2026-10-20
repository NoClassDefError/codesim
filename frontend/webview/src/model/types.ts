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

export interface SymbolicExpressionDescriptor {
  aSymLatex: string;
  fLatex: string;
  gLatex: string;
}

export interface SmallSignalDescriptor {
  available: boolean;
  normalizedTime: boolean;
  unstablePoleCount: number;
  poleTolerance: number;
  modes: SmallSignalMode[];
  symbolicExpressions?: SymbolicExpressionDescriptor;
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
  parameterValue: number;
  partition: number[];
  partitionStateNames: string[];
  blockStarts: number[];
  blocks: InteractionBlockDescriptor[];
  maskedRows: number[];
  maskedColumns: number[];
  estimatedShift: ComplexValueDescriptor;
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
  layout?: SnapshotLayout;
}

export type Selection =
  | { kind: 'component'; id: string }
  | { kind: 'connection'; id: string }
  | null;
