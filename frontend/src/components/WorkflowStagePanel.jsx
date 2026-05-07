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

const STATUS_LABELS = {
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

function formatDateTime(value) {
  if (!value) return "暂无";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function getStatusTone(status) {
  if (status === "completed") return "success";
  if (status === "running") return "info";
  if (status === "waiting_human") return "warning";
  if (status === "failed") return "danger";
  return "warning";
}

function formatDuration(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "暂无";
  if (value < 60) return `${Math.round(value)} 秒`;
  if (value < 3600) return `${Math.round(value / 60)} 分钟`;
  return `${Math.round(value / 360) / 10} 小时`;
}

function formatProgressStatus(status) {
  const labels = {
    not_started: "未开始",
    running: "运行中",
    stale: "疑似卡住",
    completed: "已完成",
    failed: "失败",
    unknown: "状态不完整",
  };
  return labels[status] ?? status ?? "未知";
}

function getProgressTone(progress) {
  if (progress?.stale || progress?.status === "stale") return "danger";
  if (progress?.status === "completed") return "success";
  if (progress?.status === "failed") return "danger";
  if (progress?.status === "running") return "info";
  return "warning";
}

function normalizeArtifactRefs(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean);
  if (typeof value === "string") return [value].filter(Boolean);
  if (typeof value === "object") {
    return Object.entries(value).flatMap(([key, item]) => {
      if (Array.isArray(item)) return item.map((entry) => `${key}: ${entry}`);
      if (item) return [`${key}: ${item}`];
      return [];
    });
  }
  return [];
}

export default function WorkflowStagePanel({
  tasks,
  tasksLoading,
  selectedTask,
  requestContext,
  runProgress,
  runProgressState,
  runProgressError,
  onRefreshRunProgress,
  onSelectTask,
  onOpenHumanCollaboration,
}) {
  const [snapshot, setSnapshot] = useState(null);
  const [state, setState] = useState("idle");
  const [manualRefreshState, setManualRefreshState] = useState("idle");
  const [error, setError] = useState("");

  const stages = useMemo(() => (Array.isArray(snapshot?.stages) ? snapshot.stages : []), [snapshot]);
  const requests = useMemo(() => (Array.isArray(snapshot?.requests) ? snapshot.requests : []), [snapshot]);

  useEffect(() => {
    if (!selectedTask?.id || !requestContext?.accessToken || !requestContext?.teamId) {
      setSnapshot(null);
      setState("idle");
      setError("");
      return;
    }
    let active = true;
    const cached = getCachedCollaborationSnapshot(selectedTask.id, requestContext.teamId);
    if (cached) setSnapshot(cached);
    setState(cached ? "refreshing" : "loading");
    setError("");
    api.taskHumanCollaboration(selectedTask.id, requestContext)
      .then((payload) => {
        if (!active) return;
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
    setManualRefreshState("loading");
    setError("");
    try {
      const payload = await api.taskHumanCollaboration(selectedTask.id, { ...requestContext, noCache: true });
      setCachedCollaborationSnapshot(selectedTask.id, requestContext.teamId, payload);
      setSnapshot(payload);
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : String(refreshError));
    } finally {
      setState("ready");
      setManualRefreshState("idle");
    }
  }

  return (
    <div className="detail-stack workflow-page-layout">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>任务切换</h3>
            <p>工作流阶段和人工复核节点都围绕当前选中的任务展示。</p>
          </div>
          <button type="button" className="chip-button" onClick={handleRefresh} disabled={!selectedTask?.id || manualRefreshState === "loading"}>
            {manualRefreshState === "loading" ? "刷新中..." : "刷新阶段"}
          </button>
        </div>

        {!tasks?.length && !tasksLoading ? <div className="empty-state">当前还没有任务。</div> : null}

        {Array.isArray(tasks) && tasks.length ? (
          <div className="task-cards">
            {tasks.map((task) => (
              <button
                key={task.id}
                type="button"
                className={task.id === selectedTask?.id ? "task-card task-card-button selected" : "task-card task-card-button"}
                onClick={() => onSelectTask?.(task.id)}
              >
                <div className="task-card-top">
                  <h4>{task.name}</h4>
                  <span>{TASK_STATUS_LABELS[task.status] ?? task.status}</span>
                </div>
                <p>{task.dataset_filename || "未上传数据集"}</p>
              </button>
            ))}
          </div>
        ) : null}
      </section>

      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>真实运行诊断</h3>
            <p>直接读取 MLZero 运行目录里的日志与产物，判断是否仍在推进。</p>
          </div>
          <button type="button" className="chip-button" onClick={onRefreshRunProgress} disabled={!selectedTask?.id || runProgressState === "loading" || runProgressState === "refreshing"}>
            {runProgressState === "loading" || runProgressState === "refreshing" ? "诊断中..." : "刷新诊断"}
          </button>
        </div>
        {runProgressError ? <div className="error-banner">{runProgressError}</div> : null}
        {!selectedTask ? <div className="empty-state compact">先选择一个任务。</div> : null}
        {selectedTask && !runProgress && !runProgressError ? <div className="empty-state compact">暂无运行诊断。运行任务后这里会显示真实日志状态。</div> : null}
        {runProgress ? (
          <div className={`callout task-run-progress-card ${runProgress.stale ? "danger" : ""}`}>
            <div className="section-head compact">
              <div>
                <h3>{formatProgressStatus(runProgress.status)}</h3>
                <p>{runProgress.current_activity || "暂无可解析的运行活动。"}</p>
              </div>
              <span className={`runtime-pill ${getProgressTone(runProgress)}`}>{runProgress.progress_percent ?? 0}%</span>
            </div>
            <div className="task-run-progress-meter" aria-label="运行进度">
              <span style={{ width: `${Math.max(0, Math.min(100, runProgress.progress_percent ?? 0))}%` }} />
            </div>
            <div className="summary-grid">
              <article className="summary-item"><span>最后日志</span><strong>{formatDateTime(runProgress.last_log_at)}</strong></article>
              <article className="summary-item"><span>无更新时间</span><strong>{formatDuration(runProgress.seconds_since_last_update)}</strong></article>
              <article className="summary-item"><span>summary</span><strong>{runProgress.artifacts?.has_run_summary ? "已找到" : "未找到"}</strong></article>
              <article className="summary-item"><span>leaderboard</span><strong>{runProgress.artifacts?.has_leaderboard ? "已找到" : "未找到"}</strong></article>
              <article className="summary-item"><span>token_usage</span><strong>{runProgress.artifacts?.has_token_usage ? "已找到" : "未找到"}</strong></article>
              <article className="summary-item"><span>生成代码</span><strong>{runProgress.artifacts?.has_generated_code ? "已找到" : "未找到"}</strong></article>
            </div>
            {runProgress.stale_reason ? <p className="danger-text">{runProgress.stale_reason}</p> : null}
            {runProgress.output_dir ? <p className="mono-text task-run-progress-path">{runProgress.output_dir}</p> : null}
            {Array.isArray(runProgress.latest_log_lines) && runProgress.latest_log_lines.length ? (
              <details className="callout workflow-log-excerpt">
                <summary>查看最后日志</summary>
                <pre className="code-block">{runProgress.latest_log_lines.slice(-40).join("\n")}</pre>
              </details>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>阶段进度</h3>
            <p>这里读取的是后端同步后的真实阶段快照，不是前端推测状态。</p>
          </div>
          {selectedTask ? <span className="runtime-pill info">{selectedTask.name}</span> : null}
        </div>

        {error ? <div className="error-banner">{error}</div> : null}
        {!selectedTask ? <div className="empty-state">先选择一个任务，再查看工作流进度。</div> : null}
        {selectedTask && state === "loading" && !snapshot ? <div className="empty-state">正在读取当前任务的工作流阶段...</div> : null}
        {selectedTask && !stages.length && state !== "loading" ? <div className="empty-state">当前任务还没有阶段记录。</div> : null}

        {stages.length ? (
          <div className="detail-stack">
            {stages.map((stage) => {
              const artifactRefs = normalizeArtifactRefs(stage.artifact_refs);
              return (
                <article key={stage.id} className="section-card">
                  <div className="section-head">
                    <div>
                      <h3>{STAGE_LABELS[stage.stage] ?? stage.stage}</h3>
                      <p>{stage.summary || "暂无阶段摘要。"}</p>
                    </div>
                    <span className={`runtime-pill ${getStatusTone(stage.status)}`}>{STATUS_LABELS[stage.status] ?? stage.status}</span>
                  </div>
                  <div className="summary-grid">
                    <article className="summary-item"><span>连接器</span><strong>{stage.selected_connector_id || "未指定"}</strong></article>
                    <article className="summary-item"><span>模型</span><strong>{stage.model_name || "未指定"}</strong></article>
                    <article className="summary-item"><span>来源</span><strong>{stage.selection_source || "未记录"}</strong></article>
                    <article className="summary-item"><span>更新时间</span><strong>{formatDateTime(stage.updated_at)}</strong></article>
                    <article className="summary-item"><span>开始时间</span><strong>{formatDateTime(stage.started_at)}</strong></article>
                    <article className="summary-item"><span>结束时间</span><strong>{formatDateTime(stage.finished_at)}</strong></article>
                    <article className="summary-item"><span>阶段耗时</span><strong>{formatDuration(stage.duration_seconds)}</strong></article>
                    <article className="summary-item"><span>关键产物</span><strong>{artifactRefs.length ? `${artifactRefs.length} 个` : "未记录"}</strong></article>
                  </div>
                  {stage.log_excerpt ? (
                    <details className="callout workflow-log-excerpt">
                      <summary>查看日志摘要</summary>
                      <pre className="code-block">{stage.log_excerpt}</pre>
                    </details>
                  ) : null}
                  {artifactRefs.length ? (
                    <div className="chip-list workflow-artifact-list">
                      {artifactRefs.map((path) => (
                        <span key={path} className="chip mono-text">{path}</span>
                      ))}
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>
        ) : null}
      </section>

      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>待处理人工节点</h3>
            <p>如果某个阶段被暂停等待人工复核，这里会直接列出来。</p>
          </div>
          {selectedTask ? (
            <button type="button" className="primary-button" onClick={() => onOpenHumanCollaboration?.(selectedTask.id)}>
              打开人机协同页
            </button>
          ) : null}
        </div>

        {!requests.length ? <div className="empty-state compact">当前任务没有待处理的人机协同请求。</div> : null}

        {requests.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>阶段</th>
                  <th>标题</th>
                  <th>状态</th>
                  <th>指派</th>
                  <th>截止时间</th>
                  <th>更新时间</th>
                </tr>
              </thead>
              <tbody>
                {requests.map((request) => (
                  <tr key={request.id}>
                    <td>{STAGE_LABELS[request.stage] ?? request.stage}</td>
                    <td>{request.payload?.title || "未命名请求"}</td>
                    <td>{request.status}</td>
                    <td>{request.assignee_value || request.assigned_to || "未指定"}</td>
                    <td>{formatDateTime(request.timeout_at)}</td>
                    <td>{formatDateTime(request.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
