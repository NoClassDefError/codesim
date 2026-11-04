import type { Edge, Node } from '@xyflow/react';
import {
  buildDisplayGraph,
  type DisplayGraph,
  type NodeRole,
} from './displayGraph';
import {
  computeElkLayout,
  type ElkLayoutResult,
  type LabelPlacement,
  type LayoutConnection,
  type LayoutNode,
} from './elkLayout';
import type {
  ComponentDescriptor,
  ComponentKind,
  PortSide,
  Selection,
  SystemSnapshot,
} from './types';

export interface SystemNodeData extends Record<string, unknown> {
  component: ComponentDescriptor;
  role: NodeRole;
  /** What the inspector shows when this node is selected. */
  selectAs: Selection;
  /** For a ground symbol: the element it belongs to. */
  ownerId?: string;
  /** The element ends in its own ground symbol, drawn below it. */
  hasGround?: boolean;
  terminalSide?: PortSide;
  /** Drawn size; wires end on its border, so it is the size of the symbol itself. */
  width: number;
  height: number;
}

export interface RoutedEdgeData extends Record<string, unknown> {
  label: string;
  waypoint?: { x: number; y: number };
  /** Orthogonal route from the automatic layout; dropped when an endpoint moves. */
  points?: Point[];
  routeAxis?: 'horizontal' | 'vertical';
  laneOffset?: number;
  sourceSide?: PortSide;
  targetSide?: PortSide;
  sourceSideLocked?: boolean;
  targetSideLocked?: boolean;
  /** Wire from an element to its ground symbol. */
  ground?: boolean;
}

export type SystemFlowNode = Node<SystemNodeData, 'systemNode'>;
export type SystemFlowEdge = Edge<RoutedEdgeData, 'routed'>;

interface Point {
  x: number;
  y: number;
}

/** Spacing of the built-in fallback layout. */
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

/** Drawn sizes. Wires end on the symbol, so these are the symbol sizes. */
export const ICON_SIZE = 44;
export const BUS_BAR_WIDTH = 8;
const BUS_MIN_HEIGHT = 44;
const BUS_PORT_PITCH = 22;
export const GROUND_WIDTH = 26;
export const GROUND_HEIGHT = 20;
/** Length of the wire from an element down to its ground symbol. */
const GROUND_DROP = 22;

function renderSize(role: NodeRole): { width: number; height: number } {
  if (role === 'bus') {
    return { width: BUS_BAR_WIDTH, height: BUS_MIN_HEIGHT };
  }
  if (role === 'ground') {
    return { width: GROUND_WIDTH, height: GROUND_HEIGHT };
  }
  return { width: ICON_SIZE, height: ICON_SIZE };
}

