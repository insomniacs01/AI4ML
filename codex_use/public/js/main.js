import { elements, state } from './state.js';
import { formatTime, refreshIcons } from './utils.js';
import {
  resizeComposer,
  setActivity,
  setComposerEnabled,
  setConnectionStatus,
  updateHeartbeat
} from './ui.js';
import {
  addAssistantMessage,
  addSystemMessage,
  addUserMessage,
  appendPendingAssistantText,
  appendRaw,
  finishAssistantMessage,
  flushPendingAssistantMessage,
  flushOutput,
  markPendingAssistantMessageDone,
  queueOutput
} from './render/messages.js';
import {
  appendToolOutput,
  appendWorkingText,
  addHistoryWorkingBlock,
  finishWorkingBlock,
  movePendingAssistantToWorking,
  renderToolResult,
  renderToolStart,
  startWorkingBlock,
  updateToolProgress
} from './render/timeline.js';

const phaseOrder = ['workspace', 'requirements', 'plan', 'approval', 'modeling', 'report'];
const phaseStatusText = {
  pending: '等待开始',
  active: '正在进行',
  done: '已完成'
};

function connect() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const sessionQuery = state.sessionId ? `?sessionId=${encodeURIComponent(state.sessionId)}` : '';
  state.socket = new WebSocket(`${protocol}//${window.location.host}/terminal${sessionQuery}`);

  setConnectionStatus('Connecting', 'pending');
  setActivity('Starting', 'pending');

  state.socket.addEventListener('open', () => {
    setConnectionStatus('Connected', 'online');
    setActivity('Connecting', 'pending');
    setComposerEnabled(true);
  });

  state.socket.addEventListener('message', (event) => {
    if (typeof event.data !== 'string') {
      return;
    }

    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }

    handleServerMessage(message);
  });

  state.socket.addEventListener('close', () => {
    setConnectionStatus('Closed', 'offline');
    setActivity('Disconnected', 'offline');
    setComposerEnabled(false);
    finishInterruptedWorkingBlock('Disconnected');
    flushOutput();
    if (!state.replaying) {
      addSystemMessage('页面已断开本地 Codex 会话；刷新或重新连接后会回到同一会话。', 'warning');
    }
  });

  state.socket.addEventListener('error', () => {
    setConnectionStatus('Error', 'offline');
    setActivity('Connection error', 'offline');
    setComposerEnabled(false);
    finishInterruptedWorkingBlock('Interrupted');
  });
}

