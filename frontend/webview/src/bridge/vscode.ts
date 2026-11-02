import type {
  ParameterValue,
  SignalDescriptor,
  SnapshotLayout,
  SourceReference,
  SystemSnapshot,
} from '../model/types';

interface VsCodeApi {
  postMessage(message: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
}

export interface SimulationChunk {
  requestId: number;
  sequence: number;
  signals: SignalDescriptor[];
}

declare global {
  interface Window {
    acquireVsCodeApi?: () => VsCodeApi;
  }
}

const vscode = window.acquireVsCodeApi?.();

export function isInsideVsCode(): boolean {
  return Boolean(vscode);
}

export function requestSystemSnapshot(): void {
  vscode?.postMessage({ type: 'requestSystemSnapshot' });
}

export function requestBackendInfo(): void {
  vscode?.postMessage({ type: 'requestBackendInfo' });
}

export function startBackend(): void {
  vscode?.postMessage({ type: 'startBackend' });
}

export function stopBackend(): void {
  vscode?.postMessage({ type: 'stopBackend' });
}

export function loadSystemDescriptor(systemName: string): void {
  vscode?.postMessage({ type: 'loadSystemDescriptor', systemName });
}

export function runAnalysis(
  analysis: 'simulation' | 'smallSignal' | 'interaction',
  systemName: string,
): void {
  vscode?.postMessage({ type: 'runAnalysis', analysis, systemName });
}

export function runTransientVoltage(
  systemName: string,
  slowStateNames: string[],
  maxSamples: number,
): void {
  vscode?.postMessage({
    type: 'runTransientVoltage',
    systemName,
    slowStateNames,
    maxSamples,
  });
}

export function updateSystemParameter(name: string, value: ParameterValue): void {
  vscode?.postMessage({ type: 'updateSystemParameter', parameterName: name, parameterValue: value });
}

export function openSignalsView(): void {
  vscode?.postMessage({ type: 'openSignalsView' });
}

export function openSource(reference?: SourceReference): void {
  if (!reference) {
    return;
  }

  if (vscode) {
    vscode.postMessage({ type: 'openSource', reference });
  } else {
    console.info('Open source:', reference);
  }
}

export function saveLayout(layout: SnapshotLayout): void {
  vscode?.postMessage({ type: 'saveLayout', layout });
}

/**
 * Why the host sent a snapshot: 'load' after a model (re)load, 'analysis'
 * after an analysis finished, 'request' in reply to requestSystemSnapshot.
 */
export type SnapshotReason = 'load' | 'analysis' | 'request';

export function onSystemSnapshot(
  listener: (snapshot: SystemSnapshot, reason: SnapshotReason) => void,
): () => void {
  const handler = (event: MessageEvent) => {
    if (event.data?.type === 'systemSnapshot') {
      listener(
        event.data.snapshot as SystemSnapshot,
        (event.data.reason as SnapshotReason | undefined) ?? 'load',
      );
    }
  };

  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}

export function onSimulationStarted(listener: () => void): () => void {
  const handler = (event: MessageEvent) => {
    if (event.data?.type === 'simulation.started') {
      listener();
    }
  };
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}

export function onSimulationChunk(
  listener: (chunk: SimulationChunk) => void,
): () => void {
  const handler = (event: MessageEvent) => {
    if (event.data?.type === 'simulation.chunk') {
      listener(event.data as SimulationChunk);
    }
  };
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}

export interface BackendInfo {
  systems: string[];
  selectedSystem: string;
  backendRunning: boolean;
  running: boolean;
}

export interface BackendStatus {
  backendRunning?: boolean;
  running: boolean;
  action?: string;
  selectedSystem?: string;
}

export function onBackendInfo(listener: (info: BackendInfo) => void): () => void {
  const handler = (event: MessageEvent) => {
    if (event.data?.type === 'backendInfo') {
      listener(event.data as BackendInfo);
    }
  };
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}

export function onBackendStatus(
  listener: (status: BackendStatus) => void,
): () => void {
  const handler = (event: MessageEvent) => {
    if (event.data?.type === 'backendStatus') {
      listener(event.data as BackendStatus);
    }
  };
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}
