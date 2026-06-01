export function shouldPersistEvent(payload) {
  if (isInternalAi4mlUserMessage(payload)) {
    return false;
  }

  return ![
    'heartbeat',
    'session',
    'replay_start',
    'replay_done',
    'raw',
    'history_restored',
    'history_restore_failed'
  ].includes(payload.type);
}

export function compactReplayEvents(events, options = {}) {
  const requestedTaskId = typeof options.taskId === 'string' && options.taskId.trim()
    ? options.taskId.trim()
    : undefined;
  const lastTaskStarted = findLastTaskStartedEvent(events, requestedTaskId);
  const replayEvents = lastTaskStarted
    ? events.slice(lastTaskStarted.index).filter((event) => isSameTaskReplayEvent(event, lastTaskStarted.taskId))
    : events;
  const compacted = [];
  const assistantTextByItemId = new Map();
  const workingTextByItemId = new Map();
  const toolById = new Map();
  const toolOrder = [];

  const flushAssistant = (itemId, fallbackEvent) => {
    if (!assistantTextByItemId.has(itemId)) {
      return;
    }
    const current = assistantTextByItemId.get(itemId);
    if (current && current.text.trim()) {
      compacted.push({
        type: 'assistant_snapshot',
        itemId,
        text: current.text,
        timestamp: current.timestamp
      });
    }
    assistantTextByItemId.delete(itemId);
    if (fallbackEvent?.type === 'assistant_done') {
      compacted.push(fallbackEvent);
    }
  };

  const flushWorking = (itemId, fallbackEvent) => {
    if (!workingTextByItemId.has(itemId)) {
      return;
    }
    const current = workingTextByItemId.get(itemId);
    compacted.push({
      type: 'working_snapshot',
      itemId,
      title: current.title || 'Working',
      text: current.text,
      startedAt: current.startedAt,
      completedAt: current.completedAt || fallbackEvent?.completedAt,
      timestamp: current.timestamp
    });
    workingTextByItemId.delete(itemId);
  };

  const flushTools = () => {
    for (const toolUseId of toolOrder) {
      const tool = toolById.get(toolUseId);
      if (!tool) {
        continue;
      }
      compacted.push({
        type: 'tool_snapshot',
        toolUseId,
        tool: tool.tool,
        title: tool.title || '工具事件',
        command: tool.command || '',
        cwd: tool.cwd || '',
        stdout: tool.stdout || '',
        stderr: tool.stderr || '',
        status: tool.status || '',
        exitCode: tool.exitCode,
        durationMs: tool.durationMs,
        startedAt: tool.startedAt,
        completedAt: tool.completedAt,
        timestamp: tool.completedAt || tool.startedAt || tool.timestamp
      });
    }
    toolById.clear();
    toolOrder.length = 0;
  };

  for (const event of replayEvents) {
    if (!event || typeof event !== 'object') {
      continue;
    }

    if (event.type === 'assistant_delta') {
      const itemId = typeof event.itemId === 'string' ? event.itemId : 'assistant';
      const current = assistantTextByItemId.get(itemId) || { text: '', timestamp: event.timestamp };
      current.text += typeof event.data === 'string' ? event.data : '';
      current.timestamp = event.timestamp || current.timestamp;
      assistantTextByItemId.set(itemId, current);
      continue;
    }

    if (event.type === 'assistant_done') {
      const itemId = typeof event.itemId === 'string' ? event.itemId : 'assistant';
      flushAssistant(itemId, event);
      continue;
    }

    if (event.type === 'working_start') {
      const itemId = typeof event.itemId === 'string' ? event.itemId : `working:${event.startedAt || Date.now()}`;
      workingTextByItemId.set(itemId, {
        title: event.title,
        text: '',
        startedAt: event.startedAt,
        timestamp: event.timestamp || event.startedAt
      });
      continue;
    }

    if (event.type === 'working_delta') {
      const itemId = typeof event.itemId === 'string' ? event.itemId : 'working';
      const current = workingTextByItemId.get(itemId) || { text: '', timestamp: event.timestamp };
      current.text += typeof event.data === 'string' ? event.data : '';
      current.timestamp = event.timestamp || current.timestamp;
      workingTextByItemId.set(itemId, current);
      continue;
    }

    if (event.type === 'working_done') {
      const itemId = typeof event.itemId === 'string' ? event.itemId : 'working';
      flushWorking(itemId, event);
      continue;
    }

    if (event.type === 'tool_start' || event.type === 'tool_output' || event.type === 'tool_result') {
      const toolUseId = typeof event.toolUseId === 'string' ? event.toolUseId : `tool:${event.startedAt || event.completedAt || Date.now()}`;
      if (!toolById.has(toolUseId)) {
        toolById.set(toolUseId, {});
        toolOrder.push(toolUseId);
      }
      const tool = toolById.get(toolUseId);
      tool.tool = event.tool || tool.tool || '';
      tool.title = event.title || tool.title;
      tool.command = event.command || tool.command || '';
      tool.cwd = event.cwd || tool.cwd || '';
      tool.startedAt = event.startedAt || tool.startedAt;
      tool.completedAt = event.completedAt || tool.completedAt;
      tool.timestamp = event.timestamp || tool.timestamp;
      if (event.type === 'tool_output') {
        if (event.stream === 'stderr') {
          tool.stderr = `${tool.stderr || ''}${event.data || ''}`;
        } else {
          tool.stdout = `${tool.stdout || ''}${event.data || ''}`;
        }
      }
      if (event.type === 'tool_result') {
        tool.stdout = event.stdout || tool.stdout || event.output || '';
        tool.stderr = event.stderr || tool.stderr || '';
        tool.status = event.status || tool.status || '';
        tool.exitCode = event.exitCode;
        tool.durationMs = event.durationMs;
      }
      continue;
    }

    flushTools();
    compacted.push(event);
  }

  for (const itemId of [...assistantTextByItemId.keys()]) {
    flushAssistant(itemId);
  }
  for (const itemId of [...workingTextByItemId.keys()]) {
    flushWorking(itemId);
  }
  flushTools();

  return compacted;
}