function handleServerMessage(message) {
  if (message.type === 'session') {
    if (typeof message.sessionId === 'string' && message.sessionId) {
      state.sessionId = message.sessionId;
      window.localStorage.setItem('codexWebConsole.sessionId', message.sessionId);
    }
    elements.commandValue.textContent = message.command || 'codex';
    elements.cwdValue.textContent = message.cwd || '--';
    elements.startedValue.textContent = formatTime(message.startedAt);
    if (!message.replayed) {
      addSystemMessage('Codex Web 会话已就绪。请选择数据并填写任务描述后开始。', 'success');
    }
    return;
  }

  if (message.type === 'replay_start') {
    resetConversationForReplay();
    state.replaying = true;
    return;
  }

  if (message.type === 'replay_done') {
    state.replaying = false;
    const activity = message.activity && typeof message.activity === 'object'
      ? message.activity
      : null;
    if (!message.running) {
      if (isInterruptedActivity(activity)) {
        finishInterruptedWorkingBlock('Interrupted', durationUntilTimestamp(activity?.timestamp));
      } else {
        finishWorkingBlock();
      }
      state.currentTurnStartedAt = null;
    }
    if (activity) {
      setActivity(activity.label || 'Ready', activity.status || 'online');
      state.runState = activity.status === 'busy' || message.running ? 'running' : 'idle';
    } else {
      setActivity(message.running ? 'Running' : 'Ready', message.running ? 'busy' : 'online');
      state.runState = message.running ? 'running' : 'idle';
    }
    refreshLatestWorkspace({ silent: true });
    return;
  }

  if (message.type === 'turn_interrupted') {
    const wasReplaying = state.replaying;
    const durationMs = durationUntilTimestamp(message.timestamp);
    state.resumeInProgress = false;
    flushOutput();
    flushPendingAssistantMessage();
    finishAssistantMessage();
    finishInterruptedWorkingBlock('Interrupted', durationMs);
    state.currentTurnStartedAt = null;
    state.runState = 'idle';
    setActivity('Interrupted', 'offline');
    setTaskCreationEnabled(true);
    addSystemMessage(message.reason || '任务已中断。', 'warning', message.timestamp);
    window.setTimeout(() => refreshLatestWorkspace({ silent: wasReplaying }), 500);
    return;
  }

  if (message.type === 'history_restored') {
    restoreHistory(message.entries);
    return;
  }

  if (message.type === 'history_restore_failed') {
    return;
  }

  if (message.type === 'task_session_started') {
    resetConversationForReplay();
    resetPhaseDetails();
    setResumeTaskVisible(false);
    addSystemMessage('已创建新任务，会为本次任务启动独立 Codex 进程。', 'success', message.timestamp);
    return;
  }

  if (message.type === 'task_input_submitted') {
    setTaskCreationEnabled(false);
    setTaskPhase('workspace');
    const description = message.description ? `\n\n任务描述：\n${message.description}` : '';
    addUserMessage(`开始 AI4ML 任务\n\n数据路径：\n${message.dataPath || '--'}${description}`, message.timestamp);
    return;
  }

  if (message.type === 'workspace_creation_started') {
    setTaskPhase('workspace', {
      workspace: '正在建立任务工作区'
    });
    setActivity('Creating workspace', 'pending');
    addSystemMessage('正在建立任务工作区。', 'success', message.timestamp);
    return;
  }

  if (message.type === 'workspace_ready') {
    setTaskPhase('requirements', {
      workspace: '已创建',
      requirements: '正在解析需求和数据结构'
    });
    addSystemMessage(`任务工作区已创建：${message.workspacePath || ''}`, 'success', message.timestamp);
    return;
  }

  if (message.type === 'requirements_analysis_started') {
    setTaskPhase('requirements', {
      workspace: '已创建',
      requirements: '正在解析需求和数据结构'
    });
    addSystemMessage('正在解析需求和数据结构。', 'success', message.timestamp);
    return;
  }

  if (message.type === 'requirements_analysis_completed') {
    setTaskPhase('plan', {
      workspace: '已创建',
      requirements: '已完成',
      plan: '正在生成可执行计划'
    });
    addSystemMessage('需求和数据结构解析已完成。', 'success', message.timestamp);
    return;
  }

  if (message.type === 'plan_generation_started') {
    setTaskPhase('plan', {
      workspace: '已创建',
      requirements: '已完成',
      plan: '正在生成可执行计划'
    });
    setPlanControlsEnabled(false);
    addSystemMessage('正在解析文档并生成可执行计划。', 'success', message.timestamp);
    return;
  }

  if (message.type === 'plan_generation_completed') {
    const wasReplaying = state.replaying;
    setTaskPhase('approval', {
      workspace: '已创建',
      requirements: '已完成',
      plan: '已生成',
      approval: '等待确认'
    });
    addSystemMessage('可执行计划已生成，等待确认。', 'success', message.timestamp);
    refreshLatestWorkspace({ silent: wasReplaying });
    return;
  }

  if (message.type === 'plan_approved') {
    setResumeTaskVisible(false);
    setTaskPhase('modeling', {
      workspace: '已创建',
      requirements: '已完成',
      plan: '已确认',
      approval: '已确认',
      modeling: '正在执行'
    });
    setPlanControlsEnabled(false);
    addSystemMessage('已确认计划，开始执行建模流程。', 'success', message.timestamp);
    return;
  }

  if (message.type === 'task_resume_requested') {
    setResumeTaskVisible(false);
    setTaskCreationEnabled(false);
    setPlanControlsEnabled(false);
    setTaskPhase('modeling', {
      workspace: '已创建',
      requirements: '已完成',
      plan: '已生成',
      approval: '已确认',
      modeling: '正在恢复执行',
      report: '未生成'
    });
    addSystemMessage(`正在恢复执行任务工作区：${message.workspacePath || ''}`, 'success', message.timestamp);
    return;
  }

  if (message.type === 'modeling_started') {
    setTaskPhase('modeling', {
      modeling: '正在执行'
    });
    setActivity('Running approved plan', 'pending');
    return;
  }

  if (message.type === 'task_completed') {
    state.resumeInProgress = false;
    setResumeTaskVisible(false);
    setTaskPhase('report', {
      workspace: '已创建',
      requirements: '已完成',
      plan: '已完成',
      approval: '已完成',
      modeling: '已完成',
      report: '已生成'
    });
    setTaskCreationEnabled(true);
    setPlanControlsEnabled(false);
    setActivity('Ready', 'online');
    addSystemMessage(`最终报告已生成：${message.reportPath || message.workspacePath || ''}`, 'success', message.timestamp);
    return;
  }

  if (message.type === 'user_message' && typeof message.text === 'string') {
    addUserMessage(message.text, message.timestamp);
    return;
  }

  if (message.type === 'assistant_delta' && typeof message.data === 'string') {
    appendPendingAssistantText(message.data);
    return;
  }

  if (message.type === 'output' && typeof message.data === 'string') {
    queueOutput(message.data);
    return;
  }

  if (message.type === 'assistant_done') {
    markPendingAssistantMessageDone();
    return;
  }

  if (message.type === 'turn_started') {
    state.runState = 'running';
    state.currentTurnStartedAt = message.officialStartedAt || message.startedAt || Date.now();
    startWorkingBlock(state.currentTurnStartedAt);
    return;
  }

  if (message.type === 'turn_completed') {
    const wasReplaying = state.replaying;
    state.resumeInProgress = false;
    flushOutput();
    flushPendingAssistantMessage();
    finishAssistantMessage();
    finishWorkingBlock(message.officialDurationMs ?? message.durationMs);
    state.currentTurnStartedAt = null;
    state.runState = 'idle';
    window.setTimeout(() => refreshLatestWorkspace({ silent: wasReplaying }), 800);
    return;
  }

  if (message.type === 'working_start') {
    if (state.runState !== 'running') {
      return;
    }

    startWorkingBlock(message.startedAt, message.title);
    return;
  }

  if (message.type === 'working_delta' && typeof message.data === 'string') {
    if (state.runState !== 'running') {
      return;
    }

    movePendingAssistantToWorking();
    appendWorkingText(message.data);
    return;
  }

  if (message.type === 'working_done') {
    return;
  }

  if (message.type === 'tool_start') {
    if (state.runState !== 'running') {
      return;
    }

    renderToolStart(message);
    return;
  }

  if (message.type === 'tool_output') {
    if (state.runState !== 'running') {
      return;
    }

    appendToolOutput(message);
    return;
  }

  if (message.type === 'tool_progress') {
    if (state.runState !== 'running') {
      return;
    }

    updateToolProgress(message);
    return;
  }

  if (message.type === 'tool_result') {
    if (state.runState !== 'running' && !state.toolBlocks.has(message.toolUseId)) {
      return;
    }

    renderToolResult(message);
    return;
  }

  if (message.type === 'raw' && typeof message.data === 'string') {
    appendRaw(`[${message.stream || 'raw'}] ${message.data}\n`);
    return;
  }

  if (message.type === 'event') {
    appendRaw(`${JSON.stringify(message.event)}\n`);
    return;
  }

  if (message.type === 'activity') {
    if (state.replaying) {
      return;
    }

    setActivity(message.label || 'Working', message.status || 'pending');
    if (message.status === 'busy') {
      state.runState = 'running';
    } else if (message.status === 'online') {
      state.runState = 'idle';
    }
    if (message.usage) {
      appendRaw(`[usage] ${JSON.stringify(message.usage)}\n`);
    }
    return;
  }

  if (message.type === 'error') {
    flushOutput();
    finishInterruptedWorkingBlock('Interrupted');
    state.runState = 'idle';
    setActivity('Error', 'offline');
    setTaskCreationEnabled(true);
    setPlanControlsEnabled(true);
    addSystemMessage(message.message || 'Codex 执行出错。', 'warning');
    return;
  }

  if (message.type === 'heartbeat') {
    updateHeartbeat(message.now);
    return;
  }

  if (message.type === 'exit') {
    flushOutput();
    state.runState = 'idle';
    if (message.exitCode === 0) {
      finishWorkingBlock();
      setActivity('Ready', 'online');
    } else {
      finishInterruptedWorkingBlock('Interrupted');
      setActivity(`Exited ${message.exitCode}`, 'offline');
      addSystemMessage(`Codex 执行已结束，退出码 ${message.exitCode}。`, 'warning');
    }
  }
}

