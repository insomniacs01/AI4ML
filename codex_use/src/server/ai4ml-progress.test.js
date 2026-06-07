import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import {
  appendAi4mlProgressEvent,
  ensureAi4mlProgressSnapshot,
  initializeAi4mlProgress,
  progressEventsPath,
  progressSnapshotPath,
  readAi4mlProgressEvents
} from './ai4ml-progress.js';

async function withWorkspace(run) {
  const workspace = await mkdtemp(path.join(os.tmpdir(), 'ai4ml-progress-'));
  try {
    await run(workspace);
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
}

async function readSnapshot(workspace) {
  return JSON.parse(await readFile(progressSnapshotPath(workspace), 'utf8'));
}

test('initializeAi4mlProgress writes an event log and progress snapshot', async () => {
  await withWorkspace(async (workspace) => {
    const snapshot = await initializeAi4mlProgress(workspace);

    assert.equal(snapshot.schema_version, 'ai4ml-progress-v1');
    assert.equal(snapshot.events_path, 'state/progress_events.jsonl');
    assert.equal(snapshot.status, 'running');
    assert.equal(snapshot.percent, 0);
    assert.equal(snapshot.percent_source, 'workspace_initialized');

    const events = await readAi4mlProgressEvents(workspace);
    assert.equal(events.length, 1);
    assert.equal(events[0].event, 'workspace_initialized');
    assert.match(await readFile(progressEventsPath(workspace), 'utf8'), /workspace_initialized/);
  });
});

test('ensureAi4mlProgressSnapshot repairs snapshot shape without inferring percent', async () => {
  await withWorkspace(async (workspace) => {
    await initializeAi4mlProgress(workspace);
    await appendAi4mlProgressEvent(workspace, {
      event: 'execution_started',
      actor: 'codex',
      status: 'running',
      step: 'data_preparation',
      message: 'running approved plan',
      evidence: ['output/plan.md']
    });
    await writeFile(
      progressSnapshotPath(workspace),
      JSON.stringify({
        status: 'running',
        current_step: 'data_preparation',
        summary: 'Codex wrote a direct snapshot without percent.',
        steps: [{ id: 'data_preparation', status: 'running' }]
      }),
      'utf8'
    );

    const repaired = await ensureAi4mlProgressSnapshot(workspace);

    assert.equal(repaired.schema_version, 'ai4ml-progress-v1');
    assert.equal(repaired.status, 'running');
    assert.equal(repaired.current_step, 'data_preparation');
    assert.equal(repaired.summary, 'Codex wrote a direct snapshot without percent.');
    assert.equal(Object.hasOwn(repaired, 'percent'), false);
    assert.equal(Object.hasOwn(repaired, 'percent_source'), false);
    assert.deepEqual(repaired.steps, [{ id: 'data_preparation', status: 'running' }]);
  });
});

test('appendAi4mlProgressEvent advances deterministic status events without percent', async () => {
  await withWorkspace(async (workspace) => {
    await initializeAi4mlProgress(workspace);
    const snapshot = await appendAi4mlProgressEvent(workspace, {
      event: 'plan_generated',
      actor: 'codex',
      message: 'plan ready'
    });

    assert.equal(snapshot.status, 'waiting_plan_approval');
    assert.equal(snapshot.current_step, 'waiting_plan_approval');
    assert.equal(Object.hasOwn(snapshot, 'percent'), false);
    assert.equal(Object.hasOwn(snapshot, 'percent_source'), false);
    assert.equal((await readAi4mlProgressEvents(workspace)).length, 2);
  });
});

test('interrupted progress preserves a newer explicit snapshot percent', async () => {
  await withWorkspace(async (workspace) => {
    await initializeAi4mlProgress(workspace);
    await writeFile(
      progressSnapshotPath(workspace),
      JSON.stringify({ status: 'running', current_step: 'modeling', percent: 64, percent_source: 'codex_runtime' }),
      'utf8'
    );

    const snapshot = await appendAi4mlProgressEvent(workspace, {
      event: 'interrupted',
      actor: 'codex_use',
      message: 'user paused'
    });

    assert.equal(snapshot.status, 'interrupted');
    assert.equal(snapshot.percent, 64);
    assert.equal(snapshot.percent_source, 'codex_runtime');
    assert.equal((await readSnapshot(workspace)).status, 'interrupted');
  });
});