function findLastTaskStartedEvent(events, requestedTaskId) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event?.type !== 'task_session_started') {
      continue;
    }

    const taskId = typeof event.taskId === 'string' && event.taskId.trim()
      ? event.taskId.trim()
      : undefined;
    if (requestedTaskId && taskId && taskId !== requestedTaskId) {
      continue;
    }
    return {
      index,
      taskId
    };
  }

  return null;
}

function isSameTaskReplayEvent(event, taskId) {
  if (!taskId || !event || typeof event !== 'object') {
    return true;
  }

  const eventTaskId = typeof event.taskId === 'string' && event.taskId.trim()
    ? event.taskId.trim()
    : undefined;
  return !eventTaskId || eventTaskId === taskId;
}

export function isInternalAi4mlUserMessage(payload) {
  return payload
    && payload.type === 'user_message'
    && typeof payload.text === 'string'
    && payload.text.trimStart().startsWith('#AI4ML_');
}

export function hasUnclosedTurn(events) {
  let running = false;

  for (const event of events) {
    if (event.type === 'turn_started') {
      running = true;
      continue;
    }

    if ([
      'turn_completed',
      'turn_interrupted',
      'exit',
      'error'
    ].includes(event.type)) {
      running = false;
    }
  }

  return running;
}

export function interruptionReasonForPayload(payload) {
  if (payload.type === 'exit') {
    const exitCode = payload.exitCode === null || payload.exitCode === undefined
      ? 'unknown'
      : payload.exitCode;
    return `Codex app-server 进程已退出，当前任务未正常完成。退出码：${exitCode}。`;
  }

  if (typeof payload.message === 'string' && payload.message.trim()) {
    return `Codex 执行出错，当前任务已中断：${payload.message}`;
  }

  return 'Codex 执行出错，当前任务已中断。';
}

export function safeFileName(value) {
  return String(value).replace(/[^A-Za-z0-9._-]/g, '_');
}
