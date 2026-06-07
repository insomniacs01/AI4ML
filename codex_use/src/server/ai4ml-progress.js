import { appendFile, mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

export const progressEventsRelativePath = 'state/progress_events.jsonl';
export const progressSnapshotRelativePath = 'output/progress.json';

const progressEventDefinitions = new Map([
  ['workspace_initialized', {
    status: 'running',
    step: 'workspace_initialized',
    title: '工作区已初始化',
    summary: 'AI4ML Codex-native 工作区已创建。'
  }],
  ['data_inspected', {
    status: 'running',
    step: 'dataset_analysis',
    title: '数据已检查',
    summary: 'Codex 已完成数据结构检查。'
  }],
  ['plan_generated', {
    status: 'waiting_plan_approval',
    step: 'waiting_plan_approval',
    title: '计划已生成',
    summary: 'Codex 已生成执行计划，等待用户确认。'
  }],
  ['plan_approved', {
    status: 'running',
    step: 'modeling',
    title: '计划已确认',
    summary: '用户已确认执行计划。'
  }],
  ['execution_started', {
    status: 'running',
    step: 'data_preparation',
    title: '执行已开始',
    summary: 'Codex 已开始执行确认后的建模流程。'
  }],
  ['modeling_started', {
    status: 'running',
    step: 'modeling',
    title: '建模已开始',
    summary: 'Codex 正在执行建模计划。'
  }],
  ['data_prepared', {
    status: 'running',
    step: 'data_preparation',
    title: '数据准备完成',
    summary: '训练前数据准备已完成。'
  }],
  ['baseline_completed', {
    status: 'running',
    step: 'baseline',
    title: '基线已完成',
    summary: '基线或对照结果已完成。'
  }],
  ['candidate_models_done', {
    status: 'running',
    step: 'candidate_models',
    title: '候选模型完成',
    summary: '候选模型或方法已完成。'
  }],
  ['validation_completed', {
    status: 'running',
    step: 'validation',
    title: '验证完成',
    summary: '模型验证或结果评估已完成。'
  }],
  ['artifacts_generated', {
    status: 'running',
    step: 'artifact_generation',
    title: '产物已生成',
    summary: '核心结果文件已生成。'
  }],
  ['final_review_completed', {
    status: 'running',
    step: 'final_review',
    title: '最终复核完成',
    summary: '最终结果复核已完成。'
  }],
  ['completed', {
    status: 'completed',
    step: 'completed',
    title: '任务已完成',
    summary: 'Codex 建模任务已完成。'
  }],
  ['interrupted', {
    status: 'interrupted',
    step: 'interrupted',
    title: '任务已中断',
    summary: 'Codex 运行已中断，可从当前工作区继续。'
  }],
  ['resume_requested', {
    status: 'running',
    step: 'resuming',
    title: '恢复运行',
    summary: '用户已要求从现有工作区继续运行。'
  }],
  ['failed', {
    status: 'failed',
    step: 'failed',
    title: '任务失败',
    summary: 'Codex 任务未正常完成。'
  }],
  ['cancelled', {
    status: 'cancelled',
    step: 'cancelled',
    title: '任务已取消',
    summary: '用户已取消任务。'
  }]
]);

const terminalStatuses = new Set(['completed', 'failed', 'cancelled']);

export async function initializeAi4mlProgress(workspacePath, details = {}) {
  await mkdir(progressStateDir(workspacePath), { recursive: true });
  await writeFile(progressEventsPath(workspacePath), '', 'utf8');
  return appendAi4mlProgressEvent(workspacePath, {
    event: 'workspace_initialized',
    actor: details.actor || 'ai4ml_backend',
    message: details.message || 'AI4ML 后端已创建 Codex-native 任务工作区和协议文件。',
    percent: Object.hasOwn(details, 'percent') ? details.percent : 0,
    percent_source: details.percent_source || 'workspace_initialized',
    evidence: details.evidence || ['input/task_request.json', 'input/project_rules.md'],
    steps: details.steps
  }, {
    previousProgress: null
  });
}

export async function appendAi4mlProgressEvent(workspacePath, eventInput = {}, options = {}) {
  const event = normalizeProgressEvent(eventInput);
  await mkdir(progressStateDir(workspacePath), { recursive: true });

  const previousEvents = await readAi4mlProgressEvents(workspacePath);
  const previousProgress = Object.hasOwn(options, 'previousProgress')
    ? options.previousProgress
    : await readProgressSnapshot(workspacePath);
  const events = [...previousEvents, event];
  const snapshot = buildAi4mlProgressSnapshot(events, { previousProgress });

  await appendFile(progressEventsPath(workspacePath), `${JSON.stringify(event)}\n`, 'utf8');
  await writeProgressSnapshot(workspacePath, snapshot);
  return snapshot;
}

export async function ensureAi4mlProgressSnapshot(workspacePath, options = {}) {
  const currentProgress = Object.hasOwn(options, 'currentProgress')
    ? options.currentProgress
    : await readProgressSnapshot(workspacePath);
  const current = currentProgress && typeof currentProgress === 'object' ? currentProgress : {};
  const events = await readAi4mlProgressEvents(workspacePath);

  if (!shouldRepairSnapshot(current, events)) {
    return currentProgress;
  }

  const eventSnapshot = buildAi4mlProgressSnapshot(events, { previousProgress: null });
  const repaired = repairSnapshotFromEvents(current, eventSnapshot);
  await writeProgressSnapshot(workspacePath, repaired);
  return repaired;
}

export async function readAi4mlProgressEvents(workspacePath) {
  let text;
  try {
    text = await readFile(progressEventsPath(workspacePath), 'utf8');
  } catch {
    return [];
  }

  const events = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) {
      continue;
    }
    try {
      const payload = JSON.parse(line);
      if (payload && typeof payload === 'object') {
        events.push(payload);
      }
    } catch {
      // Ignore malformed historical event lines; progress.json remains readable.
    }
  }
  return events;
}

