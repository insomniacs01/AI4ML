import { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api.js";

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
  onSelectTask,
  onOpenHumanCollaboration,
}) {
  const [snapshot, setSnapshot] = useState(null);
  const [state, setState] = useState("idle");
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
    setState("loading");
    setError("");
    api.taskHumanCollaboration(selectedTask.id, requestContext)
      .then((payload) => {
        if (!active) return;
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
      setSnapshot(await api.taskHumanCollaboration(selectedTask.id, requestContext));
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : String(refreshError));
    } finally {
      setState("ready");
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
          <button type="button" className="chip-button" onClick={handleRefresh} disabled={!selectedTask?.id || state === "loading"}>
            {state === "loading" ? "刷新中..." : "刷新阶段"}
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
                    <article className="summary-item"><span>关键产物</span><strong>{artifactRefs.length ? `${artifactRefs.length} 个` : "未记录"}</strong></article>
                  </div>
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
