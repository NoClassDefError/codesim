import type { Edge, Node } from '@xyflow/react';
import type {
  ComponentDescriptor,
  ComponentKind,
  PortSide,
  SystemSnapshot,
} from './types';

export interface SystemNodeData extends Record<string, unknown> {
  component: ComponentDescriptor;
  terminalSide?: PortSide;
}

export interface RoutedEdgeData extends Record<string, unknown> {
  label: string;
  waypoint?: { x: number; y: number };
  routeAxis?: 'horizontal' | 'vertical';
  laneOffset?: number;
  sourceSide?: PortSide;
  targetSide?: PortSide;
  sourceSideLocked?: boolean;
  targetSideLocked?: boolean;
}

export type SystemFlowNode = Node<SystemNodeData, 'systemNode'>;
export type SystemFlowEdge = Edge<RoutedEdgeData, 'routed'>;

interface Point {
  x: number;
  y: number;
}

const BUS_WIDTH = 76;
const BUS_HEIGHT = 92;
const DEVICE_WIDTH = 116;
const DEVICE_HEIGHT = 106;
const BUS_COLUMN_GAP = 270;
const BUS_ROW_GAP = 290;
const DEVICE_CLEARANCE = 86;
const DEVICE_GAP = 138;
const COMPONENT_GAP = 190;
const ORIGIN_X = 150;
const ORIGIN_Y = 100;

function nodeSize(component: ComponentDescriptor): { width: number; height: number } {
  return component.kind === 'bus'
    ? { width: BUS_WIDTH, height: BUS_HEIGHT }
    : { width: DEVICE_WIDTH, height: DEVICE_HEIGHT };
}

function centerOf(node: SystemFlowNode): Point {
  const size = nodeSize(node.data.component);
  return {
    x: node.position.x + size.width / 2,
    y: node.position.y + size.height / 2,
  };
}

function isReferenceBus(component: ComponentDescriptor, degree: number, busCount: number): boolean {
  const identity = `${component.id} ${component.name}`.toLowerCase();
  return /(^|[-_\s])(ground|gnd|earth)([-_\s]|$)/.test(identity) ||
    (busCount > 7 && degree >= Math.max(5, Math.ceil(busCount * 0.55)));
}

function connectedComponents(ids: string[], adjacency: Map<string, Set<string>>): string[][] {
  const remaining = new Set(ids);
  const components: string[][] = [];

  while (remaining.size > 0) {
    const seed = remaining.values().next().value as string;
    const queue = [seed];
    const component: string[] = [];
    remaining.delete(seed);

    while (queue.length > 0) {
      const current = queue.shift()!;
      component.push(current);
      for (const neighbor of adjacency.get(current) ?? []) {
        if (remaining.delete(neighbor)) {
          queue.push(neighbor);
        }
      }
    }
    components.push(component);
  }
  return components;
}

