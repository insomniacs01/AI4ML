import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { WebSessionEventLog } from './web-session-event-log.js';

async function withTempLog(run) {
  const dir = await mkdtemp(path.join(tmpdir(), 'web-session-event-log-'));
  const logFile = path.join(dir, 'sessions', 'session.jsonl');

  try {
    await run(new WebSessionEventLog(logFile), logFile);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

test('loadPayloads reads JSONL payload objects and ignores non-object payloads', async () => {
  await withTempLog(async (log, logFile) => {
    await mkdir(path.dirname(logFile), { recursive: true });
    await writeFile(logFile, [
      JSON.stringify({ timestamp: 't1', payload: { type: 'one' } }),
      JSON.stringify({ timestamp: 't2', payload: null }),
      JSON.stringify({ timestamp: 't3', payload: 'text' }),
      JSON.stringify({ timestamp: 't4', payload: { type: 'two', value: 2 } }),
      ''
    ].join('\n'), 'utf8');

    assert.deepEqual(await log.loadPayloads(), [
      { type: 'one' },
      { type: 'two', value: 2 }
    ]);
  });
});

test('append writes queued JSONL records in order', async () => {
  await withTempLog(async (log, logFile) => {
    await log.append({ type: 'first' });
    await log.append({ type: 'second', value: 2 });

    assert.deepEqual(await log.loadPayloads(), [
      { type: 'first' },
      { type: 'second', value: 2 }
    ]);

    const raw = await readFile(logFile, 'utf8');
    assert.equal(raw.split(/\r?\n/).filter(Boolean).length, 2);
    assert.match(raw, /"timestamp":/);
  });
});

test('reset stays ordered with queued appends and leaves a readable empty log', async () => {
  await withTempLog(async (log) => {
    log.append({ type: 'before-reset' });
    log.reset();
    await log.append({ type: 'after-reset' });

    assert.deepEqual(await log.loadPayloads(), [
      { type: 'after-reset' }
    ]);
  });
});

test('reset creates an empty log when no prior file exists', async () => {
  await withTempLog(async (log) => {
    await log.reset();

    assert.deepEqual(await log.loadPayloads(), []);
  });
});
