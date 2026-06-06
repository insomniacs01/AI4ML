import process from 'node:process';

import { heartbeatIntervalMs } from './config.js';
import {
  getLatestAi4mlWorkspaceArtifacts,
  initializeAi4mlWorkspace,
  isCompletedAi4mlArtifacts,
  markLatestAi4mlWorkspaceInterrupted,
  validateAi4mlDataPath,
  writeLatestAi4mlTokenUsage
} from './ai4ml-artifacts.js';
import {
  buildAi4mlApprovePlanPrompt,
  buildAi4mlResumeTaskPrompt,
  buildAi4mlStartTaskWithApprovedPlanPrompt,
  buildAi4mlStartTaskPrompt,
  loadAi4mlRegeneratePlanPrompt
} from './ai4ml-workspace-init.js';
import { createRunner } from './runners/index.js';
import { getSavedTaskThread, getSavedWorkspace, saveTaskThread, saveWebSession } from './session-store.js';
import { createSessionId, sendJson } from './utils.js';
import { createWebSessionEventLog } from './web-session-event-log.js';
import {
  buildApprovePlanEvents,
  buildRegeneratePlanEvents,
  buildResumeTaskEvents,
  buildTaskStartEvents,
  evaluateTokenBudget,
  normalizeStartTaskMessage,
  normalizeTaskThreadMessage,
  requireApprovedPlanText,
  resolveTaskResumeWorkspacePath,
  resolveRequestedWorkspacePath
} from './web-session-task-commands.js';
import { buildTaskStatePollTransition } from './web-session-task-state.js';
import {
  compactReplayEvents,
  hasUnclosedTurn,
  interruptionReasonForPayload,
  isInternalAi4mlUserMessage,
  shouldPersistEvent
} from './web-session-events.js';

const maxEventsInMemory = 5000;
const maxReplaySourceEvents = 20000;
const maxReplayEvents = 900;
const taskStatePollIntervalMs = 1500;
const taskStatePollTimeoutMs = 20 * 60 * 1000;

export class WebSessionManager {
  constructor() {
    this.sessions = new Map();
  }

  async getOrCreateSession(requestedSessionId, options = {}) {
    const cwd = process.cwd();
    const savedWorkspace = await getSavedWorkspace(cwd);
    const useSavedSession = options.useSavedSession !== false;
    const requestedTaskId = typeof options.taskId === 'string' && options.taskId.trim()
      ? options.taskId.trim()
      : undefined;
    const savedTaskThread = requestedTaskId
      ? await getSavedTaskThread(cwd, requestedTaskId)
      : null;
    const savedSessionId = typeof savedWorkspace?.webSessionId === 'string'
      ? savedWorkspace.webSessionId
      : undefined;
    const taskSessionId = typeof savedTaskThread?.webSessionId === 'string' && savedTaskThread.webSessionId
      ? savedTaskThread.webSessionId
      : undefined;
    const sessionId = requestedSessionId || taskSessionId || (useSavedSession ? savedSessionId : undefined) || createSessionId();

    if (this.sessions.has(sessionId)) {
      return this.sessions.get(sessionId);
    }

    const session = new PersistentWebSession(sessionId, cwd);
    this.sessions.set(sessionId, session);
    await saveWebSession(cwd, sessionId);
    await session.loadEvents();
    return session;
  }

  async startAi4mlTask(message, requestedSessionId) {
    const session = await this.getOrCreateSession(requestedSessionId, {
      useSavedSession: Boolean(requestedSessionId),
      taskId: message?.taskId
    });
    const result = await session.startAi4mlTask(message);
    return {
      sessionId: session.sessionId,
      ...result
    };
  }

  async approveAi4mlPlan(message, requestedSessionId) {
    const session = await this.getOrCreateSession(requestedSessionId, { taskId: message?.taskId });
    const result = await session.approveAi4mlPlan(message);
    return {
      sessionId: session.sessionId,
      ...result
    };
  }

