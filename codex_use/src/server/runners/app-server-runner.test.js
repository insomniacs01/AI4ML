import assert from 'node:assert/strict';
import test from 'node:test';

import { AppServerRunner } from './app-server-runner.js';

test('sendPrompt queues an approval prompt while a turn is still running', async () => {
  const events = [];
  const startedPrompts = [];
  const runner = new AppServerRunner((event) => events.push(event));
  runner.currentProcess = {};
  runner.initialized = true;
  runner.threadId = 'thread-1';
  runner.currentTurnId = 'turn-1';
  runner.startTurn = async (promptText) => {
    startedPrompts.push(promptText);
    runner.currentTurnId = 'turn-2';
    return { threadId: 'thread-1', turnId: 'turn-2' };
  };

  const result = await runner.sendPrompt('approved plan prompt', { queueIfBusy: true });

  assert.deepEqual(result, {
    threadId: 'thread-1',
    turnId: 'turn-1',
    queued: true
  });
  assert.equal(runner.hasActiveOrQueuedTurn(), true);

  runner.handleNotification('turn/completed', {
    turn: {
      id: 'turn-1',
      status: 'completed',
      completedAt: 1
    }
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(startedPrompts, ['approved plan prompt']);
  assert.equal(runner.currentTurnId, 'turn-2');
  assert.equal(events.some((event) => event.type === 'turn_completed'), true);
});
