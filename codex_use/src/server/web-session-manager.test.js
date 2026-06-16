import assert from 'node:assert/strict';
import test from 'node:test';

import { isTaskStatusStartupGraceActive } from './web-session-manager.js';

test('task status startup grace protects active progress during launch', () => {
  const nowMs = 100_000;

  assert.equal(isTaskStatusStartupGraceActive({
    taskStartedAtMs: nowMs - 1000,
    progressStatus: 'running',
    completed: false,
    nowMs
  }), true);

  assert.equal(isTaskStatusStartupGraceActive({
    taskStartedAtMs: nowMs - 31_000,
    progressStatus: 'running',
    completed: false,
    nowMs
  }), false);

  assert.equal(isTaskStatusStartupGraceActive({
    taskStartedAtMs: nowMs - 1000,
    progressStatus: 'waiting_plan_approval',
    completed: false,
    nowMs
  }), false);

  assert.equal(isTaskStatusStartupGraceActive({
    taskStartedAtMs: nowMs - 1000,
    progressStatus: 'running',
    completed: true,
    nowMs
  }), false);
});
