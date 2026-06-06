import assert from 'node:assert/strict';
import path from 'node:path';
import test from 'node:test';

import {
  buildApprovePlanEvents,
  buildRegeneratePlanEvents,
  buildResumeTaskEvents,
  buildTaskStartEvents,
  evaluateTokenBudget,
  normalizeStartTaskMessage,
  normalizeTaskThreadMessage,
  requireApprovedPlanText,
  resolveInterruptedResumeWorkspacePath,
  resolveTaskResumeWorkspacePath,
  resolveRequestedWorkspacePath
} from './web-session-task-commands.js';

function timestampSequence(start = 1000) {
  let value = start;
  return () => value++;
}

test('normalizeStartTaskMessage trims task text fields and preserves string teamId', () => {
  assert.deepEqual(normalizeStartTaskMessage({
    description: '  train a model  ',
    approvedPlanText: '  # plan  ',
    approvedPlanName: '  plan A  ',
    approvedPlanId: '  plan-1  ',
    taskId: '  task-1  ',
    teamId: ' team-1 ',
    tokenBudget: '250'
  }), {
    description: 'train a model',
    approvedPlanText: '# plan',
    approvedPlanName: 'plan A',
    approvedPlanId: 'plan-1',
    taskId: 'task-1',
    teamId: ' team-1 ',
    tokenBudget: 250
  });

  assert.deepEqual(normalizeStartTaskMessage({
    description: null,
    approvedPlanText: 1,
    taskId: '   ',
    teamId: 123
  }), {
    description: '',
    approvedPlanText: '',
    approvedPlanName: '',
    approvedPlanId: '',
    taskId: undefined,
    teamId: undefined,
    tokenBudget: undefined
  });
});

test('normalizeTaskThreadMessage trims explicit task/thread ids and falls back to active task id', () => {
  assert.deepEqual(normalizeTaskThreadMessage({
    taskId: ' task-2 ',
    threadId: ' thread-2 ',
    tokenBudget: '30'
  }, 'active-task'), {
    taskId: 'task-2',
    threadId: 'thread-2',
    tokenBudget: 30,
    improvementDecision: undefined
  });

  assert.deepEqual(normalizeTaskThreadMessage({
    taskId: '   ',
    threadId: '   '
  }, 'active-task'), {
    taskId: 'active-task',
    threadId: undefined,
    tokenBudget: undefined,
    improvementDecision: undefined
  });

  assert.equal(
    normalizeTaskThreadMessage({
      improvementDecision: 'continue_improvement'
    }, 'active-task').improvementDecision,
    'continue_improvement'
  );
});

test('evaluateTokenBudget interrupts when run consumption reaches the remaining budget', () => {
  assert.deepEqual(evaluateTokenBudget({
    total: { totalTokens: 930 },
    last: { totalTokens: 30 }
  }, {
    tokenBudget: 100
  }), {
    baselineTotalTokens: 900,
    consumedTokens: 30,
    shouldInterrupt: false,
    totalTokens: 930
  });

  assert.deepEqual(evaluateTokenBudget({
    total: { totalTokens: 1000 },
    last: { totalTokens: 20 }
  }, {
    tokenBudget: 100,
    baselineTotalTokens: 900
  }), {
    baselineTotalTokens: 900,
    consumedTokens: 100,
    shouldInterrupt: true,
    totalTokens: 1000
  });

  assert.equal(evaluateTokenBudget({
    total: { totalTokens: 1200 },
    last: { totalTokens: 200 }
  }, {
    tokenBudget: 100,
    baselineTotalTokens: 900,
    quotaInterrupted: true
  }).shouldInterrupt, false);
});

test('requireApprovedPlanText trims plan text and rejects empty confirmations', () => {
  assert.equal(requireApprovedPlanText({ planText: '  run this plan  ' }), 'run this plan');
  assert.throws(
    () => requireApprovedPlanText({ planText: '   ' }),
    /确认计划不能为空。/
  );
  assert.throws(
    () => requireApprovedPlanText({}),
    /确认计划不能为空。/
  );
});

test('buildTaskStartEvents preserves task start event order and payload fields', () => {
  assert.deepEqual(buildTaskStartEvents({
    taskId: 'task-1',
    teamId: 'team-1',
    dataPath: 'D:\\data\\train.csv',
    dataPathType: 'file',
    description: 'train'
  }, {
    now: timestampSequence(6000)
  }), [
    {
      type: 'task_session_started',
      taskId: 'task-1',
      teamId: 'team-1',
      timestamp: 6000
    },
    {
      type: 'task_input_submitted',
      taskId: 'task-1',
      teamId: 'team-1',
      dataPath: 'D:\\data\\train.csv',
      dataPathType: 'file',
      description: 'train',
      timestamp: 6001
    },
    {
      type: 'workspace_creation_started',
      timestamp: 6002
    }
  ]);
});

