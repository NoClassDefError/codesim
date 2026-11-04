import ELK from 'elkjs/lib/elk.bundled.js';
import type { ElkExtendedEdge, ElkNode, ElkPort, LayoutOptions } from 'elkjs/lib/elk-api';
import type { PortSide } from './types';

/**
 * Automatic topology layout with the Eclipse Layout Kernel (ELK).
 *
 * ELK's layered algorithm places the nodes and routes every connection
 * orthogonally around them, which keeps large systems readable. It runs on the
 * webview's main thread: the bundled build needs no worker (the webview CSP
 * does not allow one) and lays out systems of this size in milliseconds.
 */

export interface Point {
  x: number;
  y: number;
}

export type LabelPlacement = 'above' | 'below' | 'right';

export interface LayoutNode {
  id: string;
  /** Box the node occupies, including space reserved below it (e.g. for a ground symbol). */
  width: number;
  height: number;
  /** Label drawn outside the box; ELK keeps other nodes and wires clear of it. */
  label?: { width: number; height: number; placement: LabelPlacement };
  /** Current position, for an interactive re-layout. */
  position?: Point;
}

export interface LayoutConnection {
  id: string;
  source: string;
  target: string;
  sourceSide: PortSide;
  targetSide: PortSide;
  /** Lay out against the drawing direction (e.g. a grid feeding its bus from the left). */
  reversed?: boolean;
}

export interface EdgeRoute {
  /** Polyline from the source port to the target port, in flow coordinates. */
  points: Point[];
  sourceSide: PortSide;
  targetSide: PortSide;
}

export interface ElkLayoutResult {
  positions: Map<string, Point>;
  routes: Map<string, EdgeRoute>;
}

export interface ElkLayoutRequest {
  nodes: LayoutNode[];
  connections: LayoutConnection[];
  /** Where a full layout is placed. */
  origin?: Point;
  /**
   * Interactive re-layout: ELK keeps the left-to-right layers and the
   * top-to-bottom order implied by the nodes' current positions.
   */
  interactive?: boolean;
  /** Node that stays where it is after an interactive re-layout (e.g. the one just dropped). */
  anchorId?: string;
}

const elk = new ELK();

const ELK_SIDE: Record<PortSide, string> = {
  left: 'WEST',
  right: 'EAST',
  top: 'NORTH',
  bottom: 'SOUTH',
};

const LABEL_PLACEMENT: Record<LabelPlacement, string> = {
  above: 'OUTSIDE V_TOP H_CENTER',
  below: 'OUTSIDE V_BOTTOM H_CENTER',
  // H_PRIORITY: beside the node, not above it aligned right.
  right: 'OUTSIDE V_TOP H_RIGHT H_PRIORITY',
};

const BASE_OPTIONS: LayoutOptions = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.edgeRouting': 'ORTHOGONAL',
  'elk.spacing.nodeNode': '40',
  'elk.layered.spacing.nodeNodeBetweenLayers': '70',
  'elk.spacing.edgeNode': '22',
  'elk.layered.spacing.edgeNodeBetweenLayers': '22',
  'elk.spacing.edgeEdge': '12',
  'elk.layered.spacing.edgeEdgeBetweenLayers': '12',
  'elk.spacing.portPort': '18',
  'elk.spacing.labelNode': '6',
  'elk.spacing.componentComponent': '90',
};

const FULL_LAYOUT_OPTIONS: LayoutOptions = {
  ...BASE_OPTIONS,
  'elk.separateConnectedComponents': 'true',
  // Follow the descriptor order where it does not cost crossings, so the
  // same system always gets the same picture.
  'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
  'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
};

