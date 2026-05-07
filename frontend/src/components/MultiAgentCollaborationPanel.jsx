import { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api.js";
import { getCachedCollaborationSnapshot, setCachedCollaborationSnapshot } from "../lib/collaborationCache.js";

const AGENT_DEFINITIONS = [
  {
    id: "requirement_analysis",
    name: "Agent-Alpha",
    role: "需求解析",
    shortRole: "需求",
    description: "理解业务目标，整理任务约束与输出要求。",
    x: 10,
    y: 45,
  },
  {
    id: "data_analysis",
    name: "Agent-Beta",
    role: "数据分析",
    shortRole: "数据",
    description: "检查 CSV 字段、目标列、缺失值与任务类型。",
    x: 27,
    y: 24,
  },
  {
    id: "feature_engineering",
    name: "Agent-Gamma",
    role: "特征工程",
    shortRole: "特征",
    description: "生成数据处理与训练前特征逻辑。",
    x: 45,
    y: 57,
  },
  {
    id: "model_selection",
    name: "Agent-Delta",
    role: "模型选择",
    shortRole: "模型",
    description: "选择 AutoGluon 候选模型并组织比较策略。",
    x: 62,
    y: 30,
  },
  {
    id: "training_validation",
    name: "Agent-Epsilon",
    role: "训练验证",
    shortRole: "训练",
    description: "执行训练、验证、错误修复和 leaderboard 落盘。",
    x: 76,
    y: 62,
  },
  {
    id: "report_generation",
    name: "Agent-Zeta",
    role: "报告生成",
    shortRole: "报告",
    description: "汇总指标、产物、报告快照和在线预测入口。",
    x: 90,
    y: 44,
  },
];

const AGENT_LINKS = [
  ["requirement_analysis", "data_analysis", "任务语义"],
  ["data_analysis", "feature_engineering", "数据画像"],
  ["feature_engineering", "model_selection", "特征逻辑"],
  ["model_selection", "training_validation", "候选方案"],
  ["training_validation", "report_generation", "结果产物"],
  ["data_analysis", "model_selection", "目标与指标"],
  ["requirement_analysis", "feature_engineering", "业务约束"],
];

const STATUS_LABELS = {
  pending: "待命",
  running: "执行中",
  waiting_human: "等待人工",
  completed: "已完成",
  failed: "失败",
};

const TASK_STATUS_LABELS = {
  draft: "草稿",
  uploaded: "已上传",
  planning: "规划中",
  paused_for_review: "等待复核",
  waiting_human: "等待人工",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  published: "已发布",
};

const RUNTIME_MODE_LABELS = {
  persistent_agent_runtime: "持久化 Agent Runtime",
  stage_agent_orchestrator: "阶段快照兼容模式",
};

const EVENT_KIND_LABELS = {
  agent: "Agent Runtime",
  stage: "阶段事件",
  human_request: "人工节点",
};

const MESSAGE_TYPE_LABELS = {
  coordination: "协作安排",
  handoff: "阶段交接",
  acknowledgement: "接收确认",
  blocker: "阻塞通知",
  human_review: "人工节点",
  result: "结果广播",
};

function formatDateTime(value) {
  if (!value) return "暂无";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function formatDuration(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "暂无";
  if (value < 1) return `${Math.round(value * 1000)} ms`;
  if (value < 60) return `${value.toFixed(1)} s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}m ${seconds}s`;
}

function compactIdentifier(value) {
  if (!value) return "未记录";
  const text = String(value);
  return text.length > 34 ? `${text.slice(0, 18)}...${text.slice(-10)}` : text;
}

function getAgentTone(status) {
  if (status === "completed") return "success";
  if (status === "running") return "running";
  if (status === "waiting_human") return "waiting";
  if (status === "failed") return "failed";
  return "pending";
}

function getProgress(status) {
  if (status === "completed") return 100;
  if (status === "running") return 62;
  if (status === "waiting_human") return 48;
  if (status === "failed") return 100;
  return 0;
}

function normalizeArtifactCount(value) {
  if (!value) return 0;
  if (Array.isArray(value)) return value.length;
  if (typeof value === "string") return value ? 1 : 0;
  if (typeof value === "object") {
    return Object.values(value).reduce((count, item) => {
      if (Array.isArray(item)) return count + item.length;
      return item ? count + 1 : count;
    }, 0);
  }
  return 0;
}

function buildAgents(stages, requests) {
  const stagesByKey = new Map((stages ?? []).map((stage) => [stage.stage, stage]));
  const openRequests = new Set(
    (requests ?? [])
      .filter((request) => ["pending", "open"].includes(request.status))
      .map((request) => request.stage),
  );

  return AGENT_DEFINITIONS.map((agent) => {
    const stage = stagesByKey.get(agent.id);
    const status = openRequests.has(agent.id) ? "waiting_human" : stage?.status ?? "pending";
    return {
      ...agent,
      stage,
      status,
      tone: getAgentTone(status),
      progress: getProgress(status),
      currentTask: stage?.summary || agent.description,
      modelName: stage?.model_name || "未指定",
      connector: stage?.selected_connector_id || "未指定",
      selectionSource: stage?.selection_source || "未记录",
      artifactCount: normalizeArtifactCount(stage?.artifact_refs),
      lastActionAt: stage?.updated_at || stage?.finished_at || stage?.started_at,
    };
  });
}

function buildEvents(agents, requests) {
  const stageEvents = agents
    .filter((agent) => agent.stage)
    .map((agent) => ({
      id: `stage-${agent.id}-${agent.stage.updated_at || agent.stage.created_at}`,
      time: agent.stage.updated_at || agent.stage.created_at,
      text: `${agent.name}（${agent.role}）${STATUS_LABELS[agent.status] ?? agent.status}：${agent.currentTask}`,
      tone: agent.tone,
    }));
  const requestEvents = (requests ?? []).map((request) => ({
    id: `request-${request.id}`,
    time: request.updated_at || request.created_at,
    text: `人工节点 ${request.payload?.title || request.stage} 当前状态：${request.status}`,
    tone: "waiting",
  }));
  return [...stageEvents, ...requestEvents]
    .sort((left, right) => new Date(right.time || 0).getTime() - new Date(left.time || 0).getTime())
    .slice(0, 12);
}

function buildAgentsFromSnapshot(snapshot, stages, requests) {
  if (!Array.isArray(snapshot?.agents)) return [];
  return snapshot.agents.map((agent) => {
    const definition = AGENT_DEFINITIONS.find((item) => item.id === agent.id) ?? {};
    const status = agent.status ?? "pending";
    return {
      id: agent.id,
      name: agent.name ?? definition.name ?? agent.id,
      role: agent.role ?? definition.role ?? agent.stage,
      shortRole: agent.short_role ?? definition.shortRole ?? agent.role ?? "Agent",
      description: definition.description ?? "",
      x: typeof agent.x === "number" ? agent.x : definition.x ?? 0,
      y: typeof agent.y === "number" ? agent.y : definition.y ?? 0,
      stage: stages.find((stage) => stage.stage === agent.stage) ?? null,
      status,
      tone: getAgentTone(status),
      progress: typeof agent.progress === "number" ? agent.progress : getProgress(status),
      currentTask: agent.current_task ?? definition.description ?? "",
      modelName: agent.model_name || "未指定",
      connector: agent.connector_id || "未指定",
      selectionSource: agent.selection_source || "未记录",
      artifactCount: typeof agent.artifact_count === "number" ? agent.artifact_count : normalizeArtifactCount(agent.artifact_refs),
      artifactRefs: Array.isArray(agent.artifact_refs) ? agent.artifact_refs : [],
      lastActionAt: agent.last_action_at,
      runtimeId: agent.runtime_id ?? null,
      runtimeSource: agent.runtime_source ?? "stage_record_projection",
      workerId: agent.worker_id ?? null,
      startedAt: agent.started_at ?? null,
      finishedAt: agent.finished_at ?? null,
      durationSeconds: agent.duration_seconds ?? null,
      logExcerpt: agent.log_excerpt ?? "",
    };
  });
}

function buildEventsFromSnapshot(snapshot, agents, requests) {
  if (!Array.isArray(snapshot?.events)) return [];
  return snapshot.events.map((event) => ({
    id: event.id,
    time: event.time,
    text: event.text,
    kind: event.kind ?? "stage",
    status: event.status ?? "",
    artifactRefs: Array.isArray(event.artifact_refs) ? event.artifact_refs : [],
    tone: event.kind === "human_request" ? "waiting" : getAgentTone(event.status),
  }));
}

function buildMessagesFromSnapshot(snapshot) {
  if (!Array.isArray(snapshot?.messages)) return [];
  return snapshot.messages.map((message) => ({
    id: message.id,
    time: message.time,
    fromAgentId: message.from_agent_id,
    toAgentId: message.to_agent_id,
    type: message.message_type ?? "coordination",
    status: message.status ?? "sent",
    content: message.content ?? "",
    artifactRefs: Array.isArray(message.artifact_refs) ? message.artifact_refs : [],
    fromAgentName: message.payload?.from_agent_name,
    fromAgentRole: message.payload?.from_agent_role,
    toAgentName: message.payload?.to_agent_name,
    toAgentRole: message.payload?.to_agent_role,
  }));
}

function getAgentDisplayName(agentId, agents) {
  const agent = agents.find((item) => item.id === agentId);
  return agent?.name ?? agentId ?? "全体";
}

function isAgentSnapshot(payload) {
  return Boolean(payload) && Array.isArray(payload.agents) && Array.isArray(payload.events);
}

export default function MultiAgentCollaborationPanel({
  tasks,
  tasksLoading,
  selectedTask,
  requestContext,
  onSelectTask,
  onOpenWorkflow,
  onOpenHumanCollaboration,
}) {
  const [snapshot, setSnapshot] = useState(null);
  const [state, setState] = useState("idle");
  const [error, setError] = useState("");

  const stages = useMemo(() => (Array.isArray(snapshot?.stages) ? snapshot.stages : []), [snapshot]);
  const requests = useMemo(() => (Array.isArray(snapshot?.requests) ? snapshot.requests : []), [snapshot]);
  const agents = useMemo(() => buildAgentsFromSnapshot(snapshot, stages, requests), [snapshot, stages, requests]);
  const events = useMemo(() => buildEventsFromSnapshot(snapshot, agents, requests), [snapshot, agents, requests]);
  const messages = useMemo(() => buildMessagesFromSnapshot(snapshot), [snapshot]);

  const completedCount = agents.filter((agent) => agent.status === "completed").length;
  const activeCount = agents.filter((agent) => ["running", "waiting_human"].includes(agent.status)).length;
  const artifactCount = agents.reduce((count, agent) => count + agent.artifactCount, 0);
  const messageCount = messages.length;
  const isPersistentRuntime = snapshot?.runtime_mode === "persistent_agent_runtime";
  const runtimeModeLabel = RUNTIME_MODE_LABELS[snapshot?.runtime_mode] ?? "未读取";
  const persistentAgentCount = agents.filter((agent) => agent.runtimeSource === "persistent_agent_runtime").length;

  useEffect(() => {
    if (!selectedTask?.id || !requestContext?.accessToken || !requestContext?.teamId) {
      setSnapshot(null);
      setState("idle");
      setError("");
      return;
    }
    let active = true;
    const cachedPayload = getCachedCollaborationSnapshot(selectedTask.id, requestContext.teamId);
    const cached = isAgentSnapshot(cachedPayload) ? cachedPayload : null;
    if (cached) setSnapshot(cached);
    setState(cached ? "ready" : "loading");
    setError("");
    api.taskAgentCollaboration(selectedTask.id, requestContext)
      .then((payload) => {
        if (!active) return;
        if (!isAgentSnapshot(payload)) throw new Error("后端 Agent 快照缺少 agents/events 字段。");
        setCachedCollaborationSnapshot(selectedTask.id, requestContext.teamId, payload);
        setSnapshot(payload);
        setState("ready");
      })
      .catch((loadError) => {
        if (!active) return;
        setSnapshot(null);
        setState("ready");
        setError(loadError instanceof Error ? loadError.message : String(loadError));
      });
    return () => {
      active = false;
    };
  }, [requestContext, selectedTask?.id]);

  async function handleRefresh() {
    if (!selectedTask?.id) return;
    setState("loading");
    setError("");
    try {
      const payload = await api.taskAgentCollaboration(selectedTask.id, { ...requestContext, noCache: true });
      if (!isAgentSnapshot(payload)) throw new Error("后端 Agent 快照缺少 agents/events 字段。");
      setCachedCollaborationSnapshot(selectedTask.id, requestContext.teamId, payload);
      setSnapshot(payload);
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : String(refreshError));
    } finally {
      setState("ready");
    }
  }

  return (
    <div className="multi-agent-console">
      <section className="section-card agent-toolbar-card">
        <div className="section-head">
          <div>
            <h3>任务上下文</h3>
            <p>选择一个任务后，下面的 Agent 状态会读取后端持久化 Agent Runtime 与事件流。</p>
          </div>
          <div className="agent-toolbar-actions">
            {tasks?.length ? (
              <label className="agent-task-select">
                <span>当前任务</span>
                <select value={selectedTask?.id ?? ""} onChange={(event) => onSelectTask?.(event.target.value)}>
                  {tasks.map((task) => (
                    <option key={task.id} value={task.id}>
                      {task.name} / {TASK_STATUS_LABELS[task.status] ?? task.status}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <button type="button" className="chip-button" onClick={handleRefresh} disabled={!selectedTask?.id || state === "loading"}>
              {state === "loading" ? "同步中..." : "同步状态"}
            </button>
          </div>
        </div>
        {!tasks?.length && !tasksLoading ? <div className="empty-state compact">当前还没有任务。</div> : null}
      </section>

      <section className="section-card agent-graph-card">
        <div className="section-head">
          <div>
            <p className="eyebrow">Agent Collaboration</p>
            <h3>多 Agent 协同拓扑</h3>
            <p>节点代表 AI4ML 工作流中的 6 个后端 Agent Runtime，连线代表阶段产物和决策流向。</p>
          </div>
          <div className="agent-console-actions">
            {selectedTask ? <span className="runtime-pill info">{selectedTask.name}</span> : null}
            {selectedTask ? (
              <span className={`runtime-pill ${isPersistentRuntime ? "success" : "warning"}`}>
                运行模式：{runtimeModeLabel}
              </span>
            ) : null}
            <button type="button" className="ghost-button" onClick={() => onOpenWorkflow?.()}>
              阶段详情
            </button>
          </div>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}
        {!selectedTask ? <div className="empty-state">先选择一个任务，再查看 Agent 协同状态。</div> : null}

        {selectedTask ? (
          <>
            <div className="agent-graph-summary">
              <article><span>Agent 数</span><strong>{agents.length}</strong></article>
              <article><span>已完成</span><strong>{completedCount}</strong></article>
              <article><span>活跃/等待</span><strong>{activeCount}</strong></article>
              <article><span>持久化 Runtime</span><strong>{persistentAgentCount}</strong></article>
              <article><span>关键产物</span><strong>{artifactCount}</strong></article>
              <article><span>Agent 通信</span><strong>{messageCount}</strong></article>
            </div>

            <div className="agent-network">
              <svg className="agent-link-layer" viewBox="0 0 100 76" preserveAspectRatio="none" aria-hidden="true">
                <defs>
                  <marker id="agent-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="4" markerHeight="4" orient="auto">
                    <path d="M 0 0 L 8 4 L 0 8 z" />
                  </marker>
                </defs>
                {AGENT_LINKS.map(([fromId, toId], index) => {
                  const from = agents.find((agent) => agent.id === fromId);
                  const to = agents.find((agent) => agent.id === toId);
                  if (!from || !to) return null;
                  const midX = (from.x + to.x) / 2;
                  const midY = (from.y + to.y) / 2 - (index % 2 === 0 ? 7 : -5);
                  return (
                    <g key={`${fromId}-${toId}`}>
                      <path
                        className={`agent-link ${from.status === "completed" ? "completed" : ""}`}
                        d={`M ${from.x + 3.5} ${from.y} Q ${midX} ${midY} ${to.x - 3.5} ${to.y}`}
                        markerEnd="url(#agent-arrow)"
                      />
                    </g>
                  );
                })}
              </svg>
              {agents.map((agent) => (
                <article
                  key={agent.id}
                  className={`agent-node ${agent.tone}`}
                  style={{ left: `${agent.x}%`, top: `${agent.y}%` }}
                >
                  <span className="agent-node-icon">{agent.shortRole}</span>
                  <strong>{agent.name}</strong>
                  <em>{agent.role}</em>
                  <small>{STATUS_LABELS[agent.status] ?? agent.status}</small>
                </article>
              ))}
            </div>
          </>
        ) : null}
      </section>

      <div className="agent-bottom-grid">
        <section className="section-card agent-status-card">
          <div className="section-head">
            <div>
              <h3>Agent 运行状态</h3>
              <p>进度、模型、连接器、Runtime 标识、耗时和产物都来自后端持久化记录。</p>
            </div>
            {selectedTask ? (
              <button type="button" className="primary-button" onClick={() => onOpenHumanCollaboration?.(selectedTask.id)}>
                处理人工节点
              </button>
            ) : null}
          </div>

          <div className="table-wrap agent-status-table">
            <table>
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>角色</th>
                  <th>当前工作</th>
                  <th>进度</th>
                  <th>模型</th>
                  <th>Runtime</th>
                  <th>耗时</th>
                  <th>最后更新</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((agent) => (
                  <tr key={agent.id}>
                    <td><span className={`agent-dot ${agent.tone}`} />{agent.name}</td>
                    <td>{agent.role}</td>
                    <td>
                      <div className="agent-task-cell">
                        <span>{agent.currentTask}</span>
                        {agent.logExcerpt ? <small>日志：{agent.logExcerpt}</small> : null}
                      </div>
                    </td>
                    <td>
                      <div className="agent-progress-cell">
                        <span className={`agent-progress-bar ${agent.tone}`} style={{ width: `${agent.progress}%` }} />
                      </div>
                      <small>{agent.progress}%</small>
                    </td>
                    <td>{agent.modelName}</td>
                    <td>
                      <div className="agent-runtime-cell">
                        <strong>{agent.runtimeSource === "persistent_agent_runtime" ? "持久化" : "阶段投影"}</strong>
                        <small title={agent.workerId || agent.runtimeId || ""}>{compactIdentifier(agent.workerId || agent.runtimeId)}</small>
                      </div>
                    </td>
                    <td>
                      <div className="agent-runtime-cell">
                        <strong>{formatDuration(agent.durationSeconds)}</strong>
                        <small>开始：{formatDateTime(agent.startedAt)}</small>
                      </div>
                    </td>
                    <td>{formatDateTime(agent.lastActionAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="section-card agent-event-card">
          <div className="section-head">
            <div>
              <h3>实时日志</h3>
              <p>按更新时间展示后端 Agent Runtime 事件、阶段事件和人工协同事件。</p>
            </div>
          </div>
          {!events.length ? <div className="empty-state compact">当前任务还没有可展示的 Agent 事件。</div> : null}
          {events.length ? (
            <div className="agent-event-list">
              {events.map((event) => (
                <article key={event.id} className={`agent-event ${event.tone}`}>
                  <span>
                    {formatDateTime(event.time)}
                    <em>{EVENT_KIND_LABELS[event.kind] ?? event.kind}</em>
                    {event.artifactRefs.length ? <em>{event.artifactRefs.length} 个产物</em> : null}
                  </span>
                  <p>{event.text}</p>
                </article>
              ))}
            </div>
          ) : null}
        </section>
      </div>

      <section className="section-card agent-message-card">
        <div className="section-head">
          <div>
            <h3>Agent 讨论流</h3>
            <p>展示后端在阶段推进中持久化的 Agent 间协作、交接、确认和阻塞消息。</p>
          </div>
        </div>
        {!messages.length ? <div className="empty-state compact">当前任务还没有 Agent 间通信记录。</div> : null}
        {messages.length ? (
          <div className="agent-message-list">
            {messages.map((message) => {
              const fromName = message.fromAgentName || getAgentDisplayName(message.fromAgentId, agents);
              const toName = message.toAgentName || getAgentDisplayName(message.toAgentId, agents);
              return (
                <article key={message.id} className={`agent-message ${message.type}`}>
                  <div className="agent-message-route">
                    <strong>{fromName}</strong>
                    <span>→</span>
                    <strong>{toName}</strong>
                    <em>{MESSAGE_TYPE_LABELS[message.type] ?? message.type}</em>
                    {message.artifactRefs.length ? <em>{message.artifactRefs.length} 个产物</em> : null}
                  </div>
                  <p>{message.content}</p>
                  <small>{formatDateTime(message.time)}</small>
                </article>
              );
            })}
          </div>
        ) : null}
      </section>
    </div>
  );
}
