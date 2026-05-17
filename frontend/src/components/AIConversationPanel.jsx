import { useEffect, useMemo, useState } from "react";

import { formatMetricName, getMetricDirectionLabel } from "../lib/metrics.js";
import {
  formatDateTime,
  formatProblemType,
  formatTaskStatus,
  getTaskStatusTone,
  isRecoverableRunBlockedTask,
} from "../lib/taskPresentation.js";

const LARGE_TEXT_PREVIEW_CHARS = 12_000;
const MESSAGE_RENDER_LIMIT = 80;

const INTERACTIVE_ORIGIN_LABELS = {
  user: "你",
  ai_model: "AI 模型",
  local_runtime: "系统错误",
};

function cx(...parts) {
  return parts.filter(Boolean).join(" ");
}

function formatInteractiveOrigin(value) {
  return INTERACTIVE_ORIGIN_LABELS[value] ?? value ?? "未知";
}

function getMessageText(value) {
  if (typeof value !== "string") return "(empty)";
  const normalized = value.replace(/\r\n/g, "\n").trim();
  return normalized || "(empty)";
}

function formatMetricValue(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "暂无";
  return Math.abs(value) >= 1 ? value.toFixed(4) : value.toPrecision(4);
}

function buildResultSummary(task) {
  if (task?.last_run?.metric_name && typeof task?.last_run?.metric_value === "number") {
    return `${formatMetricName(task.last_run.metric_name)}（${getMetricDirectionLabel(task.last_run.metric_name)}）: ${formatMetricValue(task.last_run.metric_value)}`;
  }
  if (isRecoverableRunBlockedTask(task)) return "自动处理受阻，等待重试";
  if (task?.status === "failed" && task?.notes) return "最近一次运行失败";
  return "还没有运行结果";
}

function getInteractiveCountLabel(count) {
  return count ? `${count} 条` : "0 条";
}

function formatTokenUsage(usage) {
  if (!usage || typeof usage.total_tokens !== "number") return "未记录";
  return `${usage.total_tokens} 用量`;
}

function clipText(value, limit = 1200) {
  const normalized = String(value ?? "").trim();
  if (!normalized) return "";
  return normalized.length <= limit ? normalized : `${normalized.slice(0, limit)}...`;
}

function inferHumanStageFromTask(task) {
  if (task?.status === "completed" || task?.status === "published") return "report_generation";
  if (task?.last_run_attempt || task?.last_run) return "training_validation";
  if (task?.label_column && task?.problem_type) return "feature_engineering";
  if (task?.dataset_filename) return "data_analysis";
  return "requirement_analysis";
}

function inferHumanRequestTypeFromTask(task) {
  if (task?.status === "completed") return "result_review";
  if (task?.last_run_attempt || task?.last_run) return "result_review";
  return "requirement_review";
}

function buildHumanRequestPresetFromConversation(task, prompt, assistantMessage) {
  return {
    stage: inferHumanStageFromTask(task),
    request_type: inferHumanRequestTypeFromTask(task),
    title: "确认 AI 记录中的关键问题",
    summary: prompt,
    suggested_action: assistantMessage?.content
      ? `请结合最近一次 AI 回复判断是否需要转成显式修改要求：\n${clipText(assistantMessage.content)}`
      : "请人工判断这个问题是否需要转成显式修改要求，然后再决定是否继续。",
    artifact_paths: [],
    notice: "已把当前 AI 记录里的问题带入复核请求表单。",
  };
}

function getInteractiveMessageMeta(message) {
  if (message.role === "user") return "你的 prompt";
  if (message.status === "error") return "AI 服务错误";
  return "当前 AI 回复";
}

function getInteractiveBubbleTone(message) {
  if (message.role === "user") return "prompt";
  if (message.origin === "local_runtime" || message.status === "error") return "runtime";
  return "response";
}

function getInteractiveAvatar(message) {
  if (message.role === "user") return "你";
  if (message.origin === "local_runtime" || message.status === "error") return "RT";
  return "AI";
}

