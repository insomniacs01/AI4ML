import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import path from 'node:path';

const stateDir = process.env.CODEX_WEB_CONSOLE_STATE_DIR
  || path.join(homedir(), '.codex-web-console');
const stateFile = path.join(stateDir, 'session-state.json');

export function getSessionStateDir() {
  return stateDir;
}

function workspaceKey(cwd) {
  return path.resolve(cwd || process.cwd());
}

async function readState() {
  try {
    const raw = await readFile(stateFile, 'utf8');
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object') {
      return {
        version: 1,
        workspaces: parsed.workspaces && typeof parsed.workspaces === 'object'
          ? parsed.workspaces
          : {}
      };
    }
  } catch {
    // Missing or corrupt state should not prevent Codex from starting.
  }

  return {
    version: 1,
    workspaces: {}
  };
}

async function writeState(state) {
  await mkdir(stateDir, { recursive: true });
  const temporaryFile = `${stateFile}.${process.pid}.tmp`;
  await writeFile(temporaryFile, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
  await rename(temporaryFile, stateFile);
}

export async function getSavedThread(cwd = process.cwd()) {
  const state = await readState();
  const workspace = state.workspaces[workspaceKey(cwd)];

  if (!workspace || typeof workspace.threadId !== 'string' || !workspace.threadId) {
    return null;
  }

  return workspace;
}

export async function getSavedTaskThread(cwd = process.cwd(), taskId) {
  if (typeof taskId !== 'string' || !taskId.trim()) {
    return null;
  }

  const state = await readState();
  const workspace = state.workspaces[workspaceKey(cwd)];
  const taskThreads = workspace?.taskThreads;
  const record = taskThreads && typeof taskThreads === 'object'
    ? taskThreads[taskId.trim()]
    : null;

  if (!record || typeof record.threadId !== 'string' || !record.threadId) {
    return null;
  }

  return record;
}

export async function saveThread(cwd = process.cwd(), threadId) {
  if (typeof threadId !== 'string' || !threadId) {
    return;
  }

  const state = await readState();
  const current = state.workspaces[workspaceKey(cwd)] || {};
  state.workspaces[workspaceKey(cwd)] = {
    ...current,
    threadId,
    updatedAt: new Date().toISOString()
  };
  await writeState(state);
}

export async function saveTaskThread(cwd = process.cwd(), taskId, threadId, webSessionId) {
  if (typeof taskId !== 'string' || !taskId.trim() || typeof threadId !== 'string' || !threadId) {
    return;
  }

  const state = await readState();
  const key = workspaceKey(cwd);
  const current = state.workspaces[key] || {};
  const taskThreads = current.taskThreads && typeof current.taskThreads === 'object'
    ? current.taskThreads
    : {};
  taskThreads[taskId.trim()] = {
    threadId,
    webSessionId: typeof webSessionId === 'string' && webSessionId ? webSessionId : taskThreads[taskId.trim()]?.webSessionId,
    updatedAt: new Date().toISOString()
  };
  state.workspaces[key] = {
    ...current,
    taskThreads,
    updatedAt: new Date().toISOString()
  };
  await writeState(state);
}

export async function getSavedWorkspace(cwd = process.cwd()) {
  const state = await readState();
  return state.workspaces[workspaceKey(cwd)] || null;
}

export async function saveWebSession(cwd = process.cwd(), webSessionId) {
  if (typeof webSessionId !== 'string' || !webSessionId) {
    return;
  }

  const state = await readState();
  const current = state.workspaces[workspaceKey(cwd)] || {};
  state.workspaces[workspaceKey(cwd)] = {
    ...current,
    webSessionId,
    updatedAt: new Date().toISOString()
  };
  await writeState(state);
}

export async function clearSavedThread(cwd = process.cwd()) {
  const state = await readState();
  const key = workspaceKey(cwd);
  const current = state.workspaces[key];

  if (current && typeof current === 'object') {
    delete current.threadId;
    current.updatedAt = new Date().toISOString();
    state.workspaces[key] = current;
  } else {
    delete state.workspaces[key];
  }

  await writeState(state);
}