function layoutBusComponent(
  ids: string[],
  adjacency: Map<string, Set<string>>,
  gridAttachedBuses: Set<string>,
  top: number,
): { positions: Map<string, Point>; bottom: number; right: number } {
  const order = new Map(ids.map((id, index) => [id, index]));
  const root = [...ids].sort((left, right) => {
    const leftGrid = gridAttachedBuses.has(left) ? 1 : 0;
    const rightGrid = gridAttachedBuses.has(right) ? 1 : 0;
    if (leftGrid !== rightGrid) {
      return rightGrid - leftGrid;
    }
    const leftDegree = adjacency.get(left)?.size ?? 0;
    const rightDegree = adjacency.get(right)?.size ?? 0;
    const leftEndpoint = leftDegree <= 1 ? 1 : 0;
    const rightEndpoint = rightDegree <= 1 ? 1 : 0;
    if (leftEndpoint !== rightEndpoint) {
      return rightEndpoint - leftEndpoint;
    }
    return (order.get(left) ?? 0) - (order.get(right) ?? 0);
  })[0];

  const depth = new Map<string, number>([[root, 0]]);
  const queue = [root];
  while (queue.length > 0) {
    const current = queue.shift()!;
    for (const neighbor of adjacency.get(current) ?? []) {
      if (!depth.has(neighbor) && order.has(neighbor)) {
        depth.set(neighbor, (depth.get(current) ?? 0) + 1);
        queue.push(neighbor);
      }
    }
  }

  const layers = new Map<number, string[]>();
  for (const id of ids) {
    const layer = depth.get(id) ?? 0;
    layers.set(layer, [...(layers.get(layer) ?? []), id]);
  }
  const layerNumbers = [...layers.keys()].sort((a, b) => a - b);
  const row = new Map<string, number>();
  for (const layer of layerNumbers) {
    const values = layers.get(layer)!;
    values.sort((left, right) => (order.get(left) ?? 0) - (order.get(right) ?? 0));
    values.forEach((id, index) => row.set(id, index));
  }

  // Barycentric sweeps keep branches close to their parents and reduce crossings.
  for (let pass = 0; pass < 4; pass += 1) {
    const sweep = pass % 2 === 0 ? layerNumbers : [...layerNumbers].reverse();
    for (const layer of sweep) {
      const values = layers.get(layer)!;
      values.sort((left, right) => {
        const barycenter = (id: string) => {
          const neighbors = [...(adjacency.get(id) ?? [])]
            .filter((neighbor) => (depth.get(neighbor) ?? -1) !== layer)
            .map((neighbor) => row.get(neighbor))
            .filter((value): value is number => value !== undefined);
          return neighbors.length > 0
            ? neighbors.reduce((sum, value) => sum + value, 0) / neighbors.length
            : row.get(id) ?? 0;
        };
        return barycenter(left) - barycenter(right) ||
          (order.get(left) ?? 0) - (order.get(right) ?? 0);
      });
      values.forEach((id, index) => row.set(id, index));
    }
  }

  const maxRows = Math.max(...[...layers.values()].map((items) => items.length), 1);
  const positions = new Map<string, Point>();
  for (const layer of layerNumbers) {
    const values = layers.get(layer)!;
    const layerTop = top + (maxRows - values.length) * BUS_ROW_GAP / 2;
    values.forEach((id, index) => {
      positions.set(id, {
        x: ORIGIN_X + layer * BUS_COLUMN_GAP,
        y: layerTop + index * BUS_ROW_GAP,
      });
    });
  }

  const maxLayer = Math.max(...layerNumbers, 0);
  return {
    positions,
    bottom: top + (maxRows - 1) * BUS_ROW_GAP + BUS_HEIGHT,
    right: ORIGIN_X + maxLayer * BUS_COLUMN_GAP + BUS_WIDTH,
  };
}