async function refreshLatestWorkspace({ silent = false } = {}) {
  try {
    const response = await fetch('/api/latest-workspace', { cache: 'no-store' });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.error || '无法读取任务工作区。');
    }

    const workspace = payload.workspace;
    if (!workspace) {
      return;
    }

    elements.workspacePathValue.textContent = workspace.path || '--';
    const progress = payload.progress && typeof payload.progress === 'object' ? payload.progress : {};
    const status = typeof progress.status === 'string' ? progress.status : '';
    const planText = typeof payload.plan === 'string' ? payload.plan : '';

    if (status === 'interrupted') {
      if (state.resumeInProgress && state.resumableWorkspacePath === workspace.path) {
        setTaskPhase('modeling', {
          workspace: '已创建',
          requirements: '已完成',
          plan: '已生成',
          approval: '已确认',
          modeling: '正在恢复执行',
          report: '未生成'
        });
        return;
      }

      finishInterruptedWorkingBlock('Interrupted');
      setTaskPhase('modeling', {
        workspace: '已创建',
        requirements: '已完成',
        plan: '已生成',
        approval: '已确认',
        modeling: '已中断',
        report: '未生成'
      });
      setActivity('Interrupted', 'offline');
      setPlanControlsEnabled(false);
      setTaskCreationEnabled(true);
      setResumeTaskVisible(true, workspace.path);
      if (!silent && state.lastAnnouncedInterruptedWorkspace !== workspace.path) {
        addSystemMessage(progress.summary || '任务已中断，未生成最终报告。', 'warning');
        state.lastAnnouncedInterruptedWorkspace = workspace.path;
      }
      return;
    }

    if (status === 'waiting_plan_approval' && planText) {
      showPlanForReview(planText, workspace.path);
      setTaskPhase('approval', {
        workspace: '已创建',
        requirements: '已完成',
        plan: '已生成',
        approval: '等待确认'
      });
      if (!silent && state.lastAnnouncedPlanWorkspace !== workspace.path) {
        addSystemMessage('方案已生成，可以在上方编辑后确认执行，或点击重新生成。', 'success');
        state.lastAnnouncedPlanWorkspace = workspace.path;
      }
      return;
    }

    if (payload.report?.exists || status === 'completed') {
      setTaskPhase('report');
      setTaskPhase('report', {
        workspace: '已创建',
        requirements: '已完成',
        plan: '已完成',
        approval: '已完成',
        modeling: '已完成',
        report: '已生成'
      });
      setPlanControlsEnabled(false);
      setTaskCreationEnabled(true);
      setResumeTaskVisible(false);
      if (!silent && state.lastAnnouncedReportWorkspace !== workspace.path) {
        addSystemMessage(`最终报告已生成：${payload.report?.path || workspace.path}`, 'success');
        state.lastAnnouncedReportWorkspace = workspace.path;
      }
    }
  } catch (error) {
    if (!silent) {
      addSystemMessage(error.message || '无法读取最新任务状态。', 'warning');
    }
  }
}

