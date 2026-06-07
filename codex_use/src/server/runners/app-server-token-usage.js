export function normalizeTokenUsageUpdate(params, context = {}) {
  const tokenUsage = params?.tokenUsage && typeof params.tokenUsage === 'object'
    ? params.tokenUsage
    : null;
  if (!tokenUsage) {
    return null;
  }

  const total = normalizeTokenBucket(tokenUsage.total);
  const last = normalizeTokenBucket(tokenUsage.last);
  if (total.totalTokens <= 0) {
    return null;
  }

  const now = typeof context.now === 'function' ? context.now : Date.now;
  return {
    type: 'token_usage_updated',
    threadId: typeof params.threadId === 'string' ? params.threadId : context.threadId,
    turnId: typeof params.turnId === 'string' ? params.turnId : context.turnId,
    total,
    last,
    modelContextWindow: coerceNonNegativeInt(tokenUsage.modelContextWindow),
    timestamp: now()
  };
}

export function normalizeTokenBucket(bucket) {
  const value = bucket && typeof bucket === 'object' ? bucket : {};
  const inputTokens = coerceNonNegativeInt(value.inputTokens);
  const cachedInputTokens = coerceNonNegativeInt(value.cachedInputTokens);
  const outputTokens = coerceNonNegativeInt(value.outputTokens);
  const reasoningOutputTokens = coerceNonNegativeInt(value.reasoningOutputTokens);
  const totalTokens = coerceNonNegativeInt(value.totalTokens) || inputTokens + outputTokens;
  return {
    totalTokens,
    inputTokens,
    cachedInputTokens,
    outputTokens,
    reasoningOutputTokens
  };
}

function coerceNonNegativeInt(value) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return 0;
  }
  return Math.max(parsed, 0);
}