function layoutSnapshot(snapshot: SystemSnapshot): {
  positions: Map<string, Point>;
  terminalSides: Map<string, PortSide>;
} {
  const componentById = new Map(snapshot.components.map((component) => [component.id, component]));
  const buses = snapshot.components.filter((component) => component.kind === 'bus');
  const busIds = new Set(buses.map((bus) => bus.id));
  const adjacency = new Map(buses.map((bus) => [bus.id, new Set<string>()]));
  const attachments = new Map<string, string[]>();
  const gridAttachedBuses = new Set<string>();

  for (const connection of snapshot.connections) {
    const sourceIsBus = busIds.has(connection.source);
    const targetIsBus = busIds.has(connection.target);
    if (sourceIsBus && targetIsBus) {
      adjacency.get(connection.source)?.add(connection.target);
      adjacency.get(connection.target)?.add(connection.source);
    } else if (sourceIsBus !== targetIsBus) {
      const busId = sourceIsBus ? connection.source : connection.target;
      const deviceId = sourceIsBus ? connection.target : connection.source;
      attachments.set(busId, [...(attachments.get(busId) ?? []), deviceId]);
      if (componentById.get(deviceId)?.kind === 'grid') {
        gridAttachedBuses.add(busId);
      }
    }
  }

  const referenceIds = new Set(
    buses
      .filter((bus) => isReferenceBus(bus, adjacency.get(bus.id)?.size ?? 0, buses.length))
      .map((bus) => bus.id),
  );
  const regularIds = buses.map((bus) => bus.id).filter((id) => !referenceIds.has(id));
  const regularAdjacency = new Map(
    regularIds.map((id) => [
      id,
      new Set([...(adjacency.get(id) ?? [])].filter((neighbor) => !referenceIds.has(neighbor))),
    ]),
  );
  const positions = new Map<string, Point>();
  let componentTop = ORIGIN_Y;
  let right = ORIGIN_X;

  for (const ids of connectedComponents(regularIds, regularAdjacency)) {
    const layout = layoutBusComponent(ids, regularAdjacency, gridAttachedBuses, componentTop);
    layout.positions.forEach((position, id) => positions.set(id, position));
    componentTop = layout.bottom + COMPONENT_GAP;
    right = Math.max(right, layout.right);
  }

  const regularBottom = Math.max(
    ORIGIN_Y + BUS_HEIGHT,
    ...[...positions.values()].map((position) => position.y + BUS_HEIGHT),
  );
  const references = buses.filter((bus) => referenceIds.has(bus.id));
  references.forEach((bus, index) => {
    positions.set(bus.id, {
      x: ORIGIN_X + (right - ORIGIN_X - BUS_WIDTH) * (index + 1) / (references.length + 1),
      y: regularBottom + BUS_ROW_GAP,
    });
  });

  // A system with only reference buses still needs deterministic positions.
  buses.forEach((bus, index) => {
    if (!positions.has(bus.id)) {
      positions.set(bus.id, { x: ORIGIN_X + index * BUS_COLUMN_GAP, y: ORIGIN_Y });
    }
  });

  const terminalSides = new Map<string, PortSide>();
  const attachedDeviceIds = new Set<string>();
  for (const bus of buses) {
    const busPosition = positions.get(bus.id)!;
    const deviceIds = attachments.get(bus.id) ?? [];
    const gridIds = deviceIds.filter((id) => componentById.get(id)?.kind === 'grid');
    const remainingIds = deviceIds.filter((id) => componentById.get(id)?.kind !== 'grid');

    const placeRow = (ids: string[], side: 'top' | 'bottom') => {
      const startX = busPosition.x + BUS_WIDTH / 2 -
        ((ids.length - 1) * DEVICE_GAP + DEVICE_WIDTH) / 2;
      ids.forEach((id, index) => {
        positions.set(id, {
          x: startX + index * DEVICE_GAP,
          y: side === 'bottom'
            ? busPosition.y + BUS_HEIGHT + DEVICE_CLEARANCE
            : busPosition.y - DEVICE_HEIGHT - DEVICE_CLEARANCE,
        });
        terminalSides.set(id, side === 'bottom' ? 'top' : 'bottom');
        attachedDeviceIds.add(id);
      });
    };

    if (gridIds.length > 0) {
      gridIds.forEach((id, index) => {
        positions.set(id, {
          x: busPosition.x - DEVICE_WIDTH - DEVICE_CLEARANCE,
          y: busPosition.y + BUS_HEIGHT / 2 - DEVICE_HEIGHT / 2 + index * DEVICE_GAP,
        });
        terminalSides.set(id, 'right');
        attachedDeviceIds.add(id);
      });
    }
    placeRow(remainingIds, 'bottom');
  }

  const unattached = snapshot.components.filter(
    (component) => component.kind !== 'bus' && !attachedDeviceIds.has(component.id),
  );
  unattached.forEach((component, index) => {
    positions.set(component.id, {
      x: right + BUS_COLUMN_GAP,
      y: ORIGIN_Y + index * (DEVICE_HEIGHT + DEVICE_CLEARANCE),
    });
    terminalSides.set(component.id, 'left');
  });

  return { positions, terminalSides };
}

function opposite(side: PortSide): PortSide {
  if (side === 'left') {
    return 'right';
  }
  if (side === 'right') {
    return 'left';
  }
  if (side === 'top') {
    return 'bottom';
  }
  return 'top';
}

/**
 * Recompute automatic port sides and lanes for every edge.
 *
 * Runs whenever nodes change (every drag frame, every selection change), so
 * edges whose routing is unchanged keep their object identity and the input
 * array is returned as-is when nothing changed. React Flow then re-renders
 * only the edges that actually moved, and setEdges bails out entirely when
 * none did.
 */
export function orientFlowEdges(
  nodes: SystemFlowNode[],
  edges: SystemFlowEdge[],
): SystemFlowEdge[] {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  let changed = false;
  const oriented = edges.map((edge, index) => {
    const next = orientFlowEdge(edge, index, nodeById);
    changed ||= next !== edge;
    return next;
  });
  return changed ? oriented : edges;
}

