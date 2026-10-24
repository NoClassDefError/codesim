import type { ComplexTraceDescriptor, SystemSnapshot } from './types';

const sourceRoot =
  'C:/Users/Macsw/OneDrive - KTH/ADVOCANO/-AVCI/codesim';

const time = Array.from({ length: 401 }, (_, index) => index * 0.001);

function complexTrace(magnitude: number[], phase: number[]): ComplexTraceDescriptor {
  return {
    real: magnitude.map((value, index) => [value * Math.cos(phase[index])]),
    imaginary: magnitude.map((value, index) => [value * Math.sin(phase[index])]),
    magnitude: magnitude.map((value) => [Math.abs(value)]),
  };
}

function addComplexTraces(...traces: ComplexTraceDescriptor[]): ComplexTraceDescriptor {
  const real = time.map((_, index) => [
    traces.reduce((sum, trace) => sum + (trace.real[index][0] ?? 0), 0),
  ]);
  const imaginary = time.map((_, index) => [
    traces.reduce((sum, trace) => sum + (trace.imaginary[index][0] ?? 0), 0),
  ]);
  return {
    real,
    imaginary,
    magnitude: real.map((row, index) => [Math.hypot(row[0], imaginary[index][0])]),
  };
}

const mockPhase = time.map((t) => 0.08 * Math.sin(2 * Math.PI * 2.2 * t));
const mockQss = complexTrace(
  time.map((t) => 1 - 0.16 * Math.exp(-7 * t) * Math.sin(2 * Math.PI * 3.2 * t)),
  mockPhase,
);
const mockFirstOrderError = complexTrace(
  time.map((t) => 0.018 * Math.exp(-5 * t) * Math.sin(2 * Math.PI * 3.2 * t - 0.5)),
  time.map(() => 0.35),
);
const mockFirstOrder = mockFirstOrderError;
const mockEmt = complexTrace(
  time.map((t) => 0.035 * Math.exp(-22 * t) * Math.sin(2 * Math.PI * 48 * t)),
  time.map((t) => 0.025 * Math.exp(-12 * t) * Math.cos(2 * Math.PI * 48 * t)),
);
const mockReconstructed = addComplexTraces(mockQss, mockFirstOrder, mockEmt);
const mockReconstructionError = complexTrace(
  time.map((t) => 0.003 * Math.exp(-18 * t) * Math.sin(2 * Math.PI * 31 * t)),
  mockPhase,
);
const mockActual = addComplexTraces(mockReconstructed, mockReconstructionError);

const mockInteractionMatrix = {
  rowLabels: ['1', '2', '3', '4'],
  columnLabels: ['1', '2', '3', '4'],
  real: [
    [-0.25, 0.02, 0.0, -0.01],
    [-0.03, -0.25, 0.04, 0.0],
    [0.0, -0.08, -2.41, 0.96],
    [0.05, 0.0, -0.96, -2.41],
  ],
  imaginary: [
    [0.99, 0.0, 0.0, 0.02],
    [0.0, -0.99, -0.02, 0.0],
    [0.0, 0.01, 39.35, 0.0],
    [-0.01, 0.0, 0.0, -39.35],
  ],
  magnitude: [
    [1.02, 0.02, 0.0, 0.02],
    [0.03, 1.02, 0.04, 0.0],
    [0.0, 0.08, 39.42, 0.96],
    [0.05, 0.0, 0.96, 39.42],
  ],
};

