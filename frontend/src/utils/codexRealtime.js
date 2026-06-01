import { getModelDisplayName } from '@/utils/modelProfile'

const DEFAULT_CODEX_WS_ROOT = '/terminal'
const MAX_EVENTS = 1200
const MAX_TEXT_LENGTH = 24000

export function codexWebSocketUrl(sessionId, options = {}) {
  const root = (import.meta.env.VITE_CODEX_WS_ROOT || DEFAULT_CODEX_WS_ROOT).trim()
  const url = new URL(root, window.location.href)
  url.searchParams.set('sessionId', sessionId)
  if (options.taskId) url.searchParams.set('taskId', options.taskId)
  return url.toString().replace(/^http:/, 'ws:').replace(/^https:/, 'wss:')
}

export function seedCodexRealtimeFromSnapshot(state, codex) {
  if (!codex || !Array.isArray(codex.steps) || codex.steps.length === 0 || state.events.length) return
  const now = Date.now()
  const events = codex.steps.map((step, index) => timelineEvent(
    step.status === 'completed' ? 'report' : step.status === 'failed' ? 'error' : 'modeling',
    step.title || step.id || `AI4ML 步骤 ${index + 1}`,
    step.detail || step.summary || step.message || '',
    {
      ...step,
      timestamp: now + index,
    },
    step.id || `snapshot-step-${index}`,
  ))
  state.events = events.slice(-MAX_EVENTS)
  const latest = codex.progress || {}
  state.activity = {
    type: 'activity',
    status: latest.status === 'running' ? 'busy' : latest.status || codex.status || 'snapshot',
    message: latest.current_activity || latest.summary || '',
  }
  if (state.status === 'idle' || state.status === 'closed' || state.status === 'connecting') {
    state.status = 'snapshot'
  }
}

export function shouldApplyRealtimeTaskPatch(payload, streamStatus) {
  if (!payload || typeof payload !== 'object') return false
  if (streamStatus === 'replaying' || payload.replayed === true) return false
  return [
    'task_completed',
    'plan_generation_completed',
    'task_resume_requested',
    'modeling_started',
    'quota_exhausted',
    'turn_started',
    'activity',
  ].includes(payload.type)
}

export function createCodexRealtimeState() {
  return {
    session: null,
    status: 'idle',
    activity: null,
    events: [],
    assistantItems: new Map(),
    workingItems: new Map(),
    toolItems: new Map(),
  }
}

export function resetCodexRealtimeState(state) {
  state.session = null
  state.status = 'idle'
  state.activity = null
  state.events = []
  state.assistantItems = new Map()
  state.workingItems = new Map()
  state.toolItems = new Map()
}

export function applyCodexRealtimeEvent(state, payload) {
  if (!payload || typeof payload !== 'object') return
  if (payload.type === 'session') {
    state.session = payload
    state.status = 'connected'
    return
  }
  if (payload.type === 'replay_start') {
    state.status = 'replaying'
    return
  }
  if (payload.type === 'replay_done') {
    state.status = payload.running ? 'running' : 'connected'
    return
  }
  if (payload.type === 'activity') {
    state.activity = payload
    return
  }

  const item = normalizeCodexEvent(state, payload)
  if (!item) return
  const next = mergeEvent(state.events, item)
  state.events = next.slice(-MAX_EVENTS)
}