function ConversationMetric({ label, value }) {
  return (
    <article className="ai-chat-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function getPreviewText(value, limit = LARGE_TEXT_PREVIEW_CHARS) {
  const text = getMessageText(value);
  if (text.length <= limit) return { text, truncated: false, omitted: 0 };
  return {
    text: text.slice(0, limit),
    truncated: true,
    omitted: text.length - limit,
  };
}

export default function AIConversationPanel({
  tasks,
  tasksLoading,
  selectedTask,
  conversationData,
  loading,
  error,
  chatSending,
  chatError,
  onSelectTask,
  onRefresh,
  onSendInteractivePrompt,
  onOpenHumanCollaboration,
  onOpenTaskDetails,
}) {
  const [draftPrompt, setDraftPrompt] = useState("");
  const [expandedTextIds, setExpandedTextIds] = useState(() => new Set());

  useEffect(() => {
    setDraftPrompt("");
    setExpandedTextIds(new Set());
  }, [selectedTask?.id]);

  const interactiveMessages = Array.isArray(conversationData?.interactive_messages) ? conversationData.interactive_messages : [];
  const visibleInteractiveMessages = interactiveMessages.slice(-MESSAGE_RENDER_LIMIT);
  const warnings = Array.isArray(conversationData?.warnings) ? conversationData.warnings : [];
  const taskItems = Array.isArray(tasks) ? tasks : [];
  const latestAssistantMessage = useMemo(
    () => [...interactiveMessages].reverse().find((message) => message.role === "assistant") ?? null,
    [interactiveMessages],
  );

  async function handleSendPrompt(event) {
    event.preventDefault();
    const normalizedPrompt = draftPrompt.trim();
    if (!normalizedPrompt || !selectedTask || !onSendInteractivePrompt) return;
    const ok = await onSendInteractivePrompt(normalizedPrompt);
    if (ok !== false) setDraftPrompt("");
  }

  function handleOpenHumanRequestDraft() {
    const normalizedPrompt = draftPrompt.trim();
    if (!normalizedPrompt || !selectedTask || !onOpenHumanCollaboration) return;
    onOpenHumanCollaboration(
      selectedTask.id,
      buildHumanRequestPresetFromConversation(selectedTask, normalizedPrompt, latestAssistantMessage),
    );
  }

  function renderLargeText(id, value) {
    const expanded = expandedTextIds.has(id);
    const preview = getPreviewText(value);
    const displayText = expanded ? getMessageText(value) : preview.text;
    return (
      <>
        <pre>{displayText}</pre>
        {preview.truncated ? (
          <button
            type="button"
            className="ghost-button large-text-toggle"
            onClick={() => setExpandedTextIds((current) => {
              const next = new Set(current);
              if (next.has(id)) next.delete(id);
              else next.add(id);
              return next;
            })}
          >
            {expanded ? "收起全文" : `展开全文（已省略 ${preview.omitted.toLocaleString("zh-CN")} 字）`}
          </button>
        ) : null}
      </>
    );
  }

  if (!taskItems.length && !tasksLoading) {
    return (
      <section className="conversation-page-card ai-chat-workspace">
        <div className="empty-state ai-chat-empty">当前团队还没有任务。先去任务页创建并上传 CSV。</div>
      </section>
    );
  }

  return (
    <section className="conversation-page-card ai-chat-workspace">
      <div className="ai-chat-layout">
        <aside className="ai-chat-sidebar">
          <div className="ai-chat-sidebar-head">
            <p className="eyebrow">AI 对话</p>
            <h3>{selectedTask?.name ?? "选择任务"}</h3>
            {selectedTask ? (
              <span className={`runtime-pill ${getTaskStatusTone(isRecoverableRunBlockedTask(selectedTask) ? "blocked" : selectedTask.status)}`}>
                {formatTaskStatus(isRecoverableRunBlockedTask(selectedTask) ? "blocked" : selectedTask.status)}
              </span>
            ) : null}
          </div>

          <label className="conversation-task-picker ai-chat-task-picker">
            <span>当前任务</span>
            <select
              value={selectedTask?.id ?? ""}
              onChange={(event) => onSelectTask?.(event.target.value)}
              disabled={tasksLoading}
            >
              {taskItems.map((task) => (
                <option key={task.id} value={task.id}>
                  {task.name}
                </option>
              ))}
            </select>
          </label>

          {selectedTask ? (
            <div className="ai-chat-metrics">
              <ConversationMetric label="数据集" value={selectedTask.dataset_filename ?? "未上传"} />
              <ConversationMetric label="任务类型" value={formatProblemType(selectedTask.problem_type)} />
              <ConversationMetric label="最近结果" value={buildResultSummary(selectedTask)} />
              <ConversationMetric label="手动聊天" value={getInteractiveCountLabel(interactiveMessages.length)} />
            </div>
          ) : null}

          <div className="ai-chat-sidebar-actions">
            {onOpenTaskDetails ? (
              <button type="button" className="ghost-button" onClick={onOpenTaskDetails}>
                回到任务详情
              </button>
            ) : null}
            <button type="button" className="primary-button" onClick={onRefresh} disabled={loading || !selectedTask}>
              {loading ? "刷新中..." : "刷新"}
            </button>
          </div>

          {warnings.length ? (
            <div className="ai-chat-warning">
              <strong>读取提醒</strong>
              {warnings.map((warning, index) => (
                <p key={`${warning}-${index}`}>{warning}</p>
              ))}
            </div>
          ) : null}
        </aside>

        <div className="ai-chat-main">
          <div className="ai-chat-mainbar">
            <p className="ai-chat-scope-note">AI 记录只展示用户手动对话；系统日志、内部状态和训练事件统一在运行控制台查看。</p>
          </div>

          {error ? <div className="error-banner ai-chat-inline-error">{error}</div> : null}

          {!selectedTask ? (
            <div className="empty-state ai-chat-empty">先选择一个任务。</div>
          ) : null}

          {selectedTask ? (
            <div className="ai-chat-panel ai-chat-thread-panel">
              <div className="ai-chat-thread" aria-live="polite">
                {!interactiveMessages.length ? (
                  <div className="empty-state ai-chat-empty">
                    {chatSending ? "正在等待 AI 回复..." : "还没有手动聊天记录。"}
                  </div>
                ) : (
                  <>
                  {interactiveMessages.length > MESSAGE_RENDER_LIMIT ? <div className="notice-banner compact">当前仅渲染最近 {MESSAGE_RENDER_LIMIT} 条对话，避免长对话拖慢页面。</div> : null}
                  {visibleInteractiveMessages.map((message) => {
                    const isUser = message.role === "user";
                    return (
                      <article key={message.id} className={cx("ai-chat-message", isUser ? "is-user" : "is-assistant")}>
                        <div className="ai-chat-avatar">{getInteractiveAvatar(message)}</div>
                        <div className="ai-chat-message-content">
                          <div className="ai-chat-message-meta">
                            <span>{formatDateTime(message.created_at)}</span>
                            <span className={`runtime-pill ${message.origin === "local_runtime" || message.status === "error" ? "warning" : isUser ? "info" : "success"}`}>
                              {isUser ? "你的 prompt" : formatInteractiveOrigin(message.origin)}
                            </span>
                          </div>
                          <div className={cx("ai-chat-bubble", getInteractiveBubbleTone(message))}>
                            <div className="ai-chat-bubble-head">
                              <strong>{isUser ? "你发出的 prompt" : formatInteractiveOrigin(message.origin)}</strong>
                              <span>{getInteractiveMessageMeta(message)}</span>
                            </div>
                            {renderLargeText(`interactive-${message.id}-content`, message.content)}
                            {message.composed_prompt ? (
                              <details className="ai-chat-raw">
                                <summary>完整上下文</summary>
                                {renderLargeText(`interactive-${message.id}-composed`, message.composed_prompt)}
                              </details>
                            ) : null}
                          </div>
                          {!isUser ? (
                            <div className="ai-chat-tokenline">
                              {message.model_name ? <span>模型：{message.model_name}</span> : null}
                              <span>用量：{formatTokenUsage(message.token_usage)}</span>
                            </div>
                          ) : null}
                        </div>
                      </article>
                    );
                  })}
                  </>
                )}
              </div>

              {chatError ? <div className="error-banner ai-chat-inline-error">{chatError}</div> : null}

              <form className="ai-chat-composer" onSubmit={handleSendPrompt}>
                <textarea
                  value={draftPrompt}
                  onChange={(event) => setDraftPrompt(event.target.value)}
                  disabled={!selectedTask || chatSending}
                  placeholder="输入 prompt..."
                  rows={3}
                />
                <div className="ai-chat-composer-actions">
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={handleOpenHumanRequestDraft}
                    disabled={!selectedTask || chatSending || !draftPrompt.trim()}
                  >
                    转成复核待办
                  </button>
                  <button
                    type="submit"
                    className="primary-button"
                    disabled={!selectedTask || chatSending || !draftPrompt.trim()}
                  >
                    {chatSending ? "发送中..." : "发送"}
                  </button>
                </div>
              </form>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
