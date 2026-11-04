import type {
  ComponentDescriptor,
  ComponentKind,
  ConnectionDescriptor,
  Selection,
  SystemSnapshot,
} from './types';

/**
 * What the topology canvas draws, derived from a system descriptor.
 *
 * The descriptor is the electrical model: a ground is one ordinary node that
 * every load is wired to. On a one-line diagram that node is not drawn;
 * instead each shunt element ends in its own ground symbol. This module makes
 * that translation:
 *
 * - shunt devices (loads, capacitors) get a ground symbol of their own;
 * - a branch from a bus to the ground node is a load, drawn as a load symbol
 *   with its own ground (selecting it selects the branch);
 * - the ground node itself, and the devices that only hold it at zero volts,
 *   are not drawn. They stay listed in the system tree.
 */

export type NodeRole = 'bus' | 'source' | 'shunt' | 'ground';

export interface DisplayNode {
  component: ComponentDescriptor;
  role: NodeRole;
  /** What the inspector shows when this node is selected. */
  selectAs: Selection;
  /** For a ground symbol: the element it belongs to. */
  ownerId?: string;
}

export interface DisplayConnection {
  id: string;
  name: string;
  source: string;
  target: string;
  /** What the inspector shows when this wire is selected; null when not selectable. */
  selectAs: Selection;
  /** Wire from an element to its ground symbol. */
  ground?: boolean;
}

export interface DisplayGraph {
  nodes: DisplayNode[];
  connections: DisplayConnection[];
}

/** Device kinds that are connected between a bus and ground. */
const SHUNT_KINDS = new Set<ComponentKind>(['load', 'capacitor']);

const GROUND_NAME = /(^|[-_\s])(ground|gnd|earth)([-_\s]|$)/i;

export function isGroundBus(component: ComponentDescriptor): boolean {
  return component.kind === 'bus' && (GROUND_NAME.test(component.name) || GROUND_NAME.test(component.id));
}

export function groundId(ownerId: string): string {
  return `${ownerId}::ground`;
}

export function buildDisplayGraph(
  snapshot: Pick<SystemSnapshot, 'components' | 'connections'>,
): DisplayGraph {
  const componentById = new Map(snapshot.components.map((component) => [component.id, component]));
  const groundBusIds = new Set(snapshot.components.filter(isGroundBus).map((bus) => bus.id));
  const firstGroundBus = [...groundBusIds][0];

  // Devices wired only to a ground node are the ground reference itself.
  const neighbors = new Map<string, Set<string>>();
  for (const connection of snapshot.connections) {
    neighbors.set(connection.source, (neighbors.get(connection.source) ?? new Set()).add(connection.target));
    neighbors.set(connection.target, (neighbors.get(connection.target) ?? new Set()).add(connection.source));
  }
  const hidden = new Set(groundBusIds);
  for (const component of snapshot.components) {
    const linked = [...(neighbors.get(component.id) ?? [])];
    if (component.kind !== 'bus' && linked.length > 0 && linked.every((id) => groundBusIds.has(id))) {
      hidden.add(component.id);
    }
  }

  const roleOf = (component: ComponentDescriptor): NodeRole => {
    if (component.kind === 'bus') {
      return 'bus';
    }
    return SHUNT_KINDS.has(component.kind) ? 'shunt' : 'source';
  };

  const nodes: DisplayNode[] = [];
  const connections: DisplayConnection[] = [];
  const grounded = new Set<string>();

  for (const component of snapshot.components) {
    if (!hidden.has(component.id)) {
      nodes.push({ component, role: roleOf(component), selectAs: { kind: 'component', id: component.id } });
    }
  }

  const loadBranch = (connection: ConnectionDescriptor, busId: string) => {
    const loadId = `${connection.id}::load`;
    nodes.push({
      component: {
        id: loadId,
        name: connection.name,
        className: 'codesim.LoadBranch',
        kind: 'load',
        icon: 'load',
        parameters: connection.parameters ?? [],
      },
      role: 'shunt',
      selectAs: { kind: 'connection', id: connection.id },
    });
    connections.push({
      id: connection.id,
      name: '',
      source: busId,
      target: loadId,
      selectAs: { kind: 'connection', id: connection.id },
    });
    grounded.add(loadId);
  };

  for (const connection of snapshot.connections) {
    const sourceHidden = hidden.has(connection.source);
    const targetHidden = hidden.has(connection.target);
    if (sourceHidden && targetHidden) {
      continue;
    }
    if (sourceHidden || targetHidden) {
      const visibleId = sourceHidden ? connection.target : connection.source;
      if (componentById.get(visibleId)?.kind === 'bus') {
        loadBranch(connection, visibleId);
      } else {
        grounded.add(visibleId);
      }
      continue;
    }
    connections.push({
      id: connection.id,
      name: connection.name,
      source: connection.source,
      target: connection.target,
      selectAs: { kind: 'connection', id: connection.id },
    });
  }

  for (const node of [...nodes]) {
    if (node.role === 'shunt' || grounded.has(node.component.id)) {
      const ownerId = node.component.id;
      const id = groundId(ownerId);
      nodes.push({
        component: {
          id,
          name: 'Ground',
          className: 'codesim.Ground',
          kind: 'ground',
          icon: 'ground',
          parameters: [],
        },
        role: 'ground',
        selectAs: firstGroundBus ? { kind: 'component', id: firstGroundBus } : null,
        ownerId,
      });
      connections.push({ id, name: '', source: ownerId, target: id, selectAs: null, ground: true });
    }
  }

  return { nodes, connections };
}
