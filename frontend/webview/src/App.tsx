import { useCallback, useEffect, useRef, useState } from 'react';
import { useEdgesState, useNodesState, type OnNodeDrag } from '@xyflow/react';
import { onSystemSnapshot, requestSystemSnapshot, saveLayout } from './bridge/vscode';
import { Inspector } from './components/Inspector';
import { SystemTree } from './components/SystemTree';
import { Toolbar } from './components/Toolbar';
import { TopologyView } from './components/TopologyView';
import { mockSystem } from './model/mockSystem';
import {
  detachRoutes,
  layoutFlow,
  orientFlowEdges,
  relayoutFlow,
  topologySignature,
  type SystemFlowEdge,
  type SystemFlowNode,
} from './model/flowModel';
import type { PortSide, Selection, SnapshotLayout, SystemSnapshot } from './model/types';

export function App() {
  const [snapshot, setSnapshot] = useState<SystemSnapshot>(mockSystem);
  // The snapshot the canvas was laid out from. Analysis results arrive as new
  // snapshots of the same topology; re-running the layout for them would
  // rebuild every node and edge and drop unsaved drags and the selection.
  const [layoutSnapshot, setLayoutSnapshot] = useState<SystemSnapshot>(mockSystem);
  const [nodes, setNodes, onNodesChange] = useNodesState<SystemFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<SystemFlowEdge>([]);
  const [selection, setSelection] = useState<Selection>(null);
  // Latest canvas state, read by the asynchronous layout callbacks.
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  useEffect(() => {
    nodesRef.current = nodes;
    edgesRef.current = edges;
  }, [nodes, edges]);

  // Layouts finish asynchronously; only the most recently requested one is applied.
  const layoutRequest = useRef(0);
  const applyLayout = useCallback((
    pending: Promise<{ nodes: SystemFlowNode[]; edges: SystemFlowEdge[] }>,
  ) => {
    const request = ++layoutRequest.current;
    pending
      .then((flow) => {
        if (request === layoutRequest.current) {
          setNodes(flow.nodes);
          setEdges(flow.edges);
        }
      })
      .catch((error: unknown) => {
        console.warn('CodeSim: topology re-layout failed.', error);
      });
  }, [setEdges, setNodes]);

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
    setSelection(null);
    applyLayout(layoutFlow(layoutSnapshot));
  }, [applyLayout, layoutSnapshot]);

  useEffect(() => {
    setEdges((currentEdges) => orientFlowEdges(nodes, currentEdges));
  }, [nodes, setEdges]);

  const resetLayout = () => {
    applyLayout(layoutFlow(snapshot, { useSavedLayout: false }));
  };

  // While nodes move, their wires use the simple automatic route; on drop ELK
  // re-lays out the diagram, keeping the order the user chose.
  const onNodeDragStart: OnNodeDrag<SystemFlowNode> = (_event, _node, dragged) => {
    layoutRequest.current += 1;
    setEdges((current) => detachRoutes(current, new Set(dragged.map((item) => item.id))));
  };

  const onNodeDragStop: OnNodeDrag<SystemFlowNode> = (_event, node, dragged) => {
    const moved = new Map(dragged.map((item) => [item.id, item.position]));
    const current = nodesRef.current.map((item) => {
      const position = moved.get(item.id);
      return position ? { ...item, position } : item;
    });
    applyLayout(relayoutFlow(current, edgesRef.current, node.id));
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
          points: edge.data?.points,
          // Only user-fixed sides; automatic ones follow from the route.
          sourceSide: edge.data?.sourceSideLocked ? edge.data.sourceSide : undefined,
          targetSide: edge.data?.targetSideLocked ? edge.data.targetSide : undefined,
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
          // Redraw at once with the new side; the re-layout below routes it properly.
          points: undefined,
        },
      };
    }));
    setEdges(updatedEdges);
    applyLayout(relayoutFlow(nodes, updatedEdges, endpointId));

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
              onNodeDragStart={onNodeDragStart}
              onNodeDragStop={onNodeDragStop}
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