function centerOf(node: SystemFlowNode): Point {
  return {
    x: node.position.x + node.data.width / 2,
    y: node.position.y + node.data.height / 2,
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

function layoutSnapshot(snapshot: {
  components: ComponentDescriptor[];
  connections: Array<{ id: string; source: string; target: string }>;
}): {
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
  // Routed edges carry the port sides chosen by the layout.
  if (!source || !target || (edge.data?.points?.length ?? 0) >= 2) {
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


/** Port sides implied by the first and last segment of an orthogonal route. */
function sidesFromPoints(points: Point[]): { sourceSide: PortSide; targetSide: PortSide } {
  const direction = (from: Point, to: Point): PortSide => {
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    if (Math.abs(dx) >= Math.abs(dy)) {
      return dx >= 0 ? 'right' : 'left';
    }
    return dy >= 0 ? 'bottom' : 'top';
  };
  const last = points.length - 1;
  return {
    sourceSide: direction(points[0], points[1]),
    targetSide: direction(points[last], points[last - 1]),
  };
}

function isGroundEdge(edge: SystemFlowEdge): boolean {
  return Boolean(edge.data?.ground);
}

/**
 * Port sides of a wire: the user's choice where fixed, otherwise the
 * one-line convention. Power flows left to right; a grid feeds its bus from
 * the left; shunt elements hang below the bus with their ground beneath.
 */
function resolveSides(
  edge: SystemFlowEdge,
  nodeById: Map<string, SystemFlowNode>,
): { sourceSide: PortSide; targetSide: PortSide; reversed: boolean } {
  const target = nodeById.get(edge.target);
  const reversed = target?.data.component.kind === 'grid';
  const defaultTarget: PortSide = target?.data.role === 'shunt' || target?.data.role === 'ground'
    ? 'top'
    : reversed ? 'right' : 'left';
  return {
    sourceSide: (edge.data?.sourceSideLocked && edge.data.sourceSide) || (reversed ? 'left' : 'right'),
    targetSide: (edge.data?.targetSideLocked && edge.data.targetSide) || defaultTarget,
    reversed,
  };
}

/** Busbars grow with the number of wires on their busiest side. */
function withBusHeights(nodes: SystemFlowNode[], edges: SystemFlowEdge[]): SystemFlowNode[] {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const counts = new Map<string, Record<PortSide, number>>();
  const count = (nodeId: string, side: PortSide) => {
    const entry = counts.get(nodeId) ?? { left: 0, right: 0, top: 0, bottom: 0 };
    entry[side] += 1;
    counts.set(nodeId, entry);
  };
  for (const edge of edges) {
    if (isGroundEdge(edge)) {
      continue;
    }
    const sides = resolveSides(edge, nodeById);
    count(edge.source, sides.sourceSide);
    count(edge.target, sides.targetSide);
  }
  return nodes.map((node) => {
    if (node.data.role !== 'bus') {
      return node;
    }
    const entry = counts.get(node.id);
    const wires = Math.max(entry?.left ?? 0, entry?.right ?? 0, 1);
    const height = Math.max(BUS_MIN_HEIGHT, (wires + 1) * BUS_PORT_PITCH);
    return height === node.data.height ? node : { ...node, data: { ...node.data, height } };
  });
}

function labelFor(node: SystemFlowNode): LayoutNode['label'] {
  if (node.data.role === 'ground') {
    return undefined;
  }
  const placement: LabelPlacement = node.data.role === 'bus'
    ? 'above'
    : node.data.role === 'shunt' || node.data.hasGround ? 'right' : 'below';
  const name = node.data.component.name;
  const kind = kindLabels[node.data.component.kind] ?? '';
  return {
    width: Math.ceil(Math.min(150, Math.max(name.length * 7, kind.length * 6.5)) + 8),
    height: 30,
    placement,
  };
}

/** ELK input: grounds are not laid out; their owners reserve the space below them instead. */
function elkInput(nodes: SystemFlowNode[], edges: SystemFlowEdge[]): {
  nodes: LayoutNode[];
  connections: LayoutConnection[];
} {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  return {
    nodes: nodes
      .filter((node) => node.data.role !== 'ground')
      .map((node) => ({
        id: node.id,
        width: node.data.width,
        height: node.data.height + (node.data.hasGround ? GROUND_DROP + GROUND_HEIGHT : 0),
        label: labelFor(node),
        position: node.position,
      })),
    connections: edges
      .filter((edge) => !isGroundEdge(edge))
      .map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, ...resolveSides(edge, nodeById) })),
  };
}

/** Put every ground symbol straight below its element, unless its position is kept. */
function placeGrounds(
  nodes: SystemFlowNode[],
  edges: SystemFlowEdge[],
  keep: Set<string> = new Set(),
): { nodes: SystemFlowNode[]; edges: SystemFlowEdge[] } {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const placed = new Map<string, Point[]>();
  const nextNodes = nodes.map((node) => {
    const owner = node.data.ownerId ? nodeById.get(node.data.ownerId) : undefined;
    if (node.data.role !== 'ground' || !owner || keep.has(node.id)) {
      return node;
    }
    const x = owner.position.x + owner.data.width / 2;
    const top = owner.position.y + owner.data.height;
    const position = { x: x - GROUND_WIDTH / 2, y: top + GROUND_DROP };
    placed.set(node.id, [{ x, y: top }, { x, y: position.y }]);
    return { ...node, position };
  });
  const nextEdges = edges.map((edge) => {
    const points = placed.get(edge.target);
    if (!isGroundEdge(edge) || !points) {
      return edge;
    }
    return {
      ...edge,
      sourceHandle: 'source-bottom',
      targetHandle: 'target-top',
      data: {
        label: '',
        ...edge.data,
        points,
        sourceSide: 'bottom' as PortSide,
        targetSide: 'top' as PortSide,
      },
    };
  });
  return { nodes: nextNodes, edges: nextEdges };
}

/** Write an ELK result onto existing nodes and edges, then hang the grounds below their owners. */
function applyElkLayout(
  nodes: SystemFlowNode[],
  edges: SystemFlowEdge[],
  layout: ElkLayoutResult,
): { nodes: SystemFlowNode[]; edges: SystemFlowEdge[] } {
  const edgeById = new Map(edges.map((edge) => [edge.id, edge]));
  const terminalSides = new Map<string, PortSide>();
  layout.routes.forEach((route, edgeId) => {
    const edge = edgeById.get(edgeId);
    if (edge) {
      terminalSides.set(edge.source, route.sourceSide);
      terminalSides.set(edge.target, route.targetSide);
    }
  });
  const positioned = nodes.map((node) => ({
    ...node,
    position: layout.positions.get(node.id) ?? node.position,
    data: {
      ...node.data,
      terminalSide: node.data.role === 'bus'
        ? node.data.terminalSide
        : terminalSides.get(node.id) ?? node.data.terminalSide,
    },
  }));
  const routed = edges.map((edge) => {
    const route = layout.routes.get(edge.id);
    if (!route) {
      return edge;
    }
    return {
      ...edge,
      sourceHandle: `source-${route.sourceSide}`,
      targetHandle: `target-${route.targetSide}`,
      data: {
        label: edge.data?.label ?? '',
        ...edge.data,
        points: route.points,
        waypoint: undefined,
        sourceSide: route.sourceSide,
        targetSide: route.targetSide,
        routeAxis: undefined,
        laneOffset: undefined,
      },
    };
  });
  return placeGrounds(positioned, routed);
}

/** Whether a saved layout places everything this version draws. */
function savedLayoutCovers(graph: DisplayGraph, snapshot: SystemSnapshot): boolean {
  const saved = snapshot.layout?.nodes;
  return Boolean(saved) && graph.nodes.every((node) => saved?.[node.component.id] !== undefined);
}

export function snapshotToFlow(
  snapshot: SystemSnapshot,
  options: { useSavedLayout?: boolean } = {},
): {
  nodes: SystemFlowNode[];
  edges: SystemFlowEdge[];
} {
  const graph = buildDisplayGraph(snapshot);
  const automaticLayout = layoutSnapshot({
    components: graph.nodes.filter((node) => node.role !== 'ground').map((node) => node.component),
    connections: graph.connections.filter((connection) => !connection.ground),
  });
  const savedLayout = options.useSavedLayout === false ? undefined : snapshot.layout;
  const owners = new Set(graph.nodes.map((node) => node.ownerId).filter(Boolean));
  const nodes: SystemFlowNode[] = graph.nodes.map((node) => {
    const id = node.component.id;
    return {
      id,
      type: 'systemNode',
      position: savedLayout?.nodes[id] ??
        automaticLayout.positions.get(id) ?? { x: ORIGIN_X, y: ORIGIN_Y },
      selectable: node.selectAs !== null,
      data: {
        component: node.component,
        role: node.role,
        selectAs: node.selectAs,
        ownerId: node.ownerId,
        hasGround: owners.has(id),
        terminalSide: savedLayout?.nodes[id]?.terminalSide ?? automaticLayout.terminalSides.get(id),
        ...renderSize(node.role),
      },
    };
  });
  const edges: SystemFlowEdge[] = graph.connections.map((connection) => {
    const savedEdge = savedLayout?.edges[connection.id];
    const points = savedEdge?.points && savedEdge.points.length >= 2 ? savedEdge.points : undefined;
    const routeSides = points ? sidesFromPoints(points) : undefined;
    const sourceSide = savedEdge?.sourceSide ?? routeSides?.sourceSide;
    const targetSide = savedEdge?.targetSide ?? routeSides?.targetSide;
    return {
      id: connection.id,
      type: 'routed',
      source: connection.source,
      target: connection.target,
      ...(points ? { sourceHandle: `source-${sourceSide}`, targetHandle: `target-${targetSide}` } : {}),
      selectable: connection.selectAs !== null,
      focusable: connection.selectAs !== null,
      data: {
        label: connection.name,
        ground: connection.ground,
        waypoint: savedEdge?.waypoint,
        points,
        sourceSide,
        targetSide,
        sourceSideLocked: Boolean(savedEdge?.sourceSide),
        targetSideLocked: Boolean(savedEdge?.targetSide),
      },
    };
  });

  const sized = withBusHeights(nodes, edges);
  const keep = new Set(
    savedLayout ? sized.filter((node) => savedLayout.nodes[node.id]).map((node) => node.id) : [],
  );
  const grounded = placeGrounds(sized, edges, keep);
  return { nodes: grounded.nodes, edges: orientFlowEdges(grounded.nodes, grounded.edges) };
}

/**
 * Lay out a snapshot. A saved layout that places every drawn element is used
 * as it is; otherwise ELK places the elements and routes the wires. If ELK
 * fails, the built-in layered layout is used so the canvas never stays empty.
 */
export async function layoutFlow(
  snapshot: SystemSnapshot,
  options: { useSavedLayout?: boolean } = {},
): Promise<{ nodes: SystemFlowNode[]; edges: SystemFlowEdge[] }> {
  if (options.useSavedLayout !== false && savedLayoutCovers(buildDisplayGraph(snapshot), snapshot)) {
    return snapshotToFlow(snapshot);
  }
  const fallback = snapshotToFlow(snapshot, { useSavedLayout: false });
  try {
    const layout = await computeElkLayout({
      ...elkInput(fallback.nodes, fallback.edges),
      origin: { x: ORIGIN_X, y: ORIGIN_Y },
    });
    return applyElkLayout(fallback.nodes, fallback.edges, layout);
  } catch (error) {
    console.warn('CodeSim: automatic layout failed, using the basic layout.', error);
    return fallback;
  }
}

/**
 * Interactive re-layout after the user moved nodes or fixed a port side.
 * ELK keeps the current layer and order of the nodes, user-fixed port sides
 * are respected, and the anchor node stays where it is.
 */
export async function relayoutFlow(
  nodes: SystemFlowNode[],
  edges: SystemFlowEdge[],
  anchorId?: string,
): Promise<{ nodes: SystemFlowNode[]; edges: SystemFlowEdge[] }> {
  const sized = withBusHeights(nodes, edges);
  const anchor = sized.find((node) => node.id === anchorId);
  const layout = await computeElkLayout({
    ...elkInput(sized, edges),
    interactive: true,
    // A ground is not laid out by ELK; keep its owner in place instead.
    anchorId: anchor?.data.ownerId ?? anchorId,
  });
  return applyElkLayout(sized, edges, layout);
}

/** Forget the routes of edges attached to moving nodes; they fall back to automatic routing. */
export function detachRoutes(edges: SystemFlowEdge[], nodeIds: Set<string>): SystemFlowEdge[] {
  let changed = false;
  const next = edges.map((edge) => {
    if (!edge.data?.points || !(nodeIds.has(edge.source) || nodeIds.has(edge.target))) {
      return edge;
    }
    changed = true;
    return { ...edge, data: { ...edge.data, points: undefined } };
  });
  return changed ? next : edges;
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
  ground: 'Ground',
  generic: 'Component',
};
