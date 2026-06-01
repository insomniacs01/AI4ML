import assert from 'node:assert/strict';
import test from 'node:test';

import { buildTaskStatePollTransition } from './web-session-task-state.js';

function timestampSequence(start = 1000) {
  let value = start;
  return () => value++;
}

test('buildTaskStatePollTransition emits workspace readiness before requirements analysis', () => {
  const transition = buildTaskStatePollTransition({
    workspace: { path: 'D:\\workspace\\ai4ml-1' }
  }, new Set(), {
    now: timestampSequence()
  });

  assert.deepEqual(transition.reportedStates, ['workspace_ready']);
  assert.equal(transition.activeWorkspacePath, 'D:\\workspace\\ai4ml-1');
  assert.equal(transition.taskCompleted, false);
  assert.equal(transition.stopPolling, false);
  assert.deepEqual(transition.events, [
    {
      type: 'workspace_ready',
      workspacePath: 'D:\\workspace\\ai4ml-1',
      timestamp: 1000
    },
    {
      type: 'requirements_analysis_started',
      timestamp: 1001
    }
  ]);
});

test('buildTaskStatePollTransition emits completion before plan events when report exists', () => {
  const transition = buildTaskStatePollTransition({
    workspace: { path: 'D:\\workspace\\ai4ml-2' },
    plan: '# plan',
    progress: { status: 'waiting_plan_approval' },
    report: { exists: true, path: 'D:\\workspace\\ai4ml-2\\output\\report.md' }
  }, new Set(), {
    now: timestampSequence(2000)
  });

  assert.deepEqual(transition.reportedStates, ['workspace_ready']);
  assert.equal(transition.activeWorkspacePath, 'D:\\workspace\\ai4ml-2');
  assert.equal(transition.taskCompleted, true);
  assert.equal(transition.stopPolling, true);
  assert.equal(transition.stopCompletedTaskTurn, true);
  assert.deepEqual(transition.events.map((event) => event.type), [
    'workspace_ready',
    'requirements_analysis_started',
    'task_completed',
    'activity'
  ]);
  assert.deepEqual(transition.events[2], {
    type: 'task_completed',
    workspacePath: 'D:\\workspace\\ai4ml-2',
    reportPath: 'D:\\workspace\\ai4ml-2\\output\\report.md',
    timestamp: 2002
  });
  assert.deepEqual(transition.events[3], {
    type: 'activity',
    label: 'Ready',
    status: 'online'
  });
});

test('buildTaskStatePollTransition emits plan and approval events in one waiting poll', () => {
  const transition = buildTaskStatePollTransition({
    workspace: { path: 'D:\\workspace\\ai4ml-3' },
    plan: 'approved plan candidate',
    progress: { status: 'waiting_plan_approval' }
  }, new Set(['workspace_ready']), {
    now: timestampSequence(3000)
  });

  assert.deepEqual(transition.reportedStates, ['plan_written', 'plan_approval_ready']);
  assert.equal(transition.activeWorkspacePath, undefined);
  assert.equal(transition.taskCompleted, false);
  assert.equal(transition.stopPolling, true);
  assert.equal(transition.stopCompletedTaskTurn, false);
  assert.deepEqual(transition.events, [
    {
      type: 'requirements_analysis_completed',
      timestamp: 3000
    },
    {
      type: 'plan_generation_started',
      timestamp: 3001
    },
    {
      type: 'plan_generation_completed',
      workspacePath: 'D:\\workspace\\ai4ml-3',
      timestamp: 3002
    }
  ]);
});

test('buildTaskStatePollTransition does not repeat already reported states', () => {
  const transition = buildTaskStatePollTransition({
    workspace: { path: 'D:\\workspace\\ai4ml-4' },
    plan: 'plan',
    progress: { status: 'waiting_plan_approval' }
  }, new Set(['workspace_ready', 'plan_written', 'plan_approval_ready']), {
    now: timestampSequence(4000)
  });

  assert.deepEqual(transition.reportedStates, []);
  assert.deepEqual(transition.events, []);
  assert.equal(transition.stopPolling, false);
});

test('buildTaskStatePollTransition treats completed progress as completion without a report file', () => {
  const transition = buildTaskStatePollTransition({
    workspace: { path: 'D:\\workspace\\ai4ml-5' },
    progress: { status: 'completed' }
  }, new Set(['workspace_ready']), {
    now: timestampSequence(5000)
  });

  assert.deepEqual(transition.reportedStates, []);
  assert.equal(transition.taskCompleted, true);
  assert.equal(transition.stopPolling, true);
  assert.equal(transition.stopCompletedTaskTurn, true);
  assert.deepEqual(transition.events, [
    {
      type: 'task_completed',
      workspacePath: 'D:\\workspace\\ai4ml-5',
      reportPath: undefined,
      timestamp: 5000
    },
    {
      type: 'activity',
      label: 'Ready',
      status: 'online'
    }
  ]);
});