  async regenerateAi4mlPlan(message, requestedSessionId) {
    const session = await this.getOrCreateSession(requestedSessionId, { taskId: message?.taskId });
    const result = await session.regenerateAi4mlPlan(message || {});
    return {
      sessionId: session.sessionId,
      ...result
    };
  }

  async interruptAi4mlTask(requestedSessionId, options = {}) {
    const session = await this.getOrCreateSession(requestedSessionId);
    await session.interruptCurrentTask(options.reason);
    return {
      sessionId: session.sessionId,
      threadId: session.runner.threadId,
      interrupted: true
    };
  }

  async resumeAi4mlTask(message, requestedSessionId) {
    const session = await this.getOrCreateSession(requestedSessionId, { taskId: message?.taskId });
    const result = await session.resumeAi4mlTask(message || {});
    return {
      sessionId: session.sessionId,
      ...result
    };
  }

  async getAi4mlTaskStatus(message, requestedSessionId) {
    const session = await this.getOrCreateSession(requestedSessionId, { taskId: message?.taskId });
    const result = await session.getAi4mlTaskStatus(message || {});
    return {
      sessionId: session.sessionId,
      ...result
    };
  }

  reloadCodexConfig() {
    const results = [...this.sessions.values()].map((session) => session.reloadCodexConfig());
    return {
      sessions: results,
      restarted: results.filter((item) => item.restarted).length,
      skipped: results.filter((item) => item.skipped).length
    };
  }
}

class PersistentWebSession {
  constructor(sessionId, cwd) {
    this.sessionId = sessionId;
    this.cwd = cwd;
    this.startedAt = new Date().toISOString();
    this.sockets = new Set();
    this.events = [];
    this.lastActivity = {
      type: 'activity',
      label: 'Ready',
      status: 'online'
    };
    this.runner = createRunner((payload) => this.publish(payload));
    this.eventLog = createWebSessionEventLog(sessionId);
    this.taskStarted = false;
    this.taskStartedAtMs = undefined;
    this.taskStatePollTimer = undefined;
    this.reportedTaskStates = new Set();
    this.taskCompleted = false;
    this.activeWorkspacePath = undefined;
    this.activeTaskId = undefined;
    this.persistedEvents = [];
    this.tokenBudget = undefined;
    this.tokenBudgetBaseline = undefined;
    this.quotaInterrupted = false;
  }

  async loadEvents() {
    try {
      const persistedEvents = (await this.eventLog.loadPayloads())
        .filter((payload) => !isInternalAi4mlUserMessage(payload))
        .filter((payload) => payload.type !== 'history_restore_failed');
      this.persistedEvents = persistedEvents.slice(-maxReplaySourceEvents);
      this.events = compactReplayEvents(persistedEvents).slice(-maxReplayEvents);
      this.taskStarted = this.events.some((event) => event.type === 'task_input_submitted');
      this.taskStartedAtMs = this.lastTaskStartTimestamp();
      this.taskCompleted = this.events.some((event) => event.type === 'task_completed');
      this.activeWorkspacePath = this.lastWorkspacePath();
      this.activeTaskId = this.lastTaskId();
      await this.closeStaleRunningTurn();
      const activity = [...this.events].reverse().find((event) => event.type === 'activity');
      if (activity) {
        this.lastActivity = activity;
      }
    } catch {
      this.events = [];
      this.taskStarted = false;
      this.taskStartedAtMs = undefined;
      this.taskCompleted = false;
      this.activeWorkspacePath = undefined;
      this.activeTaskId = undefined;
      this.persistedEvents = [];
    }
  }

  ensureStarted() {
    if (!this.runner.currentProcess && !this.runner.initializing && !this.runner.initialized) {
      this.runner.start();
    }
  }