function showPlanForReview(planText, workspacePath) {
  elements.planPanel.hidden = false;
  setPlanExpanded(state.planExpanded && state.planWorkspacePath === workspacePath);
  elements.workspacePathValue.textContent = workspacePath || '--';

  if (state.planWorkspacePath !== workspacePath || !state.planEditorDirty) {
    elements.planEditor.value = planText;
    state.planEditorDirty = false;
  }

  state.planWorkspacePath = workspacePath;
  setPlanControlsEnabled(true);
}

function startTask() {
  const dataPath = elements.dataPathInput.value.trim();
  const description = elements.taskDescriptionInput.value.trim();

  if (!dataPath) {
    addSystemMessage('请先选择一个数据文件或文件夹。', 'warning');
    return;
  }

  if (!description) {
    addSystemMessage('请填写任务描述。目标可以是多个，也可以不是字段名。', 'warning');
    return;
  }

  const sent = sendMessage({
    type: 'start_task',
    dataPath,
    description
  });

  if (!sent) {
    return;
  }

  elements.planPanel.hidden = true;
  setPlanExpanded(false);
  state.planEditorDirty = false;
  state.resumeInProgress = false;
  setTaskCreationEnabled(false);
  setResumeTaskVisible(false);
  setPlanControlsEnabled(false);
  setTaskPhase('workspace', {
    workspace: '等待 Codex 创建'
  });
  setActivity('Queued', 'pending');
}