export function buildAi4mlProgressSnapshot(events, options = {}) {
  const orderedEvents = Array.isArray(events)
    ? events.filter((event) => event && typeof event === 'object')
    : [];
  const previousProgress = options.previousProgress && typeof options.previousProgress === 'object'
    ? options.previousProgress
    : {};
  let percent = coercePercent(previousProgress.percent ?? previousProgress.progress_percent);
  let percentSource = percent === null ? null : previousProgress.percent_source || previousProgress.progress_source || 'previous_progress_snapshot';
  let status = stringOrNull(previousProgress.status) || 'running';
  let currentStep = stringOrNull(previousProgress.current_step) || stringOrNull(previousProgress.currentStage) || 'workspace_initialized';
  let summary = stringOrNull(previousProgress.summary) || '';
  let updatedAt = stringOrNull(previousProgress.updated_at) || new Date().toISOString();
  let latestSteps = null;

  for (const event of orderedEvents) {
    const definition = progressEventDefinitions.get(String(event.event || ''));
    const eventStatus = stringOrNull(event.status) || definition?.status;
    const eventStep = stringOrNull(event.step) || stringOrNull(event.current_step) || definition?.step;
    const eventSummary = stringOrNull(event.message) || stringOrNull(event.summary) || definition?.summary;
    const explicitPercent = Object.hasOwn(event, 'percent') ? coercePercent(event.percent) : null;

    if (eventStatus) {
      status = eventStatus;
    }
    if (eventStep) {
      currentStep = eventStep;
    }
    if (eventSummary) {
      summary = eventSummary;
    }
    if (stringOrNull(event.ts)) {
      updatedAt = event.ts;
    }
    if (Array.isArray(event.steps)) {
      latestSteps = event.steps;
    }

    if (explicitPercent !== null) {
      const previousPercent = percent;
      const nextPercent = status === 'completed'
        ? 100
        : Math.max(percent ?? 0, explicitPercent);
      const advanced = previousPercent === null || nextPercent > previousPercent || status === 'completed';
      percent = nextPercent;
      if (status === 'completed') {
        percent = 100;
      }
      if (advanced) {
        percentSource = stringOrNull(event.percent_source) || 'progress_event_percent';
      }
    }
  }

  if (status === 'completed') {
    percent = 100;
    percentSource = 'completed';
  } else if (['failed', 'cancelled', 'interrupted'].includes(status) && percent !== null) {
    percent = Math.min(99, Math.max(0, percent));
  } else if (percent !== null) {
    percent = Math.min(99, Math.max(0, percent));
  }
  if (percentSource === 'workspace_initialized' && currentStep !== 'workspace_initialized' && status !== 'completed') {
    percent = null;
    percentSource = null;
  }

  const snapshot = {
    schema_version: 'ai4ml-progress-v1',
    status,
    current_step: currentStep,
    summary,
    updated_at: updatedAt,
    events_path: progressEventsRelativePath,
    steps: Array.isArray(latestSteps) ? latestSteps : buildEventSteps(orderedEvents)
  };

  if (percent !== null) {
    snapshot.percent = percent;
    snapshot.percent_source = percentSource || 'progress_event_percent';
  }
  if (terminalStatuses.has(status)) {
    snapshot.finished_at = updatedAt;
  }
  return snapshot;
}

export function progressEventsPath(workspacePath) {
  return path.join(workspacePath, progressEventsRelativePath);
}

export function progressSnapshotPath(workspacePath) {
  return path.join(workspacePath, progressSnapshotRelativePath);
}

function progressStateDir(workspacePath) {
  return path.join(workspacePath, 'state');
}

function shouldRepairSnapshot(progress, events) {
  if (!Array.isArray(events) || events.length === 0) {
    return false;
  }
  if (!progress || typeof progress !== 'object') {
    return true;
  }
  return coercePercent(progress.percent ?? progress.progress_percent) === null;
}