  attach(socket, options = {}) {
    this.sockets.add(socket);
    const requestedTaskId = typeof options.taskId === 'string' && options.taskId.trim()
      ? options.taskId.trim()
      : undefined;
    const replayEvents = this.replayEventsForTask(requestedTaskId);
    const replayActivity = [...replayEvents].reverse().find((event) => event.type === 'activity') || this.lastActivity;
    const taskIsActive = !requestedTaskId || !this.activeTaskId || this.activeTaskId === requestedTaskId;

    sendJson(socket, {
      type: 'session',
      sessionId: this.sessionId,
      cwd: this.cwd,
      command: this.runner.commandLabel,
      startedAt: this.startedAt,
      replayed: replayEvents.length > 0
    });

    sendJson(socket, {
      type: 'replay_start',
      sessionId: this.sessionId,
      count: replayEvents.length
    });

    for (const event of replayEvents) {
      sendJson(socket, event);
    }

    sendJson(socket, {
      type: 'replay_done',
      sessionId: this.sessionId,
      running: taskIsActive && Boolean(this.runner.currentTurnId),
      activity: replayActivity
    });

    if (replayActivity) {
      sendJson(socket, replayActivity);
    }

    const heartbeat = setInterval(() => {
      sendJson(socket, {
        type: 'heartbeat',
        now: new Date().toISOString()
      });
    }, heartbeatIntervalMs);

    socket.on('message', (rawMessage) => this.handleSocketMessage(rawMessage, socket));
    socket.on('close', () => {
      clearInterval(heartbeat);
      this.sockets.delete(socket);
    });
    socket.on('error', () => {
      clearInterval(heartbeat);
      this.sockets.delete(socket);
    });
  }

  reloadCodexConfig() {
    if (this.runner.currentTurnId) {
      return {
        sessionId: this.sessionId,
        restarted: false,
        skipped: true,
        reason: 'active_turn'
      };
    }

    this.runner.reloadConfig();
    this.publish({
      type: 'activity',
      label: 'Model configuration reloaded',
      status: 'online'
    });
    return {
      sessionId: this.sessionId,
      restarted: true,
      skipped: false
    };
  }

  async useTaskThread(taskId, preferredThreadId) {
    const normalizedTaskId = typeof taskId === 'string' && taskId.trim()
      ? taskId.trim()
      : undefined;
    const normalizedThreadId = typeof preferredThreadId === 'string' && preferredThreadId.trim()
      ? preferredThreadId.trim()
      : undefined;
    const saved = normalizedTaskId
      ? await getSavedTaskThread(this.cwd, normalizedTaskId)
      : null;
    const threadId = normalizedThreadId || saved?.threadId;

    if (threadId && this.runner.threadId !== threadId) {
      this.runner.resumeThread(threadId);
    }
  }

  async saveActiveTaskThread(taskId) {
    const normalizedTaskId = typeof taskId === 'string' && taskId.trim()
      ? taskId.trim()
      : undefined;
    if (!normalizedTaskId || !this.runner.threadId) {
      return;
    }
    await saveTaskThread(this.cwd, normalizedTaskId, this.runner.threadId, this.sessionId);
  }

  handleSocketMessage(rawMessage, socket) {
    let message;

    try {
      message = JSON.parse(rawMessage.toString());
    } catch {
      return;
    }

    if (message.type === 'prompt' && typeof message.text === 'string') {
      this.publish({
        type: 'user_message',
        text: message.text,
        timestamp: Date.now()
      });
      this.runner.sendPrompt(message.text);
      return;
    }

    if (message.type === 'start_task') {
      this.startAi4mlTask(message).catch(() => {});
      return;
    }

    if (message.type === 'regenerate_plan') {
      this.regenerateAi4mlPlan().catch(() => {});
      return;
    }

    if (message.type === 'approve_plan') {
      this.approveAi4mlPlan(message).catch(() => {});
      return;
    }

    if (message.type === 'resume_task') {
      this.resumeAi4mlTask(message).catch(() => {});
      return;
    }

    if (message.type === 'interrupt') {
      this.interruptCurrentTask();
      return;
    }

    if (message.type === 'restart') {
      this.resetEventLog();
      this.runner.restart();
      sendJson(socket, {
        type: 'session',
        sessionId: this.sessionId,
        cwd: this.cwd,
        command: this.runner.commandLabel,
        startedAt: new Date().toISOString()
      });
    }
  }