test('buildRegeneratePlanEvents preserves regeneration lifecycle events', () => {
  assert.deepEqual(buildRegeneratePlanEvents({
    now: timestampSequence(7000)
  }), [
    {
      type: 'plan_generation_started',
      timestamp: 7000
    },
    {
      type: 'activity',
      label: 'Regenerating plan',
      status: 'pending'
    }
  ]);
});

test('buildApprovePlanEvents preserves approval lifecycle events', () => {
  assert.deepEqual(buildApprovePlanEvents({
    now: timestampSequence(8000)
  }), [
    {
      type: 'plan_approved',
      timestamp: 8000
    },
    {
      type: 'modeling_started',
      timestamp: 8001
    },
    {
      type: 'activity',
      label: 'Running approved plan',
      status: 'pending'
    }
  ]);
});

test('buildResumeTaskEvents preserves resume lifecycle events', () => {
  assert.deepEqual(buildResumeTaskEvents({
    workspacePath: 'D:\\workspace\\ai4ml-1'
  }, {
    now: timestampSequence(9000)
  }), [
    {
      type: 'task_resume_requested',
      workspacePath: 'D:\\workspace\\ai4ml-1',
      timestamp: 9000
    },
    {
      type: 'modeling_started',
      timestamp: 9001
    },
    {
      type: 'activity',
      label: 'Resuming task',
      status: 'pending'
    }
  ]);
});

test('resolveRequestedWorkspacePath returns an absolute path only for non-empty strings', () => {
  assert.equal(
    resolveRequestedWorkspacePath({ workspacePath: 'workspaces\\ai4ml-1' }),
    path.resolve('workspaces\\ai4ml-1')
  );
  assert.equal(resolveRequestedWorkspacePath({ workspacePath: '   ' }), undefined);
  assert.equal(resolveRequestedWorkspacePath({ workspacePath: 123 }), undefined);
});

test('resolveInterruptedResumeWorkspacePath resolves valid interrupted workspaces', () => {
  const workspacePath = path.resolve('D:\\workspace\\ai4ml-1');

  assert.equal(resolveInterruptedResumeWorkspacePath({
    workspace: { path: workspacePath },
    progress: { status: 'interrupted' }
  }, undefined), workspacePath);

  assert.equal(resolveInterruptedResumeWorkspacePath({
    workspace: { path: workspacePath },
    progress: { status: 'interrupted' }
  }, workspacePath), workspacePath);
});

test('resolveInterruptedResumeWorkspacePath rejects missing, stale, and non-interrupted workspaces', () => {
  assert.throws(
    () => resolveInterruptedResumeWorkspacePath({}, undefined),
    /没有可继续的任务工作区。/
  );

  assert.throws(
    () => resolveInterruptedResumeWorkspacePath({
      workspace: { path: path.resolve('D:\\workspace\\latest') },
      progress: { status: 'interrupted' }
    }, path.resolve('D:\\workspace\\requested')),
    /请求继续的工作区不是当前最新任务工作区。/
  );

  assert.throws(
    () => resolveInterruptedResumeWorkspacePath({
      workspace: { path: path.resolve('D:\\workspace\\latest') },
      progress: { status: 'running' }
    }, undefined),
    /当前任务状态不是可恢复状态，实际状态是 running。/
  );

  assert.throws(
    () => resolveInterruptedResumeWorkspacePath({
      workspace: { path: path.resolve('D:\\workspace\\latest') },
      progress: {}
    }, undefined),
    /当前任务状态不是可恢复状态，实际状态是 unknown。/
  );
});

test('resolveTaskResumeWorkspacePath accepts improvement review only with an improvement decision', () => {
  const workspacePath = path.resolve('D:\\workspace\\ai4ml-2');
  const artifacts = {
    workspace: { path: workspacePath },
    progress: { status: 'waiting_improvement_review' }
  };

  assert.equal(resolveTaskResumeWorkspacePath(artifacts, undefined, {
    improvementDecision: 'stop_and_report'
  }), workspacePath);

  assert.throws(
    () => resolveTaskResumeWorkspacePath(artifacts, undefined),
    /当前任务状态不是可恢复状态，实际状态是 waiting_improvement_review。/
  );
});
