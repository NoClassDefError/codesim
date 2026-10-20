import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type OnEdgesChange,
  type OnNodesChange,
} from '@xyflow/react';
import type { Selection } from '../model/types';
import type { SystemFlowEdge, SystemFlowNode } from '../model/flowModel';
import { RoutedEdge } from './RoutedEdge';
import { SystemNode } from './SystemNode';

const nodeTypes = { systemNode: SystemNode };
const edgeTypes = { routed: RoutedEdge };

interface Props {
  nodes: SystemFlowNode[];
  edges: SystemFlowEdge[];
  onNodesChange: OnNodesChange<SystemFlowNode>;
  onEdgesChange: OnEdgesChange<SystemFlowEdge>;
  onSelectionChange: (selection: Selection) => void;
}

export function TopologyView({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onSelectionChange,
}: Props) {
  return (
    <ReactFlow<SystemFlowNode, SystemFlowEdge>
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onSelectionChange={({ nodes: selectedNodes, edges: selectedEdges }) => {
        if (selectedNodes[0]) {
          onSelectionChange({ kind: 'component', id: selectedNodes[0].id });
        } else if (selectedEdges[0]) {
          onSelectionChange({ kind: 'connection', id: selectedEdges[0].id });
        }
      }}
      onPaneClick={() => onSelectionChange(null)}
      nodesDraggable
      nodesConnectable={false}
      edgesReconnectable={false}
      deleteKeyCode={null}
      fitView
      minZoom={0.25}
      maxZoom={2}
    >
      <Background gap={24} size={1} />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable />
    </ReactFlow>
  );
}