  async startAi4mlTask(message) {
    try {
      const dataPath = await validateAi4mlDataPath(message.dataPath);
      const {
        description,
        approvedPlanText,
        approvedPlanName,
        approvedPlanId,
        taskId,
        teamId,
        tokenBudget
      } = normalizeStartTaskMessage(message);

      this.resetEventLog();
      this.applyTokenBudget(tokenBudget);
      this.runner.restart();
      this.taskStarted = true;
      this.taskCompleted = false;
      this.activeWorkspacePath = undefined;
      this.startedAt = new Date().toISOString();
      for (const event of buildTaskStartEvents({
        taskId,
        teamId,
        dataPath: dataPath.path,
        dataPathType: dataPath.type,
        description
      })) {
        this.publish(event);
      }
      const workspace = await initializeAi4mlWorkspace({
        taskId,
        teamId,
        dataPath: dataPath.path,
        dataPathType: dataPath.type,
        description,
        approvedPlanText,
        approvedPlanName,
        approvedPlanId
      });
      this.activeWorkspacePath = workspace.path;
      this.activeTaskId = taskId;
      this.publish({
        type: 'activity',
        label: 'Creating workspace',
        status: 'pending'
      });

      this.startTaskStatePolling();
      const promptText = approvedPlanText
        ? await buildAi4mlStartTaskWithApprovedPlanPrompt({
          dataPath: dataPath.path,
          dataPathType: dataPath.type,
          description,
          workspacePath: workspace.path,
          workspaceName: workspace.name,
          approvedPlanText,
          approvedPlanName
        })
        : await buildAi4mlStartTaskPrompt({
          dataPath: dataPath.path,
          dataPathType: dataPath.type,
          description,
          workspacePath: workspace.path,
          workspaceName: workspace.name
        });
      await this.runner.sendPrompt(promptText);
      await this.saveActiveTaskThread(taskId);
      return {
        accepted: true,
        threadId: this.runner.threadId,
        workspace,
        workspacePath: workspace.path,
        dataPath: dataPath.path,
        dataPathType: dataPath.type,
        startedAt: this.startedAt
      };
    } catch (error) {
      this.taskStarted = false;
      this.publish({
        type: 'error',
        message: `无法开始 AI4ML 任务：${error.message}`
      });
      throw error;
    }
  }

  async regenerateAi4mlPlan(message = {}) {
    try {
      const { taskId, threadId, tokenBudget } = normalizeTaskThreadMessage(message, this.activeTaskId);
      await this.useTaskThread(taskId, threadId);
      this.activeTaskId = taskId;
      this.applyTokenBudget(tokenBudget);
      this.reportedTaskStates.delete('plan_written');
      this.reportedTaskStates.delete('plan_approval_ready');
      this.startTaskStatePolling();
      for (const event of buildRegeneratePlanEvents()) {
        this.publish(event);
      }
      const promptText = await loadAi4mlRegeneratePlanPrompt();
      await this.runner.sendPrompt(promptText);
      await this.saveActiveTaskThread(taskId);
      return {
        accepted: true,
        threadId: this.runner.threadId
      };
    } catch (error) {
      this.publish({
        type: 'error',
        message: `无法重新生成方案：${error.message}`
      });
      throw error;
    }
  }

  async approveAi4mlPlan(message) {
    try {
      const { taskId, threadId, tokenBudget } = normalizeTaskThreadMessage(message, this.activeTaskId);
      await this.useTaskThread(taskId, threadId);
      this.activeTaskId = taskId;
      this.applyTokenBudget(tokenBudget);
      const planText = requireApprovedPlanText(message);

      for (const event of buildApprovePlanEvents()) {
        this.publish(event);
      }

      const promptText = await buildAi4mlApprovePlanPrompt(planText);
      await this.runner.sendPrompt(promptText);
      await this.saveActiveTaskThread(taskId);
      return {
        accepted: true,
        threadId: this.runner.threadId
      };
    } catch (error) {
      this.publish({
        type: 'error',
        message: `无法执行确认后的方案：${error.message}`
      });
      throw error;
    }
  }

