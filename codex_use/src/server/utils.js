import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';

export function createSessionId() {
  return `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function getCodexCommand() {
  if (process.platform === 'win32') {
    const appData = process.env.APPDATA;

    if (appData) {
      const codexScript = path.join(appData, 'npm', 'node_modules', '@openai', 'codex', 'bin', 'codex.js');

      if (existsSync(codexScript)) {
        return {
          command: process.execPath,
          prefixArgs: [codexScript]
        };
      }
    }

    return {
      command: 'cmd.exe',
      prefixArgs: ['/d', '/s', '/c', 'codex.cmd']
    };
  }

  return {
    command: 'codex',
    prefixArgs: []
  };
}

export function sendJson(socket, payload) {
  if (socket.readyState === socket.OPEN) {
    socket.send(JSON.stringify(payload));
  }
}

export function killProcessTree(childProcess) {
  if (!childProcess || childProcess.killed) {
    return;
  }

  if (process.platform === 'win32' && childProcess.pid) {
    spawn('taskkill.exe', ['/pid', String(childProcess.pid), '/t', '/f'], {
      stdio: 'ignore',
      windowsHide: true
    });
    return;
  }

  childProcess.kill('SIGTERM');
}

export function extractText(value) {
  if (typeof value === 'string') {
    return value;
  }

  if (!value || typeof value !== 'object') {
    return '';
  }

  const textParts = [];
  const stack = [value];

  while (stack.length > 0) {
    const current = stack.pop();

    if (!current || typeof current !== 'object') {
      continue;
    }

    if (typeof current.text === 'string') {
      textParts.push(current.text);
    }

    for (const child of Object.values(current)) {
      if (child && typeof child === 'object') {
        stack.push(child);
      }
    }
  }

  return textParts.join('\n');
}