function repairSnapshotFromEvents(progress, eventSnapshot) {
  const current = progress && typeof progress === 'object' ? progress : {};
  const status = stringOrNull(current.status) || eventSnapshot.status || 'running';
  const repaired = {
    schema_version: 'ai4ml-progress-v1',
    status,
    current_step: stringOrNull(current.current_step) || eventSnapshot.current_step || 'workspace_initialized',
    summary: stringOrNull(current.summary) || eventSnapshot.summary || '',
    updated_at: stringOrNull(current.updated_at) || eventSnapshot.updated_at || new Date().toISOString(),
    events_path: progressEventsRelativePath,
    steps: Array.isArray(current.steps) && current.steps.length
      ? current.steps
      : eventSnapshot.steps || []
  };

  const eventPercent = coercePercent(eventSnapshot.percent);
  if (status === 'completed') {
    repaired.percent = 100;
    repaired.percent_source = 'completed';
  } else if (eventPercent !== null) {
    repaired.percent = Math.min(99, Math.max(0, eventPercent));
    repaired.percent_source = eventSnapshot.percent_source || 'progress_event_percent';
  }
  if (eventSnapshot.finished_at || terminalStatuses.has(status)) {
    repaired.finished_at = eventSnapshot.finished_at || repaired.updated_at;
  }
  return repaired;
}

async function readProgressSnapshot(workspacePath) {
  try {
    const payload = JSON.parse(await readFile(progressSnapshotPath(workspacePath), 'utf8'));
    return payload && typeof payload === 'object' ? payload : {};
  } catch {
    return {};
  }
}

async function writeProgressSnapshot(workspacePath, snapshot) {
  const filePath = progressSnapshotPath(workspacePath);
  await mkdir(path.dirname(filePath), { recursive: true });
  const temporaryFile = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  const content = `${JSON.stringify(snapshot, null, 2)}\n`;
  await writeFile(temporaryFile, content, 'utf8');
  await replaceFile(temporaryFile, filePath, content);
}

async function replaceFile(temporaryFile, targetFile, content) {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      await rename(temporaryFile, targetFile);
      return;
    } catch (error) {
      if (!isRetriableReplaceError(error)) {
        throw error;
      }
      if (attempt === 4) {
        await writeFile(targetFile, content, 'utf8');
        await rm(temporaryFile, { force: true });
        return;
      }
      await delay(20 * (attempt + 1));
    }
  }
}

function isRetriableReplaceError(error) {
  return error?.code === 'EPERM' || error?.code === 'EACCES' || error?.code === 'EBUSY';
}

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function normalizeProgressEvent(eventInput) {
  const eventName = stringOrNull(eventInput.event) || 'progress_observed';
  const now = new Date().toISOString();
  const event = {
    ts: stringOrNull(eventInput.ts) || stringOrNull(eventInput.timestamp) || now,
    event: eventName,
    actor: stringOrNull(eventInput.actor) || 'ai4ml',
  };

  for (const key of ['status', 'step', 'current_step', 'message', 'summary', 'percent_source']) {
    const value = stringOrNull(eventInput[key]);
    if (value) {
      event[key] = value;
    }
  }
  if (Object.hasOwn(eventInput, 'percent')) {
    event.percent = eventInput.percent;
  }
  if (Array.isArray(eventInput.evidence)) {
    event.evidence = eventInput.evidence.filter((item) => typeof item === 'string' && item.trim());
  }
  if (Array.isArray(eventInput.steps)) {
    event.steps = eventInput.steps;
  }
  return event;
}

function buildEventSteps(events) {
  if (!events.length) {
    return [];
  }
  return events.map((event, index) => {
    const definition = progressEventDefinitions.get(String(event.event || ''));
    const latest = index === events.length - 1;
    const status = stringOrNull(event.status) || definition?.status || 'running';
    return {
      id: stringOrNull(event.step) || definition?.step || String(event.event || `event_${index + 1}`),
      title: definition?.title || String(event.event || `进度事件 ${index + 1}`),
      status: latest ? stepStatusFromSnapshotStatus(status) : 'completed',
      detail: stringOrNull(event.message) || stringOrNull(event.summary) || definition?.summary || '',
      updated_at: stringOrNull(event.ts) || undefined,
      evidence: Array.isArray(event.evidence) ? event.evidence : []
    };
  });
}

function stepStatusFromSnapshotStatus(status) {
  if (status === 'completed') {
    return 'completed';
  }
  if (status === 'interrupted') {
    return 'interrupted';
  }
  if (status === 'failed' || status === 'cancelled') {
    return 'failed';
  }
  if (status.startsWith('waiting_') || status === 'plan_ready') {
    return 'waiting_human';
  }
  return 'running';
}

function coercePercent(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return null;
  }
  return Math.round(numeric);
}

function stringOrNull(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