  async resumeAi4mlTask(message) {
    try {
      const { taskId, threadId, tokenBudget, improvementDecision } = normalizeTaskThreadMessage(message, this.activeTaskId);
      await this.useTaskThread(taskId, threadId);
      this.applyTokenBudget(tokenBudget);
      const workspacePath = resolveRequestedWorkspacePath(message);
      const artifacts = await getLatestAi4mlWorkspaceArtifacts({
        workspacePath
      });
      const resolvedWorkspacePath = resolveTaskResumeWorkspacePath(artifacts, workspacePath, {
        improvementDecision
      });

      this.taskStarted = true;
      this.taskStartedAtMs = Date.now();
      this.taskCompleted = false;
      this.activeWorkspacePath = resolvedWorkspacePath;
      this.activeTaskId = taskId;
      this.reportedTaskStates.clear();
      for (const event of buildResumeTaskEvents({ workspacePath: resolvedWorkspacePath })) {
        this.publish(event);
      }

      const promptText = await buildAi4mlResumeTaskPrompt(resolvedWorkspacePath, {
        improvementDecision
      });
      this.startTaskStatePolling();
      await this.runner.sendPrompt(promptText);
      await this.saveActiveTaskThread(taskId);
      return {
        accepted: true,
        threadId: this.runner.threadId,
        workspacePath: resolvedWorkspacePath
      };
    } catch (error) {
      this.publish({
        type: 'error',
        message: `无法继续 AI4ML 任务：${error.message}`
      });
      throw error;
    }
  }

  async getAi4mlTaskStatus(message = {}) {
    const { taskId, threadId } = normalizeTaskThreadMessage(message, this.activeTaskId);
    const taskIsActive = !taskId || !this.activeTaskId || this.activeTaskId === taskId;
    const requestedWorkspacePath = typeof message.workspacePath === 'string' && message.workspacePath.trim()
      ? message.workspacePath.trim()
      : undefined;
    const workspacePath = requestedWorkspacePath || (taskIsActive ? this.activeWorkspacePath : undefined);
    let artifacts = workspacePath
      ? await getLatestAi4mlWorkspaceArtifacts({ workspacePath })
      : { workspace: null };
    const running = taskIsActive && Boolean(this.runner.currentTurnId);
    const progressStatus = typeof artifacts.progress?.status === 'string'
      ? artifacts.progress.status
      : '';

    if (!running && isActiveProgressStatus(progressStatus) && !isCompletedAi4mlArtifacts(artifacts)) {
      artifacts = await markLatestAi4mlWorkspaceInterrupted({
        workspacePath: artifacts.workspace?.path || workspacePath,
        interruptedAt: new Date().toISOString(),
        reason: 'Codex 当前没有运行中的执行轮次，AI4ML 已停止把该任务显示为运行中。'
      });
    }

    const latestProgressStatus = typeof artifacts.progress?.status === 'string'
      ? artifacts.progress.status
      : progressStatus;
    return {
      taskId,
      threadId: threadId || this.runner.threadId,
      workspacePath: artifacts.workspace?.path || workspacePath,
      running,
      completed: this.taskCompleted || isCompletedAi4mlArtifacts(artifacts),
      progressStatus: latestProgressStatus,
      activity: this.lastActivity
    };
  }

  async interruptCurrentTask(reason) {
    await this.runner.interrupt();
    await this.markTaskInterrupted(reason || '用户已发送停止信号，任务已中断。');
  }