const INTERACTIVE_OPTIONS: LayoutOptions = {
  ...BASE_OPTIONS,
  'elk.separateConnectedComponents': 'false',
  'elk.layered.cycleBreaking.strategy': 'INTERACTIVE',
  'elk.layered.layering.strategy': 'INTERACTIVE',
  'elk.layered.crossingMinimization.strategy': 'INTERACTIVE',
  'elk.layered.nodePlacement.strategy': 'INTERACTIVE',
  'elk.layered.interactiveReferencePoint': 'CENTER',
};

function portId(connectionId: string, end: 'source' | 'target'): string {
  return `${connectionId}::${end}`;
}

export async function computeElkLayout(request: ElkLayoutRequest): Promise<ElkLayoutResult> {
  const nodeIds = new Set(request.nodes.map((node) => node.id));
  const portsByNode = new Map<string, ElkPort[]>();
  const addPort = (nodeId: string, id: string, side: PortSide) => {
    portsByNode.set(nodeId, [
      ...(portsByNode.get(nodeId) ?? []),
      { id, width: 0, height: 0, layoutOptions: { 'elk.port.side': ELK_SIDE[side] } },
    ]);
  };

  const edges: ElkExtendedEdge[] = [];
  const connectionById = new Map<string, LayoutConnection>();
  for (const connection of request.connections) {
    if (!nodeIds.has(connection.source) || !nodeIds.has(connection.target)) {
      continue;
    }
    connectionById.set(connection.id, connection);
    const sourcePort = portId(connection.id, 'source');
    const targetPort = portId(connection.id, 'target');
    addPort(connection.source, sourcePort, connection.sourceSide);
    addPort(connection.target, targetPort, connection.targetSide);
    edges.push({
      id: connection.id,
      sources: [connection.reversed ? targetPort : sourcePort],
      targets: [connection.reversed ? sourcePort : targetPort],
    });
  }

  const graph: ElkNode = {
    id: 'root',
    layoutOptions: request.interactive ? INTERACTIVE_OPTIONS : FULL_LAYOUT_OPTIONS,
    children: request.nodes.map((node) => ({
      id: node.id,
      width: node.width,
      height: node.height,
      ...(request.interactive && node.position ? { x: node.position.x, y: node.position.y } : {}),
      layoutOptions: {
        'elk.portConstraints': 'FIXED_SIDE',
        ...(node.label ? { 'elk.nodeLabels.placement': LABEL_PLACEMENT[node.label.placement] } : {}),
      },
      labels: node.label ? [{ text: ' ', width: node.label.width, height: node.label.height }] : [],
      ports: portsByNode.get(node.id) ?? [],
    })),
    edges,
  };

  const layout = await elk.layout(graph);

  const positions = new Map<string, Point>();
  for (const child of layout.children ?? []) {
    positions.set(child.id, { x: child.x ?? 0, y: child.y ?? 0 });
  }

  // Full layouts start at the origin; interactive ones keep the anchor node in place.
  let offset: Point = request.origin ?? { x: 0, y: 0 };
  if (request.interactive) {
    const anchor = request.nodes.find((node) => node.id === request.anchorId) ??
      request.nodes.find((node) => node.position);
    const after = anchor ? positions.get(anchor.id) : undefined;
    offset = anchor?.position && after
      ? { x: anchor.position.x - after.x, y: anchor.position.y - after.y }
      : { x: 0, y: 0 };
  }
  const shift = (point: Point): Point => ({ x: point.x + offset.x, y: point.y + offset.y });
  positions.forEach((position, id) => positions.set(id, shift(position)));

  const routes = new Map<string, EdgeRoute>();
  for (const edge of layout.edges ?? []) {
    const section = edge.sections?.[0];
    const connection = connectionById.get(edge.id);
    if (!section || !connection) {
      continue;
    }
    const points = [section.startPoint, ...(section.bendPoints ?? []), section.endPoint].map(shift);
    routes.set(edge.id, {
      points: connection.reversed ? points.reverse() : points,
      sourceSide: connection.sourceSide,
      targetSide: connection.targetSide,
    });
  }

  return { positions, routes };
}
