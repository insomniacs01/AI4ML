import { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api.js";
import { getCachedCollaborationSnapshot, setCachedCollaborationSnapshot } from "../lib/collaborationCache.js";

const STAGE_LABELS = {
  requirement_analysis: "需求解析",
  data_analysis: "数据分析",
  feature_engineering: "特征工程",
  model_selection: "模型选择",
  training_validation: "训练验证",
  report_generation: "报告生成",
};

const STAGE_STATUS_LABELS = {
  pending: "未开始",
  running: "进行中",
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

const REQUEST_STATUS_LABELS = {
  pending: "待处理",
  open: "待处理",
  confirmed: "已确认",
  modified: "要求修改",
  rejected: "已驳回",
  reassigned: "已转交",
  expired: "已超时",
  skipped: "已跳过",
  resolved: "已处理",
};

const DECISION_LABELS = {
  approve: "通过",
  revise: "要求修改并重跑",
  block: "阻塞",
  reject: "驳回并重跑",
  reassign: "转交",
  skip: "跳过",
};

const REQUEST_TYPE_OPTIONS = [
  { value: "requirement_review", label: "需求确认" },
  { value: "data_review", label: "数据确认" },
  { value: "code_review", label: "代码确认" },
  { value: "result_review", label: "结果确认" },
];

const ASSIGNEE_TYPE_OPTIONS = [
  { value: "member", label: "指定成员" },
  { value: "role", label: "按角色" },
  { value: "candidate_pool", label: "候选组" },
];

const STAGE_ORDER = [
  "requirement_analysis",
  "data_analysis",
  "feature_engineering",
  "model_selection",
  "training_validation",
  "report_generation",
];

const EMPTY_REQUEST_FORM = {
  stage: "requirement_analysis",
  request_type: "requirement_review",
  title: "",
  summary: "",
  suggested_action: "",
  artifact_paths: "",
  assigned_to: "",
  assignee_type: "member",
  assignee_value: "",
  timeout_minutes: "",
};

function formatDateTime(value) {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function formatTaskStatus(status) {
  return TASK_STATUS_LABELS[status] ?? status ?? "未知状态";
}

function formatStage(stage) {
  return STAGE_LABELS[stage] ?? stage ?? "未命名阶段";
}

function formatStageStatus(status) {
  return STAGE_STATUS_LABELS[status] ?? status ?? "未知";
}

function getStatusTone(status) {
  if (["completed", "approve", "confirmed", "skipped"].includes(status)) return "success";
  if (["running", "modified", "reassigned"].includes(status)) return "info";
  if (["waiting_human", "pending", "open"].includes(status)) return "warning";
  if (["failed", "block", "reject", "rejected", "expired"].includes(status)) return "danger";
  return "info";
}

function normalizeArtifactPaths(value) {
  return String(value ?? "")
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinArtifactPaths(value) {
  return Array.isArray(value) ? value.join("\n") : "";
}

function buildRequestFormFromPreset(preset) {
  return {
    stage: preset?.stage ?? EMPTY_REQUEST_FORM.stage,
    request_type: preset?.request_type ?? EMPTY_REQUEST_FORM.request_type,
    title: preset?.title ?? "",
    summary: preset?.summary ?? "",
    suggested_action: preset?.suggested_action ?? "",
    artifact_paths: joinArtifactPaths(preset?.artifact_paths),
    assigned_to: preset?.assigned_to ?? "",
    assignee_type: preset?.assignee_type ?? EMPTY_REQUEST_FORM.assignee_type,
    assignee_value: preset?.assignee_value ?? "",
    timeout_minutes: preset?.timeout_minutes ? String(preset.timeout_minutes) : "",
  };
}

function buildDecisionDraft(request) {
  const summary = typeof request?.payload?.suggested_action === "string" && request.payload.suggested_action.trim()
    ? request.payload.suggested_action.trim()
    : "";
  return {
    action: "approve",
    decision_summary: summary,
    artifact_paths: Array.isArray(request?.payload?.artifact_paths) ? request.payload.artifact_paths.join("\n") : "",
    resume_task: true,
    reassign_assignee_type: request?.assignee_type ?? "member",
    reassign_assignee_value: "",
    reassign_assigned_to: "",
    reassign_timeout_minutes: "",
  };
}

function getRequestTitle(request) {
  if (typeof request?.payload?.title === "string" && request.payload.title.trim()) return request.payload.title.trim();
  return "未命名协同请求";
}

function getRequestSummary(request) {
  if (typeof request?.payload?.summary === "string" && request.payload.summary.trim()) return request.payload.summary.trim();
  return "暂无说明。";
}

function getRequestSuggestedAction(request) {
  if (typeof request?.payload?.suggested_action === "string" && request.payload.suggested_action.trim()) return request.payload.suggested_action.trim();
  return "";
}

function isActiveRequest(request) {
  return request?.status === "pending" || request?.status === "open";
}

export default function HumanCollaborationPanel({
  tasks,
  tasksLoading,
  selectedTask,
  requestContext,
  requestPreset,
  onSelectTask,
  onTaskUpdated,
  onOpenTaskDetails,
}) {
  const [snapshot, setSnapshot] = useState(null);
  const [state, setState] = useState("idle");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [requestForm, setRequestForm] = useState(EMPTY_REQUEST_FORM);
  const [submittingRequest, setSubmittingRequest] = useState(false);
  const [resumingTask, setResumingTask] = useState(false);
  const [decisionBusyId, setDecisionBusyId] = useState("");
  const [decisionDrafts, setDecisionDrafts] = useState({});

  const taskItems = Array.isArray(tasks) ? tasks : [];
  const stageItems = useMemo(() => {
    const items = Array.isArray(snapshot?.stages) ? snapshot.stages : [];
    return [...items].sort((left, right) => STAGE_ORDER.indexOf(left.stage) - STAGE_ORDER.indexOf(right.stage));
  }, [snapshot?.stages]);
  const requestItems = Array.isArray(snapshot?.requests) ? snapshot.requests : [];
  const openRequests = requestItems.filter((item) => isActiveRequest(item));
  const decisionHistory = useMemo(() => {
    const items = Array.isArray(snapshot?.decision_history) ? snapshot.decision_history : [];
    return [...items].sort((left, right) => {
      const leftTime = Date.parse(left?.decided_at ?? left?.updated_at ?? "");
      const rightTime = Date.parse(right?.decided_at ?? right?.updated_at ?? "");
      return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
    });
  }, [snapshot?.decision_history]);
  const nextRunGuidance = snapshot?.next_run_guidance ?? null;

  useEffect(() => {
    if (!requestPreset?.preset_id || requestPreset?.task_id !== selectedTask?.id) return;
    setRequestForm(buildRequestFormFromPreset(requestPreset));
    setMessage(requestPreset.notice ?? "已带入协同请求草稿，你可以直接补充后提交。");
    setError("");
  }, [requestPreset?.preset_id, requestPreset?.task_id, requestPreset?.notice, selectedTask?.id]);

  useEffect(() => {
    if (!selectedTask?.id || !requestContext?.accessToken || !requestContext?.teamId) {
      setSnapshot(null);
      setState("idle");
      setError("");
      setMessage("");
      setDecisionDrafts({});
      return;
    }

    let active = true;
    const cached = getCachedCollaborationSnapshot(selectedTask.id, requestContext.teamId);
    if (cached) setSnapshot(cached);
    setState(cached ? "ready" : "loading");
    setError("");

    api.taskHumanCollaboration(selectedTask.id, requestContext)
      .then((payload) => {
        if (!active) return;
        setCachedCollaborationSnapshot(selectedTask.id, requestContext.teamId, payload);
        setSnapshot(payload);
        setState("ready");
        setDecisionDrafts((current) => {
          const next = { ...current };
          for (const item of payload.requests ?? []) {
            if (!next[item.id] && item.status === "open") next[item.id] = buildDecisionDraft(item);
          }
          return next;
        });
        onTaskUpdated?.(payload.task);
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
  }, [onTaskUpdated, requestContext, selectedTask?.id]);

  function syncSnapshot(payload, nextMessage) {
    setCachedCollaborationSnapshot(selectedTask?.id, requestContext?.teamId, payload);
    setSnapshot(payload);
    setMessage(nextMessage);
    setError("");
    onTaskUpdated?.(payload.task);
    setDecisionDrafts((current) => {
      const next = { ...current };
      for (const item of payload.requests ?? []) {
        if (!next[item.id] && item.status === "open") next[item.id] = buildDecisionDraft(item);
      }
      return next;
    });
  }

  async function handleRefresh() {
    if (!selectedTask?.id) return;
    setState("loading");
    setError("");
    try {
      const payload = await api.taskHumanCollaboration(selectedTask.id, { ...requestContext, noCache: true });
      syncSnapshot(payload, "");
      setState("ready");
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : String(refreshError));
      setState("ready");
    }
  }

  async function handleCreateRequest(event) {
    event.preventDefault();
    if (!selectedTask?.id) return;
    setSubmittingRequest(true);
    setError("");
    setMessage("");
    try {
      const payload = await api.createTaskHumanRequest(
        selectedTask.id,
        {
          stage: requestForm.stage,
          request_type: requestForm.request_type,
          title: requestForm.title.trim(),
          summary: requestForm.summary.trim(),
          suggested_action: requestForm.suggested_action.trim() || null,
          artifact_paths: normalizeArtifactPaths(requestForm.artifact_paths),
          assigned_to: requestForm.assigned_to.trim() || null,
          assignee_type: requestForm.assignee_type,
          assignee_value: requestForm.assignee_value.trim() || null,
          timeout_minutes: requestForm.timeout_minutes ? Number.parseInt(requestForm.timeout_minutes, 10) || null : null,
        },
        requestContext,
      );
      syncSnapshot(payload, "协同请求已创建，任务已进入等待人工复核状态。");
      setRequestForm(EMPTY_REQUEST_FORM);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : String(submitError));
    } finally {
      setSubmittingRequest(false);
    }
  }

  async function handleDecisionSubmit(requestId) {
    if (!selectedTask?.id || !requestId || decisionBusyId === requestId) return;
    const draft = decisionDrafts[requestId];
    if (!draft?.decision_summary?.trim()) {
      setError("请先填写决策说明。");
      return;
    }
    if (draft.action === "reassign" && !draft.reassign_assignee_value?.trim() && !draft.reassign_assigned_to?.trim()) {
      setError("转交请求需要填写新的指派值或指定成员 ID。");
      return;
    }

    setDecisionBusyId(requestId);
    setError("");
    setMessage("");
    try {
      const payload = await api.decideTaskHumanRequest(
        selectedTask.id,
        requestId,
        {
          action: draft.action,
          decision_summary: draft.decision_summary.trim(),
          artifact_paths: normalizeArtifactPaths(draft.artifact_paths),
          resume_task: Boolean(draft.resume_task),
          reassign_assignee_type: draft.action === "reassign" ? draft.reassign_assignee_type : null,
          reassign_assignee_value: draft.action === "reassign" ? draft.reassign_assignee_value?.trim() || null : null,
          reassign_assigned_to: draft.action === "reassign" ? draft.reassign_assigned_to?.trim() || null : null,
          reassign_timeout_minutes: draft.action === "reassign" && draft.reassign_timeout_minutes ? Number.parseInt(draft.reassign_timeout_minutes, 10) || null : null,
        },
        requestContext,
      );
      syncSnapshot(payload, draft.resume_task ? "协同决策已提交，任务状态已同步。" : "协同决策已提交，任务仍保持等待复核。");
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : String(submitError));
    } finally {
      setDecisionBusyId("");
    }
  }

  async function handleResumeTask() {
    if (!selectedTask?.id || resumingTask) return;
    setResumingTask(true);
    setError("");
    setMessage("");
    try {
      const payload = await api.resumeTask(selectedTask.id, requestContext);
      syncSnapshot(payload, "任务已恢复到人工介入前的状态。");
    } catch (resumeError) {
      setError(resumeError instanceof Error ? resumeError.message : String(resumeError));
    } finally {
      setResumingTask(false);
    }
  }

  return (
    <section className="section-card human-collaboration-card">
      {!taskItems.length && !tasksLoading ? (
        <div className="empty-state">当前团队还没有任务。先创建一个任务，再进入人机协同页。</div>
      ) : null}

      {taskItems.length ? (
        <div className="human-collaboration-shell">
          <div className="human-collaboration-toolbar">
            <div className="human-collaboration-intro">
              <p className="eyebrow">Human Collaboration</p>
              <h3>{selectedTask?.name ?? "选择一个任务"}</h3>
              <p>这里展示任务级的人机协同闭环：阶段状态、自动或手工创建的复核请求、人工决策，以及任务恢复。</p>
            </div>

            <div className="human-collaboration-actions">
              <label className="conversation-task-picker">
                <span>当前任务</span>
                <select value={selectedTask?.id ?? ""} onChange={(event) => onSelectTask?.(event.target.value)} disabled={tasksLoading}>
                  {taskItems.map((task) => (
                    <option key={task.id} value={task.id}>{task.name}</option>
                  ))}
                </select>
              </label>

              {selectedTask ? <span className={`runtime-pill ${getStatusTone(selectedTask.status === "paused_for_review" ? "waiting_human" : selectedTask.status)}`}>{formatTaskStatus(selectedTask.status)}</span> : null}

              {onOpenTaskDetails ? (
                <button type="button" className="ghost-button" onClick={onOpenTaskDetails}>
                  回到任务详情
                </button>
              ) : null}

              <button type="button" className="ghost-button" onClick={() => void handleRefresh()} disabled={state === "loading"}>
                {state === "loading" ? "刷新中..." : "刷新协同状态"}
              </button>

              <button
                type="button"
                className="primary-button"
                onClick={() => void handleResumeTask()}
                disabled={!snapshot?.can_resume || resumingTask}
              >
                {resumingTask ? "恢复中..." : "恢复任务"}
              </button>
            </div>
          </div>

          {selectedTask ? (
            <div className="conversation-context-strip human-collaboration-context">
              <span className="conversation-context-pill">
                <strong>任务状态</strong>
                <em>{formatTaskStatus(snapshot?.task?.status ?? selectedTask.status)}</em>
              </span>
              <span className="conversation-context-pill">
                <strong>开放请求</strong>
                <em>{snapshot?.open_request_count ?? 0}</em>
              </span>
              <span className="conversation-context-pill">
                <strong>可恢复</strong>
                <em>{snapshot?.can_resume ? "是" : "否"}</em>
              </span>
              <span className="conversation-context-pill">
                <strong>数据集</strong>
                <em>{selectedTask.dataset_filename ?? "未上传"}</em>
              </span>
            </div>
          ) : null}

          {message ? <div className="notice-banner">{message}</div> : null}
          {error ? <div className="error-banner">{error}</div> : null}

          {!selectedTask ? (
            <div className="empty-state">先选择一个任务，再查看它的人机协同状态。</div>
          ) : (
            <div className="human-collaboration-grid">
              <section className="section-card human-stage-board">
                <div className="section-head">
                  <div>
                    <h3>阶段状态</h3>
                    <p>阶段状态由后端根据任务进度和开放中的人工请求自动同步。</p>
                  </div>
                </div>

                {!stageItems.length ? (
                  <div className="empty-state compact">{state === "loading" ? "正在读取阶段状态..." : "当前还没有阶段记录。"}</div>
                ) : (
                  <div className="human-stage-grid">
                    {stageItems.map((item) => (
                      <article key={item.stage} className="stage-card">
                        <div className="task-card-top">
                          <div>
                            <p className="eyebrow">{formatStage(item.stage)}</p>
                            <h4>{formatStageStatus(item.status)}</h4>
                          </div>
                          <span className={`runtime-pill ${getStatusTone(item.status)}`}>{formatStageStatus(item.status)}</span>
                        </div>
                        <p className="task-description">{item.summary ?? "暂无阶段说明。"}</p>
                        <dl className="stage-meta">
                          <div><dt>模型</dt><dd>{item.model_name ?? "未记录"}</dd></div>
                          <div><dt>来源</dt><dd>{item.selection_source ?? "未记录"}</dd></div>
                          <div><dt>更新时间</dt><dd>{formatDateTime(item.updated_at)}</dd></div>
                          <div><dt>工件数</dt><dd>{Array.isArray(item.artifact_refs) ? item.artifact_refs.length : 0}</dd></div>
                        </dl>
                      </article>
                    ))}
                  </div>
                )}
              </section>

              <section className="section-card human-request-board">
                <div className="section-head">
                  <div>
                    <h3>创建协同请求</h3>
                    <p>你可以手动在任意阶段插入一个人工复核节点，和自动策略生成的节点一起工作。</p>
                  </div>
                </div>

                <form className="task-form" onSubmit={handleCreateRequest}>
                  <div className="form-row">
                    <label className="field">
                      <span>阶段</span>
                      <select value={requestForm.stage} onChange={(event) => setRequestForm((current) => ({ ...current, stage: event.target.value }))}>
                        {STAGE_ORDER.map((stage) => (
                          <option key={stage} value={stage}>{formatStage(stage)}</option>
                        ))}
                      </select>
                    </label>

                    <label className="field">
                      <span>请求类型</span>
                      <select value={requestForm.request_type} onChange={(event) => setRequestForm((current) => ({ ...current, request_type: event.target.value }))}>
                        {REQUEST_TYPE_OPTIONS.map((item) => (
                          <option key={item.value} value={item.value}>{item.label}</option>
                        ))}
                      </select>
                    </label>
                  </div>

                  <div className="form-row">
                    <label className="field">
                      <span>指派方式</span>
                      <select value={requestForm.assignee_type} onChange={(event) => setRequestForm((current) => ({ ...current, assignee_type: event.target.value }))}>
                        {ASSIGNEE_TYPE_OPTIONS.map((item) => (
                          <option key={item.value} value={item.value}>{item.label}</option>
                        ))}
                      </select>
                    </label>

                    <label className="field">
                      <span>指派值</span>
                      <input
                        value={requestForm.assignee_value}
                        onChange={(event) => setRequestForm((current) => ({ ...current, assignee_value: event.target.value }))}
                        placeholder="例如：某个用户 ID、developer_user、ml-reviewers"
                      />
                    </label>

                    <label className="field">
                      <span>超时（分钟）</span>
                      <input
                        type="number"
                        min="5"
                        step="5"
                        value={requestForm.timeout_minutes}
                        onChange={(event) => setRequestForm((current) => ({ ...current, timeout_minutes: event.target.value }))}
                        placeholder="例如：60"
                      />
                    </label>
                  </div>

                  <label className="field">
                    <span>标题</span>
                    <input
                      type="text"
                      value={requestForm.title}
                      onChange={(event) => setRequestForm((current) => ({ ...current, title: event.target.value }))}
                      placeholder="例如：运行前确认目标列与指标"
                      required
                    />
                  </label>

                  <label className="field">
                    <span>问题说明</span>
                    <textarea
                      rows={4}
                      value={requestForm.summary}
                      onChange={(event) => setRequestForm((current) => ({ ...current, summary: event.target.value }))}
                      placeholder="明确写出要人工看什么、为什么需要停下来。"
                      required
                    />
                  </label>

                  <label className="field">
                    <span>建议动作</span>
                    <textarea
                      rows={3}
                      value={requestForm.suggested_action}
                      onChange={(event) => setRequestForm((current) => ({ ...current, suggested_action: event.target.value }))}
                      placeholder="例如：请确认 metric_name 是否应改为 F1，或是否需要修改 generated_code.py。"
                    />
                  </label>

                  <label className="field">
                    <span>关联工件路径</span>
                    <textarea
                      rows={3}
                      value={requestForm.artifact_paths}
                      onChange={(event) => setRequestForm((current) => ({ ...current, artifact_paths: event.target.value }))}
                      placeholder="每行一个路径，可填运行目录、代码文件、数据文件。"
                    />
                  </label>

                  <div className="button-row connector-actions">
                    <button type="submit" className="primary-button" disabled={submittingRequest || !selectedTask}>
                      {submittingRequest ? "创建中..." : "创建协同请求"}
                    </button>
                  </div>
                </form>
              </section>
            </div>
          )}

          {selectedTask ? (
            <section className="section-card human-guidance-board">
              <div className="section-head">
                <div>
                  <h3>下一轮注入预览</h3>
                  <p>这里直接显示下一次 MLZero 运行和任务 AI 对话会读取到的人机协同内容。</p>
                </div>
              </div>

              <div className="summary-grid human-guidance-grid">
                <article className="summary-item">
                  <span>已记录决策</span>
                  <strong>{nextRunGuidance?.decision_count ?? 0}</strong>
                </article>
                <article className="summary-item">
                  <span>注入目标</span>
                  <strong>{Array.isArray(nextRunGuidance?.targets) ? nextRunGuidance.targets.length : 0}</strong>
                </article>
                <article className="summary-item">
                  <span>当前状态</span>
                  <strong>{nextRunGuidance?.has_guidance ? "会注入人工指引" : "暂不注入"}</strong>
                </article>
                <article className="summary-item">
                  <span>Prompt 行数</span>
                  <strong>{Array.isArray(nextRunGuidance?.prompt_guidance_lines) ? nextRunGuidance.prompt_guidance_lines.length : 0}</strong>
                </article>
              </div>

              {!nextRunGuidance?.has_guidance ? (
                <div className="empty-state">当前还没有已解决的人机协同决策，因此下一轮不会额外注入人工指引。</div>
              ) : (
                <div className="human-guidance-panels">
                  <details className="conversation-state-card human-guidance-panel" open>
                    <summary className="conversation-state-summary">
                      <div className="conversation-state-summary-copy">
                        <strong>`descriptions.txt` 追加片段</strong>
                        <span>这一段会合并到 MLZero 输入目录中的任务说明文件。</span>
                      </div>
                    </summary>
                    <div className="conversation-state-content">
                      <pre className="conversation-state-body">{nextRunGuidance.description_appendix}</pre>
                    </div>
                  </details>

                  <details className="conversation-state-card human-guidance-panel">
                    <summary className="conversation-state-summary">
                      <div className="conversation-state-summary-copy">
                        <strong>`human_collaboration_instructions.txt`</strong>
                        <span>这是专门写给下一轮 MLZero 的人机协同说明文件。</span>
                      </div>
                    </summary>
                    <div className="conversation-state-content">
                      <pre className="conversation-state-body">{nextRunGuidance.human_instruction_file}</pre>
                    </div>
                  </details>

                  <details className="conversation-state-card human-guidance-panel">
                    <summary className="conversation-state-summary">
                      <div className="conversation-state-summary-copy">
                        <strong>任务 AI 对话上下文</strong>
                        <span>你在“AI 对话”页继续聊天时，也会附带这一段历史决策。</span>
                      </div>
                    </summary>
                    <div className="conversation-state-content">
                      <p className="mono-text">{nextRunGuidance.initial_instruction_note || "当前没有额外的初始指令补充。"}</p>
                      <pre className="conversation-state-body">{nextRunGuidance.chat_context_block}</pre>
                    </div>
                  </details>
                </div>
              )}
            </section>
          ) : null}

          {selectedTask ? (
            <section className="section-card human-request-list-board">
              <div className="section-head">
                <div>
                  <h3>待处理请求</h3>
                  <p>开放中的请求会把任务锁定为等待复核，直到你在这里给出决策并决定是否恢复。</p>
                </div>
                <span className={`runtime-pill ${openRequests.length ? "warning" : "success"}`}>
                  {openRequests.length ? `${openRequests.length} 个待处理` : "当前无待处理请求"}
                </span>
              </div>

              {!openRequests.length ? (
                <div className="empty-state">当前没有开放中的人工请求。</div>
              ) : (
                <div className="human-request-list">
                  {openRequests.map((request) => {
                    const draft = decisionDrafts[request.id] ?? buildDecisionDraft(request);
                    return (
                      <article key={request.id} className="status-card human-request-card">
                        <div className="status-card-top">
                          <div>
                            <p className="eyebrow">{formatStage(request.stage)}</p>
                            <h4>{getRequestTitle(request)}</h4>
                          </div>
                          <span className={`runtime-pill ${getStatusTone(request.status === "open" ? "waiting_human" : request.status)}`}>
                            {REQUEST_STATUS_LABELS[request.status] ?? request.status}
                          </span>
                        </div>

                        <p className="task-description">{getRequestSummary(request)}</p>
                        {getRequestSuggestedAction(request) ? (
                          <div className="callout">
                            <strong>建议动作</strong>
                            <p>{getRequestSuggestedAction(request)}</p>
                          </div>
                        ) : null}

                        {Array.isArray(request.payload?.artifact_paths) && request.payload.artifact_paths.length ? (
                          <div className="chip-list">
                            {request.payload.artifact_paths.map((path) => <span key={path} className="chip mono-text">{path}</span>)}
                          </div>
                        ) : null}

                        <div className="human-decision-form">
                          <label className="field">
                            <span>决策动作</span>
                            <select
                              value={draft.action}
                              onChange={(event) => setDecisionDrafts((current) => ({ ...current, [request.id]: { ...draft, action: event.target.value } }))}
                            >
                              {Object.entries(DECISION_LABELS).map(([value, label]) => (
                                <option key={value} value={value}>{label}</option>
                              ))}
                            </select>
                          </label>

                          <label className="field">
                            <span>决策说明</span>
                            <textarea
                              rows={4}
                              value={draft.decision_summary}
                              onChange={(event) => setDecisionDrafts((current) => ({ ...current, [request.id]: { ...draft, decision_summary: event.target.value } }))}
                              placeholder="明确说明这次人工判断的结论，以及接下来应该怎么做。"
                            />
                          </label>

                          {draft.action === "reassign" ? (
                            <div className="form-row">
                              <label className="field">
                                <span>新指派方式</span>
                                <select
                                  value={draft.reassign_assignee_type}
                                  onChange={(event) => setDecisionDrafts((current) => ({ ...current, [request.id]: { ...draft, reassign_assignee_type: event.target.value } }))}
                                >
                                  {ASSIGNEE_TYPE_OPTIONS.map((item) => (
                                    <option key={item.value} value={item.value}>{item.label}</option>
                                  ))}
                                </select>
                              </label>

                              <label className="field">
                                <span>新指派值</span>
                                <input
                                  value={draft.reassign_assignee_value}
                                  onChange={(event) => setDecisionDrafts((current) => ({ ...current, [request.id]: { ...draft, reassign_assignee_value: event.target.value } }))}
                                  placeholder="成员 ID、角色或候选池"
                                />
                              </label>

                              <label className="field">
                                <span>新超时（分钟）</span>
                                <input
                                  type="number"
                                  min="5"
                                  step="5"
                                  value={draft.reassign_timeout_minutes}
                                  onChange={(event) => setDecisionDrafts((current) => ({ ...current, [request.id]: { ...draft, reassign_timeout_minutes: event.target.value } }))}
                                  placeholder="留空则沿用原超时"
                                />
                              </label>
                            </div>
                          ) : null}

                          <label className="field">
                            <span>决策后关联工件</span>
                            <textarea
                              rows={3}
                              value={draft.artifact_paths}
                              onChange={(event) => setDecisionDrafts((current) => ({ ...current, [request.id]: { ...draft, artifact_paths: event.target.value } }))}
                              placeholder="可补充修订后的代码路径或报告路径。"
                            />
                          </label>

                          <label className="human-resume-toggle">
                            <input
                              type="checkbox"
                              checked={Boolean(draft.resume_task)}
                              onChange={(event) => setDecisionDrafts((current) => ({ ...current, [request.id]: { ...draft, resume_task: event.target.checked } }))}
                            />
                            <span>如果这是最后一个待处理请求，提交后自动恢复任务</span>
                          </label>

                          <div className="button-row connector-actions">
                            <button
                              type="button"
                              className="primary-button"
                              onClick={() => void handleDecisionSubmit(request.id)}
                              disabled={decisionBusyId === request.id}
                            >
                              {decisionBusyId === request.id ? "提交中..." : "提交决策"}
                            </button>
                            <span className="helper-text">创建时间：{formatDateTime(request.created_at)}</span>
                          </div>
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </section>
          ) : null}

          {selectedTask ? (
            <section className="section-card human-request-list-board">
              <div className="section-head">
                <div>
                  <h3>历史决策</h3>
                  <p>这里保留已经关闭的人机协同请求，便于回看谁在什么阶段给过什么判断。</p>
                </div>
              </div>

              {!decisionHistory.length ? (
                <div className="empty-state">当前还没有历史决策。</div>
              ) : (
                <div className="human-request-history">
                  {decisionHistory.map((item, index) => (
                    <article key={`${item.request_id ?? "history"}-${item.updated_at ?? item.decided_at ?? index}`} className="status-card human-request-card history">
                      <div className="status-card-top">
                        <div>
                          <p className="eyebrow">{formatStage(item.stage)}</p>
                          <h4>{item.title ?? "未命名协同决策"}</h4>
                        </div>
                        <span className={`runtime-pill ${getStatusTone(item.action)}`}>
                          {DECISION_LABELS[item.action] ?? item.action ?? "未记录"}
                        </span>
                      </div>
                      <p className="task-description">{item.request_summary ?? "这条历史决策没有额外的问题说明。"}</p>
                      {item.suggested_action ? (
                        <div className="callout">
                          <strong>原始期望动作</strong>
                          <p>{item.suggested_action}</p>
                        </div>
                      ) : null}
                      <dl className="stage-meta">
                        <div><dt>决策结论</dt><dd>{item.decision_summary ?? "未记录"}</dd></div>
                        <div><dt>决策时间</dt><dd>{formatDateTime(item.decided_at ?? item.updated_at)}</dd></div>
                        <div><dt>请求类型</dt><dd>{item.request_type ?? "未记录"}</dd></div>
                        <div><dt>提交后恢复</dt><dd>{item.resume_task === false ? "否" : "是"}</dd></div>
                      </dl>
                      {Array.isArray(item.artifact_paths) && item.artifact_paths.length ? (
                        <div className="chip-list">
                          {item.artifact_paths.map((path) => <span key={path} className="chip mono-text">{path}</span>)}
                        </div>
                      ) : null}
                    </article>
                  ))}
                </div>
              )}
            </section>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