  publish(payload) {
    if (!payload || typeof payload !== 'object') {
      return;
    }

    const shouldMarkInterrupted = (
      payload.type === 'exit' ||
      payload.type === 'error'
    ) && hasUnclosedTurn(this.events);

    if (payload.type === 'activity') {
      this.lastActivity = payload;
    }

    if (payload.type === 'token_usage_updated') {
      this.handleTokenUsageUpdated(payload).catch((error) => {
        this.publish({
          type: 'error',
          message: `无法处理大模型用量统计：${error.message}`
        });
      });
    }

    if (shouldPersistEvent(payload)) {
      this.events.push(payload);
      if (this.events.length > maxEventsInMemory) {
        this.events = this.events.slice(-maxEventsInMemory);
      }
      this.eventLog.append(payload);
    }

    for (const socket of this.sockets) {
      sendJson(socket, payload);
    }

    if (shouldMarkInterrupted) {
      this.markTaskInterrupted(interruptionReasonForPayload(payload)).catch((error) => {
        this.publish({
          type: 'error',
          message: `无法标记任务中断：${error.message}`
        });
      });
    }
  }

  async persistTokenUsage(payload) {
    if (!this.taskStartedAtMs) {
      return;
    }

    await writeLatestAi4mlTokenUsage({
      threadId: payload.threadId,
      turnId: payload.turnId,
      total: payload.total,
      last: payload.last,
      modelContextWindow: payload.modelContextWindow
    }, {
      sinceMs: this.taskStartedAtMs - 2000,
      workspacePath: this.activeWorkspacePath,
      sessionName: `codex:${this.sessionId}`
    });
  }

  applyTokenBudget(tokenBudget) {
    this.tokenBudget = Number.isFinite(tokenBudget) ? tokenBudget : undefined;
    this.tokenBudgetBaseline = undefined;
    this.quotaInterrupted = false;
  }

  async handleTokenUsageUpdated(payload) {
    await this.persistTokenUsage(payload);
    await this.enforceTokenBudget(payload);
  }

  async enforceTokenBudget(payload) {
    const budgetState = evaluateTokenBudget(payload, {
      tokenBudget: this.tokenBudget,
      baselineTotalTokens: this.tokenBudgetBaseline,
      quotaInterrupted: this.quotaInterrupted
    });
    this.tokenBudgetBaseline = budgetState.baselineTotalTokens;
    if (!budgetState.shouldInterrupt) {
      return;
    }

    this.quotaInterrupted = true;
    const reason = (
      `当前任务已达到本次运行 Token 额度上限 ${budgetState.consumedTokens}/${this.tokenBudget}，` +
      'AI4ML 已自动中断，避免继续消耗。'
    );
    this.publish({
      type: 'quota_exhausted',
      reason,
      tokenBudget: this.tokenBudget,
      consumedTokens: budgetState.consumedTokens,
      totalTokens: budgetState.totalTokens,
      timestamp: Date.now()
    });
    await this.interruptCurrentTask(reason);
  }

  resetEventLog() {
    this.events = [];
    this.persistedEvents = [];
    this.taskStarted = false;
    this.taskStartedAtMs = undefined;
    this.taskCompleted = false;
    this.activeWorkspacePath = undefined;
    this.activeTaskId = undefined;
    this.applyTokenBudget(undefined);
    this.reportedTaskStates.clear();
    this.stopTaskStatePolling();
    this.lastActivity = {
      type: 'activity',
      label: 'Restarting',
      status: 'pending'
    };
    this.eventLog.reset();
  }

  startTaskStatePolling() {
    this.stopTaskStatePolling();
    this.taskStartedAtMs = Date.now();
    this.taskStatePollTimer = setInterval(() => {
      this.pollTaskState().catch((error) => {
        this.publish({
          type: 'error',
          message: `无法读取任务阶段状态：${error.message}`
        });
        this.stopTaskStatePolling();
      });
    }, taskStatePollIntervalMs);
  }

  stopTaskStatePolling() {
    if (this.taskStatePollTimer) {
      clearInterval(this.taskStatePollTimer);
      this.taskStatePollTimer = undefined;
    }
  }

