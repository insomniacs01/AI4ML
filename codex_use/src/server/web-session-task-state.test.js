import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildProgressRecordsForTaskStateTransition,
  buildTaskStatePollTransition
} from './web-session-task-state.js';

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

test('buildTaskStatePollTransition emits completion before plan events when accepted artifacts exist', () => {
  const transition = buildTaskStatePollTransition({
    workspace: { path: 'D:\\workspace\\ai4ml-2' },
    plan: '# plan',
    progress: { status: 'waiting_plan_approval' },
    metrics: { acceptance: { passed: true } },
    report: { exists: true, path: 'D:\\workspace\\ai4ml-2\\output\\report.md' },
    predict: { exists: true, path: 'D:\\workspace\\ai4ml-2\\output\\predict.py' }
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

test('buildTaskStatePollTransition does not complete artifacts that failed acceptance', () => {
  const transition = buildTaskStatePollTransition({
    workspace: { path: 'D:\\workspace\\ai4ml-failed' },
    plan: '# plan',
    progress: { status: 'completed' },
    metrics: { acceptance: { passed: false } },
    report: { exists: true, path: 'D:\\workspace\\ai4ml-failed\\output\\report.md' },
    predict: { exists: true, path: 'D:\\workspace\\ai4ml-failed\\output\\predict.py' }
  }, new Set(['workspace_ready']), {
    now: timestampSequence(2500)
  });

  assert.equal(transition.taskCompleted, false);
  assert.equal(transition.stopPolling, false);
  assert.equal(transition.stopCompletedTaskTurn, false);
  assert.deepEqual(transition.events.map((event) => event.type), [
    'requirements_analysis_completed',
    'plan_generation_started'
  ]);
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

test('buildProgressRecordsForTaskStateTransition records plan approval readiness', () => {
  assert.deepEqual(buildProgressRecordsForTaskStateTransition({
    reportedStates: ['plan_written', 'plan_approval_ready'],
    taskCompleted: false
  }, {
    workspace: { path: 'D:\\workspace\\ai4ml-6' }
  }), [
    {
      workspacePath: 'D:\\workspace\\ai4ml-6',
      payload: {
        event: 'plan_generated',
        actor: 'codex_use',
        message: 'Codex 已写入执行计划，等待用户确认。',
        evidence: ['output/plan.md']
      }
    }
  ]);
});

test('buildProgressRecordsForTaskStateTransition records completion evidence from artifacts', () => {
  assert.deepEqual(buildProgressRecordsForTaskStateTransition({
    reportedStates: [],
    taskCompleted: true
  }, {
    workspace: { path: 'D:\\workspace\\ai4ml-7' },
    metrics: { leaderboard: [] },
    report: { exists: true },
    predict: { exists: true }
  }), [
    {
      workspacePath: 'D:\\workspace\\ai4ml-7',
      payload: {
        event: 'completed',
        actor: 'codex_use',
        message: 'Codex 建模任务已完成，最终产物已可读取。',
        evidence: [
          'output/progress.json',
          'output/metrics.json',
          'output/report.md',
          'output/predict.py'
        ]
      }
    }
  ]);
});
