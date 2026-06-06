import path from 'node:path';

const CODEX_INTERRUPTED_STATUSES = new Set(['interrupted']);
const CODEX_IMPROVEMENT_REVIEW_STATUSES = new Set([
  'waiting_improvement_review',
  'improvement_review',
  'waiting_improvement_approval'
]);
const IMPROVEMENT_DECISIONS = new Set(['continue_improvement', 'stop_and_report']);

function trimmedString(value) {
  return typeof value === 'string' ? value.trim() : '';
}

function optionalTrimmedString(value) {
  const text = trimmedString(value);
  return text ? text : undefined;
}

function normalizeTokenBudget(value) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return undefined;
  }
  return Math.max(0, parsed);
}

function timestampSource(options = {}) {
  return typeof options.now === 'function' ? options.now : Date.now;
}

export function normalizeStartTaskMessage(message = {}) {
  return {
    description: trimmedString(message.description),
    approvedPlanText: trimmedString(message.approvedPlanText),
    approvedPlanName: trimmedString(message.approvedPlanName),
    approvedPlanId: trimmedString(message.approvedPlanId),
    taskId: optionalTrimmedString(message.taskId),
    teamId: typeof message.teamId === 'string' ? message.teamId : undefined,
    tokenBudget: normalizeTokenBudget(message.tokenBudget)
  };
}

export function normalizeTaskThreadMessage(message = {}, activeTaskId) {
  return {
    taskId: optionalTrimmedString(message.taskId) || activeTaskId,
    threadId: optionalTrimmedString(message.threadId),
    tokenBudget: normalizeTokenBudget(message.tokenBudget),
    improvementDecision: normalizeImprovementDecision(message.improvementDecision)
  };
}

export function requireApprovedPlanText(message = {}) {
  const planText = trimmedString(message.planText);
  if (!planText) {
    throw new Error('确认计划不能为空。');
  }
  return planText;
}

export function resolveRequestedWorkspacePath(message = {}) {
  const workspacePath = optionalTrimmedString(message.workspacePath);
  return workspacePath ? path.resolve(workspacePath) : undefined;
}

export function resolveInterruptedResumeWorkspacePath(artifacts, requestedWorkspacePath) {
  return resolveResumeWorkspacePath(artifacts, requestedWorkspacePath, CODEX_INTERRUPTED_STATUSES);
}

export function resolveTaskResumeWorkspacePath(artifacts, requestedWorkspacePath, options = {}) {
  const allowedStatuses = new Set(CODEX_INTERRUPTED_STATUSES);
  if (options.improvementDecision) {
    for (const status of CODEX_IMPROVEMENT_REVIEW_STATUSES) {
      allowedStatuses.add(status);
    }
  }
  return resolveResumeWorkspacePath(artifacts, requestedWorkspacePath, allowedStatuses);
}

function resolveResumeWorkspacePath(artifacts, requestedWorkspacePath, allowedStatuses) {
  const resolvedWorkspacePath = requestedWorkspacePath || artifacts?.workspace?.path;

  if (!resolvedWorkspacePath) {
    throw new Error('没有可继续的任务工作区。');
  }

  if (artifacts?.workspace?.path && path.resolve(artifacts.workspace.path) !== resolvedWorkspacePath) {
    throw new Error('请求继续的工作区不是当前最新任务工作区。');
  }

  const progress = artifacts?.progress && typeof artifacts.progress === 'object'
    ? artifacts.progress
    : {};
  const status = typeof progress.status === 'string' ? progress.status : '';

  if (!allowedStatuses.has(status)) {
    throw new Error(`当前任务状态不是可恢复状态，实际状态是 ${status || 'unknown'}。`);
  }

  return resolvedWorkspacePath;
}

function normalizeImprovementDecision(value) {
  const text = trimmedString(value);
  return IMPROVEMENT_DECISIONS.has(text) ? text : undefined;
}

export function buildTaskStartEvents(input, options = {}) {
  const now = timestampSource(options);
  return [
    {
      type: 'task_session_started',
      taskId: input.taskId,
      teamId: input.teamId,
      timestamp: now()
    },
    {
      type: 'task_input_submitted',
      taskId: input.taskId,
      teamId: input.teamId,
      dataPath: input.dataPath,
      dataPathType: input.dataPathType,
      description: input.description,
      timestamp: now()
    },
    {
      type: 'workspace_creation_started',
      timestamp: now()
    }
  ];
}

export function buildRegeneratePlanEvents(options = {}) {
  const now = timestampSource(options);
  return [
    {
      type: 'plan_generation_started',
      timestamp: now()
    },
    {
      type: 'activity',
      label: 'Regenerating plan',
      status: 'pending'
    }
  ];
}

export function buildApprovePlanEvents(options = {}) {
  const now = timestampSource(options);
  return [
    {
      type: 'plan_approved',
      timestamp: now()
    },
    {
      type: 'modeling_started',
      timestamp: now()
    },
    {
      type: 'activity',
      label: 'Running approved plan',
      status: 'pending'
    }
  ];
}

export function buildResumeTaskEvents(input, options = {}) {
  const now = timestampSource(options);
  return [
    {
      type: 'task_resume_requested',
      workspacePath: input.workspacePath,
      timestamp: now()
    },
    {
      type: 'modeling_started',
      timestamp: now()
    },
    {
      type: 'activity',
      label: 'Resuming task',
      status: 'pending'
    }
  ];
}

export function evaluateTokenBudget(payload, state = {}) {
  const budget = normalizeTokenBudget(state.tokenBudget);
  if (budget === undefined || state.quotaInterrupted) {
    return {
      baselineTotalTokens: state.baselineTotalTokens,
      consumedTokens: 0,
      shouldInterrupt: false,
      totalTokens: tokenTotalFromPayload(payload)
    };
  }

  const totalTokens = tokenTotalFromPayload(payload);
  const lastTokens = tokenTotalFromPayload({ total: payload?.last });
  const baselineTotalTokens = Number.isFinite(state.baselineTotalTokens)
    ? state.baselineTotalTokens
    : Math.max(totalTokens - lastTokens, 0);
  const consumedTokens = Math.max(totalTokens - baselineTotalTokens, 0);

  return {
    baselineTotalTokens,
    consumedTokens,
    shouldInterrupt: totalTokens > 0 && consumedTokens >= budget,
    totalTokens
  };
}

function tokenTotalFromPayload(payload) {
  const total = payload?.total && typeof payload.total === 'object' ? payload.total : {};
  return normalizeTokenBudget(total.totalTokens ?? total.total_tokens) ?? 0;
}
