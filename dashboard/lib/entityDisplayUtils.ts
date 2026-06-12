type EntityRecord = Record<string, unknown>;

function entityDisplayName(entity: EntityRecord): string {
  return String(entity.name || entity.canonicalName || '').trim();
}

/** Map entityId → human-readable name from blueprint and entity-graph records. */
export function buildEntityNameMap(
  blueprintEntities: EntityRecord[] = [],
  graphEntities: EntityRecord[] = []
): Record<string, string> {
  const map: Record<string, string> = {};

  for (const entity of blueprintEntities) {
    const id = String(entity.entityId || '').trim();
    const name = entityDisplayName(entity);
    if (id && name) map[id] = name;
  }

  for (const entity of graphEntities) {
    const id = String(entity.entityId || '').trim();
    if (!id || map[id]) continue;
    const name = entityDisplayName(entity);
    if (name) map[id] = name;
  }

  return map;
}

/** Resolve an entity ref/id to its display name, falling back to the raw id. */
export function resolveEntityLabel(
  entityRef: unknown,
  nameMap: Record<string, string>
): string {
  const id = String(entityRef || '').trim();
  if (!id) return '?';
  return nameMap[id] || id;
}
