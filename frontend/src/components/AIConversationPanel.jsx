import { useEffect, useState } from "react";

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
  ai_model: "info",
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
  task_analysis: "这是任务解析阶段发给模型的提示词，用来识别目标列、任务类型和建议指标。",
  python_coder: "这是让模型生成或修复训练脚本的提示词。",
  bash_coder: "这是生成执行包装脚本的提示词，用来真正把代码在本机跑起来。",
  executer: "这是执行评估阶段的提示词，用来判断本轮运行是否成功。",
  error_analyzer: "这是错误分析阶段的提示词，用来总结失败原因，指导下一轮修复。",
  chat: "这是补充说明或辅助对话阶段的提示词。",
};

const TASK_STATUS_LABELS = {
  draft: "草稿",
  uploaded: "已上传数据集",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
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
  if (value === "local_runtime") return "这条回复来自本地运行逻辑，不是远端模型直接返回。";
  if (value === "ai_model") return "这是一条真实的模型调用记录。";
  return "当前无法完全确定这条响应的来源。";
}

function getTurnMeta(item) {
  const segments = [formatPhase(item.phase)];
  if (item.node) segments.push(item.node);
  if (item.stage) segments.push(item.stage);
  return segments.join(" / ");
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
  if (!count) return "还没有系统问答";
  return `${count} 组系统问答`;
}

function getInternalStateCountLabel(count) {
  if (!count) return "还没有内部状态";
  return `${count} 条内部状态`;
}