function normalizeCodexEvent(state, payload) {
  const type = payload.type
  const modelName = getModelDisplayName()
  if (type === 'user_message' && typeof payload.text === 'string') {
    const isInternalPrompt = payload.text.trimStart().startsWith('#AI4ML_')
    return timelineEvent(
      isInternalPrompt ? 'prompt' : 'input',
      isInternalPrompt ? `发送给 ${modelName} 的内部指令` : '用户消息',
      payload.text,
      payload,
    )
  }
  if (type === 'task_session_started') {
    return timelineEvent('session', '任务会话已开始', `AI4ML 已把任务提交给 ${modelName}。`, payload)
  }
  if (type === 'task_input_submitted') {
    const description = payload.description ? `任务描述：${payload.description}` : `${modelName} 已收到任务输入。`
    return timelineEvent('input', '任务输入已提交', description, payload)
  }
  if (type === 'workspace_creation_started') {
    return timelineEvent('workspace', '正在创建环境', `${modelName}-native 工作区正在初始化。`, payload)
  }
  if (type === 'workspace_ready') {
    return timelineEvent('workspace', '任务工作区已创建', payload.workspacePath || '', payload)
  }
  if (type === 'requirements_analysis_started') {
    return timelineEvent('requirements', '正在解析需求和数据', `${modelName} 正在读取数据结构和任务描述。`, payload)
  }
  if (type === 'requirements_analysis_completed') {
    return timelineEvent('requirements', '需求解析已完成', `${modelName} 已完成数据结构和需求解析。`, payload)
  }
  if (type === 'plan_generation_started') {
    return timelineEvent('plan', '正在生成工作计划', `${modelName} 正在根据数据和任务描述重新生成计划。`, payload)
  }
  if (type === 'plan_generation_completed') {
    return timelineEvent('approval', '计划已生成', `${modelName} 已生成计划，等待人工确认。`, payload)
  }
  if (type === 'plan_approved') {
    return timelineEvent('approval', '计划已确认', `用户已确认计划，${modelName} 将继续执行建模。`, payload)
  }
  if (type === 'task_resume_requested') {
    return timelineEvent('modeling', '正在恢复中断任务', payload.workspacePath || `${modelName} 正在恢复现有工作区。`, payload)
  }
  if (type === 'modeling_started') {
    return timelineEvent('modeling', '开始执行建模', `${modelName} 已进入训练、验证和交付阶段。`, payload)
  }
  if (type === 'task_completed') {
    return timelineEvent('report', '最终报告已生成', payload.reportPath || payload.workspacePath || '', payload)
  }
  if (type === 'token_usage_updated') {
    const total = payload.total?.totalTokens || payload.total?.total_tokens || 0
    return timelineEvent('usage', '大模型用量已更新', total ? `累计 ${formatNumber(total)} tokens` : '', payload)
  }
  if (type === 'quota_exhausted') {
    return timelineEvent('error', '额度已用完，任务已自动暂停', payload.reason || '', payload)
  }
  if (type === 'turn_started') {
    return timelineEvent('turn', `${modelName} 回合开始`, '', payload, payload.turnId)
  }
  if (type === 'turn_completed') {
    return timelineEvent('turn', `${modelName} 回合完成`, payload.status || '', payload, payload.turnId)
  }
  if (type === 'turn_interrupted') {
    return timelineEvent('error', `${modelName} 回合中断`, payload.reason || '', payload)
  }
  if (type === 'error') {
    return timelineEvent('error', `${modelName} 错误`, payload.message || '', payload)
  }
  if (type === 'assistant_snapshot') {
    const id = payload.itemId || `assistant:${payload.timestamp || Date.now()}`
    const text = truncate(payload.text || '')
    state.assistantItems.set(id, text)
    return {
      id: `assistant:${id}`,
      kind: 'assistant',
      title: `${modelName} 输出`,
      text,
      raw: payload,
      done: true,
      updatedAt: eventTime(payload),
    }
  }
  if (type === 'assistant_delta') {
    const id = payload.itemId || 'assistant'
    const previous = state.assistantItems.get(id) || ''
    const text = truncate(`${previous}${payload.data || ''}`)
    state.assistantItems.set(id, text)
    return {
      id: `assistant:${id}`,
      kind: 'assistant',
      title: `${modelName} 输出`,
      text,
      raw: payload,
      updatedAt: eventTime(payload),
    }
  }
  if (type === 'assistant_done') {
    const id = payload.itemId || 'assistant'
    const text = state.assistantItems.get(id) || ''
    return {
      id: `assistant:${id}`,
      kind: 'assistant',
      title: `${modelName} 输出`,
      text,
      raw: payload,
      done: true,
      updatedAt: eventTime(payload),
    }
  }
  if (type === 'working_start') {
    const id = payload.itemId || `working:${payload.startedAt || Date.now()}`
    state.workingItems.set(id, '')
    return {
      id: `working:${id}`,
      kind: 'working',
      title: payload.title || 'Working',
      text: '',
      raw: payload,
      updatedAt: eventTime(payload),
    }
  }
  if (type === 'working_snapshot') {
    const id = payload.itemId || `working:${payload.startedAt || payload.timestamp || Date.now()}`
    const text = truncate(payload.text || '')
    state.workingItems.set(id, text)
    return {
      id: `working:${id}`,
      kind: 'working',
      title: payload.title || 'Working',
      text,
      raw: payload,
      done: true,
      updatedAt: eventTime(payload),
    }
  }
  if (type === 'working_delta') {
    const id = payload.itemId || 'working'
    const previous = state.workingItems.get(id) || ''
    const text = truncate(`${previous}${payload.data || ''}`)
    state.workingItems.set(id, text)
    return {
      id: `working:${id}`,
      kind: 'working',
      title: 'Working',
      text,
      raw: payload,
      updatedAt: eventTime(payload),
    }
  }
  if (type === 'working_done') {
    const id = payload.itemId || 'working'
    return {
      id: `working:${id}`,
      kind: 'working',
      title: 'Working',
      text: state.workingItems.get(id) || '',
      raw: payload,
      done: true,
      updatedAt: eventTime(payload),
    }
  }
  if (type === 'tool_start') {
    const id = payload.toolUseId || `tool:${payload.startedAt || Date.now()}`
    const tool = {
      command: payload.command || '',
      cwd: payload.cwd || '',
      stdout: '',
      stderr: '',
    }
    state.toolItems.set(id, tool)
    return toolEvent(id, payload.title || '运行工具', tool, payload)
  }
  if (type === 'tool_snapshot') {
    const id = payload.toolUseId || `tool:${payload.startedAt || payload.timestamp || Date.now()}`
    const tool = {
      command: payload.command || '',
      cwd: payload.cwd || '',
      stdout: payload.stdout || '',
      stderr: payload.stderr || '',
      status: payload.status,
      exitCode: payload.exitCode,
      durationMs: payload.durationMs,
    }
    state.toolItems.set(id, tool)
    return toolEvent(id, payload.title || '工具事件', tool, payload, true)
  }
  if (type === 'tool_output') {
    const id = payload.toolUseId || 'tool'
    const tool = state.toolItems.get(id) || { command: '', cwd: '', stdout: '', stderr: '' }
    if (payload.stream === 'stderr') tool.stderr = truncate(`${tool.stderr}${payload.data || ''}`)
    else tool.stdout = truncate(`${tool.stdout}${payload.data || ''}`)
    state.toolItems.set(id, tool)
    return toolEvent(id, '命令输出', tool, payload)
  }
  if (type === 'tool_result') {
    const id = payload.toolUseId || 'tool'
    const tool = state.toolItems.get(id) || {}
    const merged = {
      ...tool,
      command: payload.command || tool.command || '',
      cwd: payload.cwd || tool.cwd || '',
      stdout: payload.stdout || tool.stdout || payload.output || '',
      stderr: payload.stderr || tool.stderr || '',
      exitCode: payload.exitCode,
      status: payload.status,
      durationMs: payload.durationMs,
    }
    state.toolItems.set(id, merged)
    return toolEvent(id, payload.title || '工具完成', merged, payload, true)
  }
  if (type === 'history_restored' && Array.isArray(payload.entries)) {
    return timelineEvent('history', '历史会话已恢复', `已恢复 ${payload.entries.length} 条历史记录。`, payload)
  }
  return null
}