function orientFlowEdge(
  edge: SystemFlowEdge,
  index: number,
  nodeById: Map<string, SystemFlowNode>,
): SystemFlowEdge {
  const source = nodeById.get(edge.source);
  const target = nodeById.get(edge.target);
  if (!source || !target) {
    return edge;
  }
  const sourceCenter = centerOf(source);
  const targetCenter = centerOf(target);
  const dx = targetCenter.x - sourceCenter.x;
  const dy = targetCenter.y - sourceCenter.y;
  const horizontal = Math.abs(dx) >= Math.abs(dy);
  const automaticSourceSide: PortSide = horizontal
    ? (dx >= 0 ? 'right' : 'left')
    : (dy >= 0 ? 'bottom' : 'top');
  const sourceSide = edge.data?.sourceSideLocked && edge.data.sourceSide
    ? edge.data.sourceSide
    : automaticSourceSide;
  const targetSide = edge.data?.targetSideLocked && edge.data.targetSide
    ? edge.data.targetSide
    : opposite(automaticSourceSide);
  const routeHorizontal = ['left', 'right'].includes(sourceSide) &&
    ['left', 'right'].includes(targetSide);
  const routeAxis = routeHorizontal ? 'horizontal' : 'vertical';
  const laneOffset = ((index % 5) - 2) * 7;
  const sourceHandle = `source-${sourceSide}`;
  const targetHandle = `target-${targetSide}`;
  const data = edge.data;
  if (
    data?.label !== undefined &&
    edge.sourceHandle === sourceHandle &&
    edge.targetHandle === targetHandle &&
    data.sourceSide === sourceSide &&
    data.targetSide === targetSide &&
    data.routeAxis === routeAxis &&
    data.laneOffset === laneOffset
  ) {
    return edge;
  }
  return {
    ...edge,
    sourceHandle,
    targetHandle,
    data: {
      label: data?.label ?? '',
      ...data,
      sourceSide,
      targetSide,
      routeAxis,
      laneOffset,
    },
  };
}

/**
 * Everything the topology canvas draws. Snapshots that differ only in
 * results (signals, eigenvalues, ...) or parameter values share a signature,
 * so the canvas can keep its node positions and selection for them.
 */
export function topologySignature(snapshot: SystemSnapshot): string {
  return JSON.stringify([
    snapshot.system.id,
    snapshot.components.map((component) => [
      component.id,
      component.name,
      component.kind,
      component.icon,
    ]),
    snapshot.connections.map((connection) => [
      connection.id,
      connection.name,
      connection.source,
      connection.target,
    ]),
    snapshot.layout ?? null,
  ]);
}

export function snapshotToFlow(
  snapshot: SystemSnapshot,
  options: { useSavedLayout?: boolean } = {},
): {
  nodes: SystemFlowNode[];
  edges: SystemFlowEdge[];
} {
  const automaticLayout = layoutSnapshot(snapshot);
  const savedLayout = options.useSavedLayout === false ? undefined : snapshot.layout;
  const nodes: SystemFlowNode[] = snapshot.components.map((component) => ({
    id: component.id,
    type: 'systemNode',
    position: savedLayout?.nodes[component.id] ??
      automaticLayout.positions.get(component.id) ?? { x: ORIGIN_X, y: ORIGIN_Y },
    data: {
      component,
      terminalSide: savedLayout?.nodes[component.id]?.terminalSide ??
        automaticLayout.terminalSides.get(component.id),
    },
  }));
  const edges: SystemFlowEdge[] = snapshot.connections.map((connection) => {
    const savedEdge = savedLayout?.edges[connection.id];
    return {
      id: connection.id,
      type: 'routed',
      source: connection.source,
      target: connection.target,
      data: {
        label: connection.name,
        waypoint: savedEdge?.waypoint,
        sourceSide: savedEdge?.sourceSide,
        targetSide: savedEdge?.targetSide,
        sourceSideLocked: Boolean(savedEdge?.sourceSide),
        targetSideLocked: Boolean(savedEdge?.targetSide),
      },
      selectable: true,
    };
  });

  return { nodes, edges: orientFlowEdges(nodes, edges) };
}

export const kindLabels: Record<ComponentKind, string> = {
  bus: 'Bus',
  grid: 'Grid',
  gfm: 'GFM',
  gfl: 'GFL',
  generator: 'Generator',
  load: 'Load',
  motor: 'Motor',
  capacitor: 'Capacitor',
  controller: 'Controller',
  generic: 'Component',
};