function resumeTask() {
  const workspacePath = state.resumableWorkspacePath || elements.workspacePathValue.textContent.trim();

  if (!workspacePath || workspacePath === '--') {
    addSystemMessage('没有可继续执行的任务工作区。', 'warning');
    return;
  }

  if (!sendMessage({
    type: 'resume_task',
    workspacePath
  })) {
    return;
  }

  setResumeTaskVisible(false);
  state.resumeInProgress = true;
  state.resumableWorkspacePath = workspacePath;
  setTaskCreationEnabled(false);
  setPlanControlsEnabled(false);
  setTaskPhase('modeling', {
    modeling: '正在恢复执行'
  });
  setActivity('Queued', 'pending');
}

async function selectDataPath(mode) {
  setTaskCreationEnabled(false);
  elements.taskHint.textContent = mode === 'directory'
    ? '正在打开文件夹选择窗口...'
    : '正在打开文件选择窗口...';

  try {
    const response = await fetch(`/api/select-data-path?mode=${encodeURIComponent(mode)}`, { cache: 'no-store' });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.error || '选择数据失败。');
    }

    if (payload.cancelled) {
      elements.taskHint.textContent = '已取消选择。';
      return;
    }

    elements.dataPathInput.value = payload.path || '';
    elements.dataPathInput.dataset.type = payload.type || '';
    elements.taskHint.textContent = payload.type === 'directory'
      ? '已选择数据文件夹。'
      : '已选择数据文件。';
  } catch (error) {
    elements.taskHint.textContent = error.message || '选择数据失败。';
    addSystemMessage(elements.taskHint.textContent, 'warning');
  } finally {
    setTaskCreationEnabled(true);
  }
}

function regeneratePlan() {
  if (!sendMessage({ type: 'regenerate_plan' })) {
    return;
  }

  state.planEditorDirty = false;
  setTaskPhase('plan', {
    plan: '正在重新生成'
  });
  setPlanControlsEnabled(false);
  setActivity('Queued', 'pending');
}