function getInteractiveCountLabel(count) {
  if (!count) return "还没有手动聊天";
  return `${count} 条手动消息`;
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

function buildConversationStream(items) {
  return items.flatMap((item, index) => {
    const marker = {
      type: "marker",
      id: `${item.id}-marker`,
      title: formatEntryTitle(item),
      meta: getTurnMeta(item),
      time: formatDateTime(item.created_at),
    };

    const prompt = {
      type: "message",
      id: `${item.id}-prompt`,
      align: "prompt",
      avatar: "P",
      title: "系统 Prompt",
      subtitle: `发送到 ${formatPhase(item.phase)}`,
      body: getMessageText(item.prompt),
      explanation: PROMPT_EXPLANATIONS[item.stage] ?? "这是当前阶段发给模型或运行时的原始提示词。",
      bubbleTone: "prompt",
      markerLabel: `Round ${index + 1}`,
    };

    const response = {
      type: "message",
      id: `${item.id}-response`,
      align: "response",
      avatar: getOriginAvatar(item.origin),
      title: formatOrigin(item.origin),
      subtitle: getResponseNote(item.origin),
      body: getMessageText(item.response),
      bubbleTone: item.origin === "local_runtime" ? "runtime" : "response",
      files: [
        item.prompt_path ? `Prompt file: ${item.prompt_path}` : null,
        item.response_path ? `Response file: ${item.response_path}` : null,
      ].filter(Boolean),
      originTone: getOriginTone(item.origin),
      time: formatDateTime(item.created_at),
    };

    return [marker, prompt, response];
  });
}

function getInteractiveMessageMeta(message) {
  if (message.role === "user") return "你手动输入的 prompt";
  if (message.status === "error") return "系统把连接器调用错误直接暴露出来，方便你排查";
  return "当前激活连接器返回的真实回复";
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

  useEffect(() => {
    setDraftPrompt("");
  }, [selectedTask?.id]);

  const items = Array.isArray(conversationData?.items) ? conversationData.items : [];
  const interactiveMessages = Array.isArray(conversationData?.interactive_messages) ? conversationData.interactive_messages : [];
  const internalStates = Array.isArray(conversationData?.internal_states) ? conversationData.internal_states : [];
  const warnings = Array.isArray(conversationData?.warnings) ? conversationData.warnings : [];
  const taskItems = Array.isArray(tasks) ? tasks : [];
  const streamItems = buildConversationStream(items);
  const latestAssistantMessage = [...interactiveMessages].reverse().find((message) => message.role === "assistant") ?? null;

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

  return (
    <section className="section-card conversation-page-card">
      {!taskItems.length && !tasksLoading ? (
        <div className="empty-state">当前团队还没有任务。先去任务页创建并上传 CSV。</div>
      ) : null}

      {taskItems.length ? (
        <div className="conversation-page-shell">
          <div className="conversation-page-toolbar">
            <div className="conversation-page-intro">
              <p className="eyebrow">Interactive Chat</p>
              <h3>{selectedTask?.name ?? "选择一个任务"}</h3>
              <p>这里分成两层：上面是你可以自己写 prompt 的真实聊天区，下面是系统内部的 MLZero prompt / response 日志。</p>
            </div>

            <div className="conversation-page-actions">
              <label className="conversation-task-picker">
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
                <span className={`runtime-pill ${selectedTask.status === "failed" ? "danger" : selectedTask.status === "completed" ? "success" : "info"}`}>
                  {formatTaskStatus(selectedTask.status)}
                </span>
              ) : null}

              {onOpenTaskDetails ? (
                <button type="button" className="ghost-button" onClick={onOpenTaskDetails}>
                  回到任务详情
                </button>
              ) : null}

              <button type="button" className="primary-button" onClick={onRefresh} disabled={loading}>
                {loading ? "刷新中..." : "刷新对话"}
              </button>
            </div>
          </div>

          {selectedTask ? (
            <div className="conversation-context-strip">
              <span className="conversation-context-pill">
                <strong>数据集</strong>
                <em>{selectedTask.dataset_filename ?? "未上传"}</em>
              </span>
              <span className="conversation-context-pill">
                <strong>任务类型</strong>
                <em>{formatProblemType(selectedTask.problem_type)}</em>
              </span>
              <span className="conversation-context-pill">
                <strong>最近结果</strong>
                <em>{buildResultSummary(selectedTask)}</em>
              </span>
              <span className="conversation-context-pill">
                <strong>系统日志</strong>
                <em>{getConversationCountLabel(items.length)}</em>
              </span>
              <span className="conversation-context-pill">
                <strong>手动聊天</strong>
                <em>{getInteractiveCountLabel(interactiveMessages.length)}</em>
              </span>
              <span className="conversation-context-pill">
                <strong>内部状态</strong>
                <em>{getInternalStateCountLabel(internalStates.length)}</em>
              </span>
            </div>
          ) : null}

          {error ? <div className="error-banner">{error}</div> : null}

          {warnings.length ? (
            <div className="callout conversation-warning">
              <strong>读取提醒</strong>
              <div className="conversation-warning-list">
                {warnings.map((warning, index) => (
                  <p key={`${warning}-${index}`}>{warning}</p>
                ))}
              </div>
            </div>
          ) : null}

          {!selectedTask ? (
            <div className="empty-state">先在上方选择一个任务，再查看它的 AI 对话记录。</div>
          ) : (
            <>
              <div className="conversation-window conversation-interactive-board">
                <div className="conversation-window-head">
                  <div>
                    <strong>与你自己的 AI 对话</strong>
                    <p>你可以直接写 prompt。系统会附带当前任务上下文和最近几轮聊天，再发送给当前激活的连接器。</p>
                  </div>
                  <span className="runtime-pill success">{getInteractiveCountLabel(interactiveMessages.length)}</span>
                </div>

                <form className="conversation-chat-form" onSubmit={handleSendPrompt}>
                  <textarea
                    className="conversation-chat-input"
                    rows={6}
                    value={draftPrompt}
                    onChange={(event) => setDraftPrompt(event.target.value)}
                    disabled={!selectedTask || chatSending}
                    placeholder="在这里直接写你的 prompt，例如：请根据当前任务，帮我判断目标列是否合理，并给出一版更好的训练提示词。"
                  />
                  <div className="conversation-chat-form-footer">
                    <p className="conversation-chat-helper">
                      这里输入的是你自己的 prompt。助手回复后，你还能展开查看系统实际发给模型的完整上下文。
                    </p>
                    <div className="conversation-chat-actions">
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
                        {chatSending ? "发送中..." : "发送 prompt"}
                      </button>
                    </div>
                  </div>
                </form>

                {chatError ? <div className="error-banner conversation-inline-banner">{chatError}</div> : null}

                {!interactiveMessages.length ? (
                  <div className="empty-state conversation-inline-empty">
                    {chatSending ? "正在等待 AI 回复..." : "还没有手动聊天记录。你现在就可以自己写 prompt。"}
                  </div>
                ) : (
                  <div className="conversation-window-scroll conversation-chat-scroll">
                    <div className="conversation-stream">
                      {interactiveMessages.map((message) => {
                        const align = message.role === "user" ? "prompt" : "response";
                        return (
                          <div key={message.id} className={cx("conversation-message-row", align)}>
                            <div className={cx("conversation-avatar", align === "prompt" ? "prompt" : "response")}>
                              {getInteractiveAvatar(message)}
                            </div>

                            <div className="conversation-message-shell">
                              <div className="conversation-message-meta">
                                <span>{formatDateTime(message.created_at)}</span>
                                <span className={`runtime-pill ${message.origin === "local_runtime" || message.status === "error" ? "warning" : align === "prompt" ? "info" : "success"}`}>
                                  {message.role === "user" ? "你的 prompt" : formatInteractiveOrigin(message.origin)}
                                </span>
                              </div>

                              <div className={cx("conversation-message-bubble", getInteractiveBubbleTone(message))}>
                                <div className="conversation-bubble-head">
                                  <strong>{message.role === "user" ? "你发出的 prompt" : formatInteractiveOrigin(message.origin)}</strong>
                                  <span>{getInteractiveMessageMeta(message)}</span>
                                </div>
                                <pre className="conversation-message-body">{getMessageText(message.content)}</pre>
                                {message.composed_prompt ? (
                                  <details className="conversation-raw-block">
                                    <summary>查看系统实际发送给模型的完整 prompt</summary>
                                    <pre className="conversation-message-body raw">{getMessageText(message.composed_prompt)}</pre>
                                  </details>
                                ) : null}
                              </div>

                              {message.role === "assistant" ? (
                                <div className="conversation-message-files">
                                  {message.model_name ? <p className="mono-text">Model: {message.model_name}</p> : null}
                                  <p className="mono-text">Token: {formatTokenUsage(message.token_usage)}</p>
                                </div>
                              ) : null}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>

              <div className="conversation-window">
                <div className="conversation-window-head">
                  <div>
                    <strong>系统内部 Prompt / Response 日志</strong>
                    <p>这里展示 MLZero 和任务解析过程里保存下来的系统日志。提示词默认先显示中文解释，原始英文放在折叠区。</p>
                  </div>
                  <span className="runtime-pill info">{getConversationCountLabel(items.length)}</span>
                </div>

                {!items.length ? (
                  <div className="empty-state conversation-inline-empty">
                    {loading ? "正在读取这个任务的系统对话日志..." : "这个任务暂时还没有保存下来的系统 prompt / response 记录。"}
                  </div>
                ) : (
                  <div className="conversation-window-scroll">
                    <div className="conversation-stream">
                      {streamItems.map((entry) => {
                        if (entry.type === "marker") {
                          return (
                            <div key={entry.id} className="conversation-marker">
                              <span className="conversation-marker-line" />
                              <div className="conversation-marker-content">
                                <strong>{entry.title}</strong>
                                <span>{entry.meta}</span>
                                <small>{entry.time}</small>
                              </div>
                              <span className="conversation-marker-line" />
                            </div>
                          );
                        }

                        return (
                          <div key={entry.id} className={cx("conversation-message-row", entry.align)}>
                            <div className={cx("conversation-avatar", entry.align === "prompt" ? "prompt" : "response")}>
                              {entry.avatar}
                            </div>

                            <div className="conversation-message-shell">
                              <div className="conversation-message-meta">
                                {entry.markerLabel ? <span>{entry.markerLabel}</span> : null}
                                {entry.time ? <span>{entry.time}</span> : null}
                                {entry.originTone ? <span className={`runtime-pill ${entry.originTone}`}>{entry.title}</span> : null}
                              </div>

                              <div className={cx("conversation-message-bubble", entry.bubbleTone)}>
                                <div className="conversation-bubble-head">
                                  <strong>{entry.title}</strong>
                                  <span>{entry.subtitle}</span>
                                </div>
                                {entry.explanation ? <p className="conversation-message-explanation">{entry.explanation}</p> : null}
                                {entry.align === "prompt" ? (
                                  <details className="conversation-raw-block">
                                    <summary>查看原始英文提示词</summary>
                                    <pre className="conversation-message-body raw">{entry.body}</pre>
                                  </details>
                                ) : (
                                  <pre className="conversation-message-body">{entry.body}</pre>
                                )}
                              </div>

                              {entry.files?.length ? (
                                <div className="conversation-message-files">
                                  {entry.files.map((file) => (
                                    <p key={file} className="mono-text">{file}</p>
                                  ))}
                                </div>
                              ) : null}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>

              <div className="conversation-state-board">
                <div className="conversation-state-board-head">
                  <div>
                    <strong>内部状态</strong>
                    <p>这里展示 MLZero 在检索、执行、修复和汇总过程中落盘的内部状态文件。</p>
                  </div>
                  <span className="runtime-pill warning">{getInternalStateCountLabel(internalStates.length)}</span>
                </div>

                {!internalStates.length ? (
                  <div className="empty-state compact">当前运行目录里还没有可展示的内部状态文件。</div>
                ) : (
                  <div className="conversation-state-list">
                    {internalStates.map((item) => (
                      <details key={item.id} className="conversation-state-card">
                        <summary className="conversation-state-summary">
                          <div className="conversation-state-summary-copy">
                            <strong>{item.title}</strong>
                            <span>
                              {[
                                item.node ?? "runtime",
                                formatInternalStateCategory(item.category),
                                formatDateTime(item.created_at),
                              ].join(" / ")}
                            </span>
                          </div>
                          <div className="conversation-state-summary-meta">
                            <span className="runtime-pill warning">{formatInternalStateCategory(item.category)}</span>
                            {item.node ? <span className="runtime-pill info">{item.node}</span> : null}
                          </div>
                        </summary>

                        <div className="conversation-state-content">
                          {item.description ? <p className="conversation-state-description">{item.description}</p> : null}
                          <p className="mono-text">{item.path}</p>
                          <pre className="conversation-state-body">{getMessageText(item.content)}</pre>
                        </div>
                      </details>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      ) : null}
    </section>
  );
}