function timelineEvent(kind, title, text, raw, id = '') {
  return {
    id: `${kind}:${id || raw.timestamp || raw.startedAt || raw.completedAt || Date.now()}:${title}`,
    kind,
    title,
    text,
    raw,
    updatedAt: eventTime(raw),
  }
}

function toolEvent(id, title, tool, raw, done = false) {
  return {
    id: `tool:${id}`,
    kind: tool.status === 'failed' || tool.exitCode ? 'error' : 'tool',
    tool: raw.tool || tool.tool || '',
    title,
    command: tool.command || '',
    cwd: tool.cwd || '',
    stdout: truncate(tool.stdout || ''),
    stderr: truncate(tool.stderr || ''),
    status: tool.status || '',
    exitCode: tool.exitCode,
    durationMs: tool.durationMs,
    raw,
    done,
    updatedAt: eventTime(raw),
  }
}

function mergeEvent(events, item) {
  const index = events.findIndex((event) => event.id === item.id)
  if (index < 0) return [...events, item]
  return [
    ...events.slice(0, index),
    { ...events[index], ...item },
    ...events.slice(index + 1),
  ]
}

function eventTime(payload) {
  const value = payload.completedAt || payload.startedAt || payload.timestamp
  if (typeof value === 'number') return value
  return Date.now()
}

function truncate(value) {
  const text = String(value || '')
  if (text.length <= MAX_TEXT_LENGTH) return text
  return text.slice(text.length - MAX_TEXT_LENGTH)
}

function formatNumber(value) {
  return new Intl.NumberFormat('zh-CN').format(Number(value || 0))
}
