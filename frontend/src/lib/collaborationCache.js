const CACHE_TTL_MS = 60_000;
const snapshots = new Map();

function keyFor(taskId, teamId) {
  return `${teamId ?? ""}:${taskId ?? ""}`;
}

export function getCachedCollaborationSnapshot(taskId, teamId) {
  const cached = snapshots.get(keyFor(taskId, teamId));
  if (!cached) return null;
  if (Date.now() - cached.cachedAt > CACHE_TTL_MS) return null;
  return cached.payload;
}

export function setCachedCollaborationSnapshot(taskId, teamId, payload) {
  if (!taskId || !teamId || !payload) return;
  snapshots.set(keyFor(taskId, teamId), {
    cachedAt: Date.now(),
    payload,
  });
}

export function clearCollaborationSnapshot(taskId, teamId) {
  snapshots.delete(keyFor(taskId, teamId));
}
