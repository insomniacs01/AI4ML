import { useEffect, useMemo, useState } from "react";

const PHASE_LABELS = {
  analysis: "任务解析",
  mlzero: "MLZero 执行",
};

const STAGE_LABELS = {
  task_analysis: "任务解析",
  python_coder: "Python 代码生成",
  bash_coder: "Shell / PowerShell 包装",
  executer: "执行评估",
  error_analyzer: "错误分析",
  chat: "补充对话",
};

const ORIGIN_LABELS = {
  ai_model: "AI 模型",
  local_runtime: "本地运行时",
  unknown: "未知来源",
};

const ORIGIN_TONES = {
  ai_model: "success",
  local_runtime: "warning",
  unknown: "warning",
};

const INTERNAL_STATE_CATEGORY_LABELS = {
  decision: "决策",
  error: "错误",
  log: "日志",
  retrieval: "检索",
  code: "代码状态",
  summary: "摘要",
  metric: "指标",
  artifact: "工件",
  other: "其他",
};

const PROMPT_EXPLANATIONS = {
  task_analysis: "识别目标列、任务类型和建议指标。",
  python_coder: "生成或修复训练脚本。",
  bash_coder: "生成本机执行包装脚本。",
  executer: "判断本轮运行是否成功。",
  error_analyzer: "总结失败原因并指导下一轮修复。",
  chat: "补充说明或辅助对话。",
};

const TASK_STATUS_LABELS = {
  draft: "草稿",
  uploaded: "已上传数据集",
  planning: "规划中",
  running: "运行中",
  paused_for_review: "等待复核",
  waiting_human: "等待人工协同",
  completed: "已完成",
  failed: "失败",
  published: "已发布",
};

const TASK_STATUS_TONES = {
  draft: "warning",
  uploaded: "info",
  planning: "info",
  running: "info",
  paused_for_review: "warning",
  waiting_human: "warning",
  completed: "success",
  failed: "danger",
  published: "success",
};

const PROBLEM_TYPE_LABELS = {
  classification: "分类",
  regression: "回归",
};

const INTERACTIVE_ORIGIN_LABELS = {
  user: "你",
  ai_model: "AI 模型",
  local_runtime: "系统错误",
};

function cx(...parts) {
  return parts.filter(Boolean).join(" ");
}

function formatDateTime(value) {
  if (!value) return "时间未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function formatPhase(value) {
  return PHASE_LABELS[value] ?? value ?? "未指定";
}

function formatOrigin(value) {
  return ORIGIN_LABELS[value] ?? value ?? "未知来源";
}

function formatTaskStatus(value) {
  return TASK_STATUS_LABELS[value] ?? value ?? "未知状态";
}

function formatTaskStatusTone(value) {
  return TASK_STATUS_TONES[value] ?? "warning";
}

function formatInternalStateCategory(value) {
  return INTERNAL_STATE_CATEGORY_LABELS[value] ?? value ?? "其他";
}

function formatProblemType(value) {
  return PROBLEM_TYPE_LABELS[value] ?? value ?? "未解析";
}

function formatInteractiveOrigin(value) {
  return INTERACTIVE_ORIGIN_LABELS[value] ?? value ?? "未知";
}

function getOriginTone(value) {
  return ORIGIN_TONES[value] ?? "warning";
}

function getOriginAvatar(value) {
  if (value === "ai_model") return "AI";
  if (value === "local_runtime") return "RT";
  return "?";
}

function getResponseNote(value) {
  if (value === "local_runtime") return "本地运行逻辑";
  if (value === "ai_model") return "真实模型调用";
  return "来源未确认";
}

function getTurnMeta(item, index) {
  const stageLabel = STAGE_LABELS[item.stage] ?? item.stage ?? "未命名阶段";
  const segments = [`Round ${index + 1}`, formatPhase(item.phase), stageLabel];
  if (item.node) segments.splice(2, 0, item.node);
  return segments.filter(Boolean).join(" / ");
}

function formatEntryTitle(item) {
  const stageLabel = STAGE_LABELS[item.stage] ?? item.title ?? item.stage ?? "未命名阶段";
  return item.node ? `${item.node} / ${stageLabel}` : stageLabel;
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
    return `${task.last_run.metric_name}: ${formatMetricValue(task.last_run.metric_value)}`;
  }
  if (task?.status === "failed" && task?.notes) return "最近一次运行失败";
  return "还没有运行结果";
}

function getConversationCountLabel(count) {
  return count ? `${count} 组` : "0 组";
}

function getInternalStateCountLabel(count) {
  return count ? `${count} 条` : "0 条";
}

function getInteractiveCountLabel(count) {
  return count ? `${count} 条` : "0 条";
}

function formatTokenUsage(usage) {
  if (!usage || typeof usage.total_tokens !== "number") return "未记录";
  return `${usage.total_tokens} tokens`;
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
    title: "确认 AI 对话中的关键问题",
    summary: prompt,
    suggested_action: assistantMessage?.content
      ? `请结合最近一次 AI 回复判断是否需要转成显式修改要求：\n${clipText(assistantMessage.content)}`
      : "请人工判断这个问题是否需要转成显式修改要求，然后再决定是否继续。",
    artifact_paths: [],
    notice: "已把当前对话里的问题带入协同请求表单。",
  };
}