function approvePlan() {
  const planText = elements.planEditor.value.trim();

  if (!planText) {
    addSystemMessage('确认计划不能为空。', 'warning');
    return;
  }

  if (!sendMessage({ type: 'approve_plan', planText })) {
    return;
  }

  state.planEditorDirty = false;
  setTaskPhase('modeling', {
    modeling: '正在执行'
  });
  setPlanControlsEnabled(false);
  setActivity('Queued', 'pending');
}

function restoreHistory(entries) {
  if (!Array.isArray(entries) || entries.length === 0) {
    return;
  }

  for (const entry of entries) {
    if (!entry || typeof entry !== 'object') {
      continue;
    }

    if (entry.type === 'message') {
      if (entry.role === 'user') {
        addUserMessage(entry.text || '', entry.timestamp);
      } else if (entry.role === 'assistant') {
        addAssistantMessage(entry.text || '', entry.timestamp);
      }
      continue;
    }

    if (entry.type === 'working') {
      addHistoryWorkingBlock(entry);
    }
  }

  if (!state.replaying) {
    addSystemMessage('已恢复上一次 Codex 会话历史。', 'success');
  }
}

function resetConversationForReplay() {
  finishAssistantMessage();
  finishWorkingBlock();
  state.activeWorkingBlock = null;
  state.activeWorkingBody = null;
  state.activeWorkingContent = null;
  state.activeWorkingStartedAt = null;
  state.currentTurnStartedAt = null;
  state.outputBuffer = '';
  state.pendingAssistantText = '';
  state.streamingMessage = null;
  state.toolBlocks.clear();
  elements.conversation.innerHTML = '';
}

function finishInterruptedWorkingBlock(title = 'Interrupted', durationMs) {
  if (!state.activeWorkingBlock && state.runState !== 'running') {
    return;
  }

  flushPendingAssistantMessage();
  finishAssistantMessage();
  finishWorkingBlock(durationMs, {
    title,
    interrupted: true
  });
  state.currentTurnStartedAt = null;
  state.runState = 'idle';
}

function isInterruptedActivity(activity) {
  if (!activity || typeof activity !== 'object') {
    return false;
  }

  return activity.label === 'Interrupted' || activity.status === 'offline';
}

function durationUntilTimestamp(timestamp) {
  if (
    typeof timestamp !== 'number' ||
    !state.activeWorkingStartedAt ||
    timestamp < state.activeWorkingStartedAt
  ) {
    return undefined;
  }

  return timestamp - state.activeWorkingStartedAt;
}

function sendMessage(payload) {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
    addSystemMessage('当前未连接 Codex 会话。', 'warning');
    return false;
  }

  state.socket.send(JSON.stringify(payload));
  return true;
}

function interruptSession() {
  if (sendMessage({ type: 'interrupt' })) {
    movePendingAssistantToWorking();
    finishInterruptedWorkingBlock('Interrupted');
    state.resumeInProgress = false;
    setActivity('Interrupted', 'pending');
    addSystemMessage('已发送停止信号。', 'warning');
  }
}

function restartSession() {
  flushOutput();
  flushPendingAssistantMessage();
  finishAssistantMessage();
  finishWorkingBlock();
  state.runState = 'idle';
  state.taskPhase = 'idle';
  state.planEditorDirty = false;
  state.resumeInProgress = false;
  elements.planPanel.hidden = true;
  setPlanExpanded(false);
  setTaskCreationEnabled(true);
  setTaskPhase('idle');
  window.localStorage.removeItem('codexWebConsole.sessionId');

  if (state.socket && state.socket.readyState === WebSocket.OPEN) {
    sendMessage({ type: 'restart' });
    setActivity('Restarting', 'pending');
    addSystemMessage('已重置 Codex 上下文。请选择数据并点击开始创建新任务。', 'warning');
    return;
  }

  connect();
}

