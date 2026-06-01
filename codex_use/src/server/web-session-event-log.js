import { appendFile, mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

import { getSessionStateDir } from './session-store.js';
import { safeFileName } from './web-session-events.js';

export function createWebSessionEventLog(sessionId) {
  return new WebSessionEventLog(path.join(
    getSessionStateDir(),
    'sessions',
    `${safeFileName(sessionId)}.jsonl`
  ));
}

export class WebSessionEventLog {
  constructor(logFile) {
    this.logFile = logFile;
    this.writeQueue = Promise.resolve();
  }

  async loadPayloads() {
    const raw = await readFile(this.logFile, 'utf8');
    return raw
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line))
      .map((record) => record.payload)
      .filter((payload) => payload && typeof payload === 'object');
  }

  append(payload) {
    const record = JSON.stringify({
      timestamp: new Date().toISOString(),
      payload
    });
    this.writeQueue = this.writeQueue
      .then(async () => {
        await mkdir(path.dirname(this.logFile), { recursive: true });
        await appendFile(this.logFile, `${record}\n`, 'utf8');
      })
      .catch(() => {});
    return this.writeQueue;
  }

  reset() {
    this.writeQueue = this.writeQueue
      .then(async () => {
        await mkdir(path.dirname(this.logFile), { recursive: true });
        const temporaryFile = `${this.logFile}.${process.pid}.tmp`;
        await writeFile(temporaryFile, '', 'utf8');
        await rename(temporaryFile, this.logFile);
      })
      .catch(async () => {
        try {
          await unlink(this.logFile);
        } catch {
          // A missing event log is equivalent to an empty event log.
        }
      });
    return this.writeQueue;
  }
}