export const mockSystem: SystemSnapshot = {
  schemaVersion: 1,
  system: {
    id: 'two-bus-demo',
    name: 'Two-bus post-fault example',
    className: 'codesim.systems.TwoBusSystem',
    source: { file: `${sourceRoot}/+examples/TwoBusSystem.m`, line: 1 },
  },
  components: [
    {
      id: 'grid',
      name: 'Infinite bus',
      className: 'codesim.components.Infbus',
      kind: 'grid',
      icon: 'grid',
      parameters: [
        { id: 'V', label: 'Voltage', value: 1, unit: 'pu' },
        { id: 'f', label: 'Frequency', value: 50, unit: 'Hz' },
      ],
      classSource: { file: `${sourceRoot}/Infbus.m`, line: 1 },
      instanceSource: { file: `${sourceRoot}/+examples/TwoBusSystem.m`, line: 16 },
    },
    {
      id: 'bus-1',
      name: 'Bus 1',
      className: 'codesim.Bus',
      kind: 'bus',
      icon: 'bus',
      parameters: [{ id: 'Vbase', label: 'Base voltage', value: 1, unit: 'pu' }],
      classSource: { file: `${sourceRoot}/Bus.m`, line: 1 },
      instanceSource: { file: `${sourceRoot}/+examples/TwoBusSystem.m`, line: 18 },
    },
    {
      id: 'gfm-1',
      name: 'GFM 1',
      className: 'codesim.components.VSG',
      kind: 'gfm',
      icon: 'inverter',
      parameters: [
        { id: 'Pref', label: 'Active-power reference', value: 1, unit: 'pu', group: 'Reference' },
        { id: 'Qref', label: 'Reactive-power reference', value: 0, unit: 'pu', group: 'Reference' },
        { id: 'KpAPC', label: 'APC droop gain', value: 0.1, unit: 'pu', group: 'Controller' },
        { id: 'Rv', label: 'Virtual resistance', value: 0.1, unit: 'pu', group: 'Impedance' },
        { id: 'Lv', label: 'Virtual inductance', value: 0.3, unit: 'pu', group: 'Impedance' },
      ],
      classSource: { file: `${sourceRoot}/VSG.m`, line: 1 },
      instanceSource: { file: `${sourceRoot}/+examples/TwoBusSystem.m`, line: 22 },
    },
    {
      id: 'bus-2',
      name: 'Bus 2',
      className: 'codesim.Bus',
      kind: 'bus',
      icon: 'bus',
      parameters: [{ id: 'Vbase', label: 'Base voltage', value: 1, unit: 'pu' }],
      classSource: { file: `${sourceRoot}/Bus.m`, line: 1 },
      instanceSource: { file: `${sourceRoot}/+examples/TwoBusSystem.m`, line: 19 },
    },
    {
      id: 'load-1',
      name: 'ZIP load',
      className: 'codesim.components.ZIP',
      kind: 'load',
      icon: 'load',
      parameters: [
        { id: 'P', label: 'Active power', value: 0.5, unit: 'pu' },
        { id: 'Q', label: 'Reactive power', value: 0.2, unit: 'pu' },
      ],
      classSource: { file: `${sourceRoot}/ZIP.m`, line: 1 },
      instanceSource: { file: `${sourceRoot}/+examples/TwoBusSystem.m`, line: 28 },
    },
  ],
  connections: [
    { id: 'grid-bus-1', name: 'Grid connection', source: 'grid', target: 'bus-1' },
    {
      id: 'line-12',
      name: 'Line 1-2',
      source: 'bus-1',
      target: 'bus-2',
      parameters: [
        { id: 'R', label: 'Resistance', value: 0.02, unit: 'pu' },
        { id: 'X', label: 'Reactance', value: 0.2, unit: 'pu' },
      ],
      sourceReference: { file: `${sourceRoot}/+examples/TwoBusSystem.m`, line: 31 },
    },
    {
      id: 'bus-1-gfm',
      name: 'GFM terminal',
      source: 'bus-1',
      target: 'gfm-1',
      sourceHandle: 'bottom',
      targetHandle: 'top',
    },
    {
      id: 'bus-2-load',
      name: 'Load terminal',
      source: 'bus-2',
      target: 'load-1',
      sourceHandle: 'bottom',
      targetHandle: 'top',
    },
  ],
  signals: [
    {
      id: 'gfm-1-delta-gfm',
      componentId: 'gfm-1',
      ownerId: 'gfm-1',
      ownerKind: 'component',
      category: 'state',
      label: 'delta_gfm',
      unit: 'rad',
      time,
      values: time.map((t) => 0.12 * Math.sin(2 * Math.PI * 2.2 * t)),
    },
    {
      id: 'gfm-1-xccd-gfm',
      componentId: 'gfm-1',
      ownerId: 'gfm-1',
      ownerKind: 'component',
      category: 'state',
      label: 'xccd_gfm',
      unit: '',
      time,
      values: time.map((t) => 0.04 * Math.exp(-8 * t) * Math.sin(2 * Math.PI * 18 * t)),
    },
    {
      id: 'gfm-1.vpcc',
      componentId: 'gfm-1',
      label: 'PCC voltage',
      unit: 'pu',
      time,
      values: time.map((t) => 1 + 0.18 * Math.exp(-22 * t) * Math.sin(2 * Math.PI * 48 * t)),
    },
    {
      id: 'gfm-1.p',
      componentId: 'gfm-1',
      label: 'Active power',
      unit: 'pu',
      time,
      values: time.map((t) => 1 - 0.35 * Math.exp(-14 * t) * Math.cos(2 * Math.PI * 18 * t)),
    },
    {
      id: 'load-1.v',
      componentId: 'load-1',
      label: 'Load-bus voltage',
      unit: 'pu',
      time,
      values: time.map((t) => 1 - 0.12 * Math.exp(-18 * t) * Math.cos(2 * Math.PI * 35 * t)),
    },
  ],
  smallSignal: {
    available: true,
    normalizedTime: true,
    unstablePoleCount: 0,
    poleTolerance: 1e-7,
    symbolicExpressions: {
      aSymLatex: String.raw`\begin{bmatrix}-R_g/L_g & 1/L_g \\ -1/C & -G_d/C\end{bmatrix}`,
      fLatex: String.raw`\begin{bmatrix}(v_1-v_2-R_g i_g)/L_g \\ (-i_g-G_d v_2)/C\end{bmatrix}`,
      gLatex: String.raw`\begin{bmatrix}i_g \\ v_1 \\ v_2\end{bmatrix}`,
    },
    modes: [
      { mode: 1, realPart: 0, imaginaryPart: 0, frequencyHz: 0, dampingRatio: 0, stability: 'Marginal', dominantState: 'theta_grid', dominantParticipation: 1 },
      { mode: 2, realPart: -0.086, imaginaryPart: 0, frequencyHz: 0, dampingRatio: 1, stability: 'Stable', dominantState: 'delta_gfm', dominantParticipation: 0.92 },
      { mode: 3, realPart: -0.25, imaginaryPart: 0.99, frequencyHz: 49.5, dampingRatio: 0.245, stability: 'Stable', dominantState: 'i_gd', dominantParticipation: 0.49 },
      { mode: 4, realPart: -0.25, imaginaryPart: -0.99, frequencyHz: 49.5, dampingRatio: 0.245, stability: 'Stable', dominantState: 'i_gq', dominantParticipation: 0.49 },
      { mode: 5, realPart: -2.41, imaginaryPart: 39.35, frequencyHz: 1968, dampingRatio: 0.061, stability: 'Stable', dominantState: 'v_cq', dominantParticipation: 0.24 },
      { mode: 6, realPart: -2.41, imaginaryPart: -39.35, frequencyHz: 1968, dampingRatio: 0.061, stability: 'Stable', dominantState: 'v_cd', dominantParticipation: 0.24 },
    ],
  },
  interactionAnalysis: {
    available: true,
    parameterName: 'Lg1',
    parameterValue: 0.66663,
    partition: [5, 6, 7, 8],
    partitionStateNames: ['xccd_gfm', 'xccq_gfm', 'id_gfl', 'iq_gfl'],
    blockStarts: [1, 3],
    blocks: [
      { name: 'GFM', startMode: 1, endMode: 2, stateNames: ['xccd_gfm', 'xccq_gfm'] },
      { name: 'GFL', startMode: 3, endMode: 4, stateNames: ['id_gfl', 'iq_gfl'] },
    ],
    maskedRows: [1, 2],
    maskedColumns: [3, 4],
    estimatedShift: { realPart: -0.0012, imaginaryPart: 0.0004, magnitude: 0.001265 },
    reconstructionErrorFro: 0.084,
    modeShifts: [
      { mode: 1, relatedState: 'xccd_gfm', localEigenvalue: '-2.5e-1+9.9e-1j', fullEigenvalue: '-2.4e-1+1.0e+0j', reducedEigenvalue: '-2.5e-1+9.9e-1j', deltaEigenvalue: '1.0e-2+1.0e-2j' },
      { mode: 2, relatedState: 'xccq_gfm', localEigenvalue: '-2.5e-1-9.9e-1j', fullEigenvalue: '-2.4e-1-1.0e+0j', reducedEigenvalue: '-2.5e-1-9.9e-1j', deltaEigenvalue: '1.0e-2-1.0e-2j' },
      { mode: 3, relatedState: 'id_gfl', localEigenvalue: '-2.4e+0+3.9e+1j', fullEigenvalue: '-2.5e+0+3.9e+1j', reducedEigenvalue: '-2.4e+0+3.9e+1j', deltaEigenvalue: '-1.0e-1+0.0e+0j' },
      { mode: 4, relatedState: 'iq_gfl', localEigenvalue: '-2.4e+0-3.9e+1j', fullEigenvalue: '-2.5e+0-3.9e+1j', reducedEigenvalue: '-2.4e+0-3.9e+1j', deltaEigenvalue: '-1.0e-1+0.0e+0j' },
    ],
    localModes: [
      { mode: 1, label: '1', eigenvalue: '-2.500e-1+9.900e-1j', naturalFrequency: 1.02, dampingRatio: 0.245, dominantState: 'xccd_gfm' },
      { mode: 2, label: '2', eigenvalue: '-2.500e-1-9.900e-1j', naturalFrequency: 1.02, dampingRatio: 0.245, dominantState: 'xccq_gfm' },
      { mode: 3, label: '3', eigenvalue: '-2.410e+0+3.935e+1j', naturalFrequency: 39.42, dampingRatio: 0.061, dominantState: 'id_gfl' },
      { mode: 4, label: '4', eigenvalue: '-2.410e+0-3.935e+1j', naturalFrequency: 39.42, dampingRatio: 0.061, dominantState: 'iq_gfl' },
    ],
    matrices: {
      dAll: mockInteractionMatrix,
      aOriginal: mockInteractionMatrix,
      aPartitioned: mockInteractionMatrix,
      aBack: mockInteractionMatrix,
    },
  },
  transientVoltage: {
    available: true,
    time_s: time,
      sourceSampleCount: time.length,
      sampleIndices: time.map((_, index) => index),
    busNames: ['Bus 1'],
    slowStateNames: ['delta_gfm'],
    fastStateNames: ['id_grid', 'iq_grid', 'xccd_gfm', 'xccq_gfm'],
    angleStateName: 'delta_gfm',
    angleRate_rad_s: time.map((t) => 0.12 * 2 * Math.PI * 2.2 * Math.cos(2 * Math.PI * 2.2 * t)),
    slowStateRates_per_s: time.map((t) => [
      0.12 * 2 * Math.PI * 2.2 * Math.cos(2 * Math.PI * 2.2 * t),
    ]),
    qssConverged: time.map(() => true),
    qssResidualNorm: time.map((t) => 2e-10 + 3e-9 * Math.abs(Math.sin(2 * Math.PI * 3 * t))),
    fastJacobianCondition: time.map((t) => 18 + 4 * Math.abs(Math.sin(2 * Math.PI * 1.5 * t))),
      firstOrderAvailable: time.map(() => true),
    components: {
      actual: mockActual,
      qss: mockQss,
      firstOrderError: mockFirstOrderError,
      firstOrder: mockFirstOrder,
      emt: mockEmt,
      reconstructed: mockReconstructed,
      reconstructionError: mockReconstructionError,
    },
  },
};