function setTaskCreationEnabled(enabled) {
  elements.dataPathInput.disabled = !enabled;
  elements.taskDescriptionInput.disabled = !enabled;
  elements.startTaskButton.disabled = !enabled;
  elements.selectFileButton.disabled = !enabled;
  elements.selectFolderButton.disabled = !enabled;
  elements.resumeTaskButton.disabled = !enabled;
}

function setResumeTaskVisible(visible, workspacePath = '') {
  elements.resumeTaskButton.hidden = !visible;
  state.resumableWorkspacePath = visible ? workspacePath : '';
  if (visible) {
    elements.taskHint.textContent = '当前任务已中断。可以点击继续执行恢复原 Codex thread 和当前工作区。';
  } else if (!elements.dataPathInput.value.trim()) {
    elements.taskHint.textContent = '点击开始后会创建新的任务工作区，并进入需求解析与方案生成。';
  }
}

function setPlanControlsEnabled(enabled) {
  elements.planEditor.disabled = !enabled;
  elements.confirmPlanButton.disabled = !enabled;
  elements.regeneratePlanButton.disabled = !enabled;
  elements.togglePlanButton.disabled = !enabled;
  elements.collapsePlanButton.disabled = !enabled;
}

function setPlanExpanded(expanded) {
  state.planExpanded = expanded;
  elements.planPanel.dataset.expanded = expanded ? 'true' : 'false';
  elements.planEditorWrap.hidden = !expanded;
  elements.collapsePlanButton.hidden = !expanded;
  elements.togglePlanButton.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  const icon = elements.togglePlanButton.querySelector('i');
  if (icon) {
    icon.setAttribute('data-lucide', expanded ? 'chevron-down' : 'chevron-right');
    refreshIcons();
  }
}

function setTaskPhase(phase, details = {}) {
  state.taskPhase = phase;
  const activeIndex = phaseOrder.indexOf(phase);
  const phaseSteps = elements.phasePanel.querySelectorAll('.phase-step');

  for (const step of phaseSteps) {
    const index = phaseOrder.indexOf(step.dataset.phase);
    if (activeIndex === -1 || index === -1) {
      step.dataset.status = 'pending';
    } else if (index < activeIndex) {
      step.dataset.status = 'done';
    } else if (index === activeIndex) {
      step.dataset.status = 'active';
    } else {
      step.dataset.status = 'pending';
    }

    const detail = step.querySelector('small');
    if (detail) {
      const status = step.dataset.status || 'pending';
      detail.textContent = details[step.dataset.phase] || phaseStatusText[status] || '';
    }
  }
}

function resetPhaseDetails() {
  const phaseSteps = elements.phasePanel.querySelectorAll('.phase-step');
  for (const step of phaseSteps) {
    const detail = step.querySelector('small');
    if (detail) {
      detail.textContent = phaseStatusText.pending;
    }
  }
}

function bindEvents() {
  elements.startTaskButton.addEventListener('click', startTask);
  elements.resumeTaskButton.addEventListener('click', resumeTask);
  elements.selectFileButton.addEventListener('click', () => selectDataPath('file'));
  elements.selectFolderButton.addEventListener('click', () => selectDataPath('directory'));
  elements.regeneratePlanButton.addEventListener('click', regeneratePlan);
  elements.confirmPlanButton.addEventListener('click', approvePlan);
  elements.togglePlanButton.addEventListener('click', () => setPlanExpanded(!state.planExpanded));
  elements.collapsePlanButton.addEventListener('click', () => setPlanExpanded(false));
  elements.taskDescriptionInput.addEventListener('input', resizeComposer);
  elements.planEditor.addEventListener('input', () => {
    state.planEditorDirty = true;
  });
  elements.interruptButton.addEventListener('click', interruptSession);
  elements.restartButton.addEventListener('click', restartSession);
}

refreshIcons();
bindEvents();
setTaskPhase('idle');
setComposerEnabled(false);
setPlanControlsEnabled(false);
connect();