  async pollTaskState() {
    if (!this.taskStartedAtMs) {
      return;
    }

    if (this.taskCompleted) {
      return;
    }

    const artifacts = await getLatestAi4mlWorkspaceArtifacts({
      sinceMs: this.taskStartedAtMs - 2000,
      workspacePath: this.activeWorkspacePath
    });

    const transition = buildTaskStatePollTransition(artifacts, this.reportedTaskStates);
    for (const state of transition.reportedStates) {
      this.reportedTaskStates.add(state);
    }
    if (transition.activeWorkspacePath) {
      this.activeWorkspacePath = transition.activeWorkspacePath;
    }
    if (transition.taskCompleted) {
      this.taskCompleted = true;
    }
    for (const event of transition.events) {
      this.publish(event);
    }
    if (transition.stopPolling) {
      this.stopTaskStatePolling();
    }
    if (transition.stopCompletedTaskTurn) {
      await this.stopCompletedTaskTurn();
      return;
    }
    if (transition.stopPolling) {
      return;
    }

    if (Date.now() - this.taskStartedAtMs > taskStatePollTimeoutMs) {
      this.stopTaskStatePolling();
    }
  }

  lastTaskStartTimestamp() {
    const taskEvent = [...this.events]
      .reverse()
      .find((event) => event.type === 'task_session_started' || event.type === 'task_input_submitted');

    return typeof taskEvent?.timestamp === 'number' ? taskEvent.timestamp : undefined;
  }

  lastWorkspacePath() {
    const workspaceEvent = [...this.events]
      .reverse()
      .find((event) => typeof event.workspacePath === 'string' && event.workspacePath.trim());

    return typeof workspaceEvent?.workspacePath === 'string' ? workspaceEvent.workspacePath : undefined;
  }

  lastTaskId() {
    const taskEvent = [...this.events]
      .reverse()
      .find((event) => typeof event.taskId === 'string' && event.taskId.trim());

    return typeof taskEvent?.taskId === 'string' ? taskEvent.taskId : undefined;
  }

  replayEventsForTask(taskId) {
    if (!taskId || this.persistedEvents.length === 0) {
      return this.events;
    }

    return compactReplayEvents(this.persistedEvents, { taskId }).slice(-maxReplayEvents);
  }

  async closeStaleRunningTurn() {
    if (!hasUnclosedTurn(this.events)) {
      return;
    }

    const timestamp = Date.now();
    await this.markTaskInterrupted('Codex 进程或服务已重启，上一轮执行未正常完成。', {
      timestamp,
      persistOnly: true
    });
  }

  async markTaskInterrupted(reason, options = {}) {
    const timestamp = options.timestamp || Date.now();
    const eventPayloads = [
      {
        type: 'turn_interrupted',
        reason,
        timestamp
      },
      {
        type: 'activity',
        label: 'Interrupted',
        status: 'offline',
        timestamp
      }
    ];

    if (options.persistOnly) {
      for (const payload of eventPayloads) {
        this.events.push(payload);
        this.eventLog.append(payload);
      }
      this.lastActivity = eventPayloads[1];
    } else {
      for (const payload of eventPayloads) {
        this.publish(payload);
      }
    }

    this.stopTaskStatePolling();
    await markLatestAi4mlWorkspaceInterrupted({
      sinceMs: this.taskStartedAtMs ? this.taskStartedAtMs - 2000 : undefined,
      workspacePath: this.activeWorkspacePath,
      interruptedAt: new Date(timestamp).toISOString(),
      reason
    });
  }

  async stopCompletedTaskTurn() {
    const artifacts = await getLatestAi4mlWorkspaceArtifacts({
      sinceMs: this.taskStartedAtMs ? this.taskStartedAtMs - 2000 : undefined,
      workspacePath: this.activeWorkspacePath
    });

    if (!isCompletedAi4mlArtifacts(artifacts)) {
      return;
    }

    await this.runner.interrupt();
  }
}

function isActiveProgressStatus(status) {
  return ['running', 'in_progress', 'executing'].includes(String(status || '').trim())
}