function getInteractiveMessageMeta(message) {
  if (message.role === "user") return "你的 prompt";
  if (message.status === "error") return "连接器错误";
  return "当前连接器回复";
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
  const [activeView, setActiveView] = useState("chat");

  useEffect(() => {
    setDraftPrompt("");
  }, [selectedTask?.id]);

  const items = Array.isArray(conversationData?.items) ? conversationData.items : [];
  const interactiveMessages = Array.isArray(conversationData?.interactive_messages) ? conversationData.interactive_messages : [];
  const internalStates = Array.isArray(conversationData?.internal_states) ? conversationData.internal_states : [];
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
            <p className="eyebrow">Conversation</p>
            <h3>{selectedTask?.name ?? "选择任务"}</h3>
            {selectedTask ? (
              <span className={`runtime-pill ${formatTaskStatusTone(selectedTask.status)}`}>
                {formatTaskStatus(selectedTask.status)}
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
              <ConversationMetric label="系统日志" value={getConversationCountLabel(items.length)} />
              <ConversationMetric label="手动聊天" value={getInteractiveCountLabel(interactiveMessages.length)} />
              <ConversationMetric label="内部状态" value={getInternalStateCountLabel(internalStates.length)} />
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
            <div className="ai-chat-tabs" role="tablist" aria-label="AI 对话视图">
              <button
                type="button"
                className={cx("ai-chat-tab", activeView === "chat" && "active")}
                onClick={() => setActiveView("chat")}
              >
                手动对话 <span>{getInteractiveCountLabel(interactiveMessages.length)}</span>
              </button>
              <button
                type="button"
                className={cx("ai-chat-tab", activeView === "system" && "active")}
                onClick={() => setActiveView("system")}
              >
                系统日志 <span>{getConversationCountLabel(items.length)}</span>
              </button>
              <button
                type="button"
                className={cx("ai-chat-tab", activeView === "states" && "active")}
                onClick={() => setActiveView("states")}
              >
                内部状态 <span>{getInternalStateCountLabel(internalStates.length)}</span>
              </button>
            </div>
          </div>

          {error ? <div className="error-banner ai-chat-inline-error">{error}</div> : null}

          {!selectedTask ? (
            <div className="empty-state ai-chat-empty">先选择一个任务。</div>
          ) : null}

          {selectedTask && activeView === "chat" ? (
            <div className="ai-chat-panel ai-chat-thread-panel">
              <div className="ai-chat-thread" aria-live="polite">
                {!interactiveMessages.length ? (
                  <div className="empty-state ai-chat-empty">
                    {chatSending ? "正在等待 AI 回复..." : "还没有手动聊天记录。"}
                  </div>
                ) : (
                  interactiveMessages.map((message) => {
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
                            <pre>{getMessageText(message.content)}</pre>
                            {message.composed_prompt ? (
                              <details className="ai-chat-raw">
                                <summary>完整上下文</summary>
                                <pre>{getMessageText(message.composed_prompt)}</pre>
                              </details>
                            ) : null}
                          </div>
                          {!isUser ? (
                            <div className="ai-chat-tokenline">
                              {message.model_name ? <span>Model: {message.model_name}</span> : null}
                              <span>Token: {formatTokenUsage(message.token_usage)}</span>
                            </div>
                          ) : null}
                        </div>
                      </article>
                    );
                  })
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
                    转成人机协同
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

          {selectedTask && activeView === "system" ? (
            <div className="ai-chat-panel ai-log-panel">
              {!items.length ? (
                <div className="empty-state ai-chat-empty">
                  {loading ? "正在读取系统日志..." : "这个任务暂时还没有系统 prompt / response 记录。"}
                </div>
              ) : (
                <div className="ai-system-turn-list">
                  {items.map((item, index) => (
                    <details key={item.id} className="ai-system-turn" open={index === 0}>
                      <summary>
                        <div>
                          <strong>{formatEntryTitle(item)}</strong>
                          <span>{getTurnMeta(item, index)}</span>
                        </div>
                        <time>{formatDateTime(item.created_at)}</time>
                      </summary>
                      <div className="ai-system-turn-grid">
                        <article className="ai-system-block prompt">
                          <div className="ai-system-block-head">
                            <strong>Prompt</strong>
                            <span>{PROMPT_EXPLANATIONS[item.stage] ?? "当前阶段原始提示词。"}</span>
                          </div>
                          <pre>{getMessageText(item.prompt)}</pre>
                          {item.prompt_path ? <p className="ai-filepath">{item.prompt_path}</p> : null}
                        </article>
                        <article className="ai-system-block response">
                          <div className="ai-system-block-head">
                            <strong>{formatOrigin(item.origin)}</strong>
                            <span>{getResponseNote(item.origin)}</span>
                          </div>
                          <pre>{getMessageText(item.response)}</pre>
                          {item.response_path ? <p className="ai-filepath">{item.response_path}</p> : null}
                          <span className={`runtime-pill ${getOriginTone(item.origin)}`}>{formatOrigin(item.origin)}</span>
                        </article>
                      </div>
                    </details>
                  ))}
                </div>
              )}
            </div>
          ) : null}

          {selectedTask && activeView === "states" ? (
            <div className="ai-chat-panel ai-state-panel">
              {!internalStates.length ? (
                <div className="empty-state ai-chat-empty">当前运行目录里还没有可展示的内部状态文件。</div>
              ) : (
                <div className="ai-state-list">
                  {internalStates.map((item) => (
                    <details key={item.id} className="ai-state-card">
                      <summary>
                        <div>
                          <strong>{item.title}</strong>
                          <span>
                            {[item.node ?? "runtime", formatInternalStateCategory(item.category), formatDateTime(item.created_at)].join(" / ")}
                          </span>
                        </div>
                        <span className="runtime-pill warning">{formatInternalStateCategory(item.category)}</span>
                      </summary>
                      <div className="ai-state-content">
                        {item.description ? <p>{item.description}</p> : null}
                        <p className="ai-filepath">{item.path}</p>
                        <pre>{getMessageText(item.content)}</pre>
                      </div>
                    </details>
                  ))}
                </div>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
