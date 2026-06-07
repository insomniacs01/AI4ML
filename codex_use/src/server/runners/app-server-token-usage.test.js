import assert from 'node:assert/strict';
import test from 'node:test';

import {
  normalizeTokenBucket,
  normalizeTokenUsageUpdate
} from './app-server-token-usage.js';

test('normalizeTokenBucket preserves only non-negative integer token fields', () => {
  assert.deepEqual(normalizeTokenBucket({
    inputTokens: '120',
    cachedInputTokens: 40,
    outputTokens: -7,
    reasoningOutputTokens: 'bad',
    totalTokens: ''
  }), {
    totalTokens: 120,
    inputTokens: 120,
    cachedInputTokens: 40,
    outputTokens: 0,
    reasoningOutputTokens: 0
  });
});

test('normalizeTokenUsageUpdate emits real token usage events with context fallback ids', () => {
  assert.deepEqual(normalizeTokenUsageUpdate({
    tokenUsage: {
      total: {
        inputTokens: 100,
        outputTokens: 25,
        cachedInputTokens: 30,
        reasoningOutputTokens: 5
      },
      last: {
        inputTokens: 10,
        outputTokens: 2
      },
      modelContextWindow: '128000'
    }
  }, {
    threadId: 'thread-1',
    turnId: 'turn-1',
    now: () => 12345
  }), {
    type: 'token_usage_updated',
    threadId: 'thread-1',
    turnId: 'turn-1',
    total: {
      totalTokens: 125,
      inputTokens: 100,
      cachedInputTokens: 30,
      outputTokens: 25,
      reasoningOutputTokens: 5
    },
    last: {
      totalTokens: 12,
      inputTokens: 10,
      cachedInputTokens: 0,
      outputTokens: 2,
      reasoningOutputTokens: 0
    },
    modelContextWindow: 128000,
    timestamp: 12345
  });
});

test('normalizeTokenUsageUpdate refuses missing or zero token usage', () => {
  assert.equal(normalizeTokenUsageUpdate({}, { threadId: 'thread-1' }), null);
  assert.equal(normalizeTokenUsageUpdate({
    tokenUsage: {
      total: {
        inputTokens: 0,
        outputTokens: 0
      }
    }
  }, { threadId: 'thread-1' }), null);
});
