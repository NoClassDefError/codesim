import { useEffect, useMemo, useState } from 'react';
import { useEdgesState, useNodesState } from '@xyflow/react';
import { onSystemSnapshot, requestSystemSnapshot, saveLayout } from './bridge/vscode';
import { Inspector } from './components/Inspector';
import { SystemTree } from './components/SystemTree';
import { Toolbar } from './components/Toolbar';
import { TopologyView } from './components/TopologyView';
import { mockSystem } from './model/mockSystem';
import { orientFlowEdges, snapshotToFlow, topologySignature } from './model/flowModel';
import type { PortSide, Selection, SnapshotLayout, SystemSnapshot } from './model/types';

export function App() {
  const [snapshot, setSnapshot] = useState<SystemSnapshot>(mockSystem);
  // The snapshot the canvas was laid out from. Analysis results arrive as new
  // snapshots of the same topology; re-running the layout for them would
  // rebuild every node and edge and drop unsaved drags and the selection.
  const [layoutSnapshot, setLayoutSnapshot] = useState<SystemSnapshot>(mockSystem);
  const initialFlow = useMemo(() => snapshotToFlow(layoutSnapshot), [layoutSnapshot]);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialFlow.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialFlow.edges);
  const [selection, setSelection] = useState<Selection>(null);

  useEffect(() => {
    const unsubscribe = onSystemSnapshot((next, reason) => {
      setSnapshot(next);
      setLayoutSnapshot((current) => (
        reason !== 'load' && topologySignature(current) === topologySignature(next)
          ? current
          : next
      ));
    });
    requestSystemSnapshot();
    return unsubscribe;
  }, []);

  useEffect(() => {
    setNodes(initialFlow.nodes);
    setEdges(initialFlow.edges);
    setSelection(null);
  }, [initialFlow, setEdges, setNodes]);

  useEffect(() => {
    setEdges((currentEdges) => orientFlowEdges(nodes, currentEdges));
  }, [nodes, setEdges]);

  const resetLayout = () => {
    const flow = snapshotToFlow(snapshot, { useSavedLayout: false });
    setNodes(flow.nodes);
    setEdges(flow.edges);
  };

  const saveCurrentLayout = () => {
    const layout: SnapshotLayout = {
      version: 1,
      nodes: Object.fromEntries(
        nodes.map((node) => [node.id, {
          x: node.position.x,
          y: node.position.y,
          terminalSide: node.data.terminalSide,
        }]),
      ),
      edges: Object.fromEntries(
        edges.map((edge) => [edge.id, {
          waypoint: edge.data?.waypoint,
          sourceSide: edge.data?.sourceSide,
          targetSide: edge.data?.targetSide,
        }]),
      ),
    };
    saveLayout(layout);
  };

  const changeConnectionPort = (
    connectionId: string,
    endpoint: 'source' | 'target',
    side?: PortSide,
  ) => {
    const connection = edges.find((edge) => edge.id === connectionId);
    const endpointId = endpoint === 'source' ? connection?.source : connection?.target;
    const updatedEdges = orientFlowEdges(nodes, edges.map((edge) => {
      if (edge.id !== connectionId) {
        return edge;
      }
      return {
        ...edge,
        data: {
          label: edge.data?.label ?? '',
          ...edge.data,
          [`${endpoint}Side`]: side,
          [`${endpoint}SideLocked`]: Boolean(side),
        },
      };
    }));
    setEdges(updatedEdges);

    const resolvedEdge = updatedEdges.find((edge) => edge.id === connectionId);
    const resolvedSide = endpoint === 'source'
      ? resolvedEdge?.data?.sourceSide
      : resolvedEdge?.data?.targetSide;
    if (resolvedSide && endpointId) {
      setNodes((currentNodes) => currentNodes.map((node) =>
        node.id === endpointId && node.data.component.kind !== 'bus'
          ? { ...node, data: { ...node.data, terminalSide: resolvedSide } }
          : node,
      ));
    }
  };

  const selectedEdge = selection?.kind === 'connection'
    ? edges.find((edge) => edge.id === selection.id)
    : undefined;

  return (
    <main className="app-shell">
      <Toolbar
        systemName={snapshot.system.name}
        onResetLayout={resetLayout}
        onSaveLayout={saveCurrentLayout}
        showSignalsButton
        view="topology"
      />

      <section className="workspace viewer-workspace">
        <SystemTree snapshot={snapshot} selection={selection} onSelect={setSelection} />
        <div className="topology-stage">
          <div className="topology-panel">
            <TopologyView
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onSelectionChange={setSelection}
            />
          </div>
          <Inspector
            snapshot={snapshot}
            selection={selection}
            connectionPorts={selectedEdge ? {
              sourceSide: selectedEdge.data?.sourceSide,
              targetSide: selectedEdge.data?.targetSide,
              sourceAutomatic: !selectedEdge.data?.sourceSideLocked,
              targetAutomatic: !selectedEdge.data?.targetSideLocked,
            } : undefined}
            onConnectionPortChange={changeConnectionPort}
          />
        </div>
      </section>
    </main>
  );
}
