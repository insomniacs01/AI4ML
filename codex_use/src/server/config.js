import process from 'node:process';
import path from 'node:path';

export const host = process.env.HOST || '127.0.0.1';
export const port = Number(process.env.PORT || 3000);
export const heartbeatIntervalMs = 10000;
export const defaultCodexModel = process.env.CODEX_MODEL || undefined;
export const ai4mlDataRoot = process.env.AI4ML_DATA_ROOT || path.resolve(process.cwd(), '..', 'data');
export const ai4mlWorkspaceRoot = process.env.AI4ML_WORKSPACE_ROOT || path.resolve(process.cwd(), 'workspaces');
