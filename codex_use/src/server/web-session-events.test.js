import assert from 'node:assert/strict';
import test from 'node:test';

import {
  compactReplayEvents,
  hasUnclosedTurn,
  interruptionReasonForPayload,
  isInternalAi4mlUserMessage,
  safeFileName,
  shouldPersistEvent
} from './web-session-events.js';

test('shouldPersistEvent filters transient websocket and internal AI4ML events', () => {
  for (const type of [
    'heartbeat',
    'session',
    'replay_start',
    'replay_done',
    'raw',
    'history_restored',
    'history_restore_failed'
  ]) {
    assert.equal(shouldPersistEvent({ type }), false);
  }

  assert.equal(isInternalAi4mlUserMessage({
    type: 'user_message',
    text: '  #AI4ML_START_TASK'
  }), true);
  assert.equal(shouldPersistEvent({
    type: 'user_message',
    text: '#AI4ML_START_TASK'
  }), false);
  assert.equal(shouldPersistEvent({
    type: 'user_message',
    text: 'normal prompt'
  }), true);
  assert.equal(shouldPersistEvent({ type: 'task_completed' }), true);
});

test('compactReplayEvents collapses streamed assistant, working, and tool events', () => {
  const compacted = compactReplayEvents([
    { type: 'task_session_started', taskId: 'task-1', timestamp: 1 },
    { type: 'assistant_delta', itemId: 'assistant-1', data: 'Hello ', timestamp: 2 },
    { type: 'assistant_delta', itemId: 'assistant-1', data: 'world', timestamp: 3 },
    { type: 'assistant_done', itemId: 'assistant-1', timestamp: 4 },
    { type: 'working_start', itemId: 'working-1', title: 'Thinking', startedAt: 10 },
    { type: 'working_delta', itemId: 'working-1', data: 'step ', timestamp: 11 },
    { type: 'working_delta', itemId: 'working-1', data: 'one', timestamp: 12 },
    { type: 'working_done', itemId: 'working-1', completedAt: 13 },
    {
      type: 'tool_start',
      toolUseId: 'tool-1',
      tool: 'command',
      title: 'Running command',
      command: 'npm test',
      cwd: 'D:\\repo',
      startedAt: 20
    },
    { type: 'tool_output', toolUseId: 'tool-1', stream: 'stdout', data: 'ok\n', timestamp: 21 },
    { type: 'tool_output', toolUseId: 'tool-1', stream: 'stderr', data: 'warn\n', timestamp: 22 },
    { type: 'tool_result', toolUseId: 'tool-1', status: 'completed', exitCode: 0, durationMs: 7, completedAt: 27 },
    { type: 'task_completed', taskId: 'task-1', timestamp: 30 }
  ]);

  assert.deepEqual(compacted.map((event) => event.type), [
    'task_session_started',
    'assistant_snapshot',
    'assistant_done',
    'working_snapshot',
    'tool_snapshot',
    'task_completed'
  ]);
  assert.deepEqual(compacted.find((event) => event.type === 'assistant_snapshot'), {
    type: 'assistant_snapshot',
    itemId: 'assistant-1',
    text: 'Hello world',
    timestamp: 3
  });
  assert.deepEqual(compacted.find((event) => event.type === 'working_snapshot'), {
    type: 'working_snapshot',
    itemId: 'working-1',
    title: 'Thinking',
    text: 'step one',
    startedAt: 10,
    completedAt: 13,
    timestamp: 12
  });
  assert.deepEqual(compacted.find((event) => event.type === 'tool_snapshot'), {
    type: 'tool_snapshot',
    toolUseId: 'tool-1',
    tool: 'command',
    title: 'Running command',
    command: 'npm test',
    cwd: 'D:\\repo',
    stdout: 'ok\n',
    stderr: 'warn\n',
    status: 'completed',
    exitCode: 0,
    durationMs: 7,
    startedAt: 20,
    completedAt: 27,
    timestamp: 27
  });
});

test('compactReplayEvents replays from the latest or requested task boundary', () => {
  const events = [
    { type: 'task_session_started', taskId: 'task-1', timestamp: 1 },
    { type: 'workspace_ready', taskId: 'task-1', timestamp: 2 },
    { type: 'assistant_delta', itemId: 'assistant-old', taskId: 'task-1', data: 'old', timestamp: 3 },
    { type: 'task_session_started', taskId: 'task-2', timestamp: 4 },
    { type: 'workspace_ready', taskId: 'task-2', timestamp: 5 },
    { type: 'assistant_delta', itemId: 'assistant-new', taskId: 'task-2', data: 'new', timestamp: 6 }
  ];

  const latestReplay = compactReplayEvents(events);
  assert.equal(latestReplay[0].taskId, 'task-2');
  assert.equal(latestReplay.some((event) => event.taskId === 'task-1'), false);
  assert.equal(latestReplay.find((event) => event.type === 'assistant_snapshot')?.text, 'new');

  const requestedReplay = compactReplayEvents(events, { taskId: 'task-1' });
  assert.equal(requestedReplay[0].taskId, 'task-1');
  assert.equal(requestedReplay.some((event) => event.taskId === 'task-2'), false);
  assert.equal(requestedReplay.find((event) => event.type === 'assistant_snapshot')?.text, 'old');
});

test('hasUnclosedTurn treats completion, interruption, exit, and error as terminal events', () => {
  assert.equal(hasUnclosedTurn([{ type: 'turn_started' }]), true);
  assert.equal(hasUnclosedTurn([
    { type: 'turn_started' },
    { type: 'turn_completed' }
  ]), false);
  assert.equal(hasUnclosedTurn([
    { type: 'turn_started' },
    { type: 'turn_interrupted' }
  ]), false);
  assert.equal(hasUnclosedTurn([
    { type: 'turn_started' },
    { type: 'exit' }
  ]), false);
  assert.equal(hasUnclosedTurn([
    { type: 'turn_started' },
    { type: 'error' },
    { type: 'turn_started' }
  ]), true);
});

test('interruptionReasonForPayload preserves user-facing interruption messages', () => {
  assert.equal(
    interruptionReasonForPayload({ type: 'exit', exitCode: 9 }),
    'Codex app-server 进程已退出，当前任务未正常完成。退出码：9。'
  );
  assert.equal(
    interruptionReasonForPayload({ type: 'exit', exitCode: null }),
    'Codex app-server 进程已退出，当前任务未正常完成。退出码：unknown。'
  );
  assert.equal(
    interruptionReasonForPayload({ type: 'error', message: 'RPC timeout' }),
    'Codex 执行出错，当前任务已中断：RPC timeout'
  );
  assert.equal(
    interruptionReasonForPayload({ type: 'error' }),
    'Codex 执行出错，当前任务已中断。'
  );
});

test('safeFileName keeps only portable session log filename characters', () => {
  assert.equal(safeFileName('session/with spaces:and?marks'), 'session_with_spaces_and_marks');
  assert.equal(safeFileName('abc.DEF-123_456'), 'abc.DEF-123_456');
});
