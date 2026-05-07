import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../lib/api.js";

const MAX_RENDERED_LINE_NUMBERS = 1200;
const MAX_VIEWER_PREVIEW_CHARS = 120_000;
const MAX_PREFETCH_ARTIFACTS = 2;

const CATEGORY_LABELS = {
  code: "代码",
  state: "过程",
  result: "结果",
  log: "日志",
  other: "其他",
};

const CATEGORY_TONES = {
  code: "success",
  state: "info",
  result: "warning",
  log: "warning",
  other: "info",
};

const FILTER_DEFINITIONS = [
  {
    id: "core",
    label: "核心文件",
    description: "默认只看最值得先打开的代码和结果文件。",
    match: (item) => Boolean(item.is_core),
  },
  {
    id: "generation",
    label: "代码生成过程",
    description: "查看 AI 写代码时的 Prompt、回复和中间状态。",
    match: (item) => item.group === "generation",
  },
  {
    id: "result",
    label: "运行结果",
    description: "查看摘要、预测输出和结构化结果文件。",
    match: (item) => item.group === "result",
  },
  {
    id: "log",
    label: "调试日志",
    description: "查看 stdout、stderr 和运行日志。",
    match: (item) => item.group === "log",
  },
  {
    id: "all",
    label: "全部工件",
    description: "展示最新运行目录里所有可读文本工件。",
    match: () => true,
  },
];

const GROUP_LABELS = {
  generation: "代码生成过程",
  result: "运行结果",
  log: "调试日志",
  context: "运行上下文",
  other: "其他工件",
};

const STAGE_LABELS = {
  final_code: "最终代码",
  python_draft: "Python 草稿",
  execution: "执行脚本",
  summary: "结果摘要",
  result_compare: "结果对比",
  predictions: "预测输出",
  usage: "Token 记录",
  python_coder: "写代码阶段",
  python_coder_retry: "代码重试",
  bash_coder: "脚本生成阶段",
  executor: "执行/自修复",
  repair: "报错分析",
  decision: "决策过程",
  task_setup: "任务理解",
  reader: "前置读取",
  retrieval: "教程检索",
  score: "节点分数",
  logs: "运行日志",
  context: "运行上下文",
  state: "过程状态",
  other: "其他",
};

const LANGUAGE_LABELS = {
  python: "Python",
  text: "Text",
  markdown: "Markdown",
  json: "JSON",
  csv: "CSV",
  yaml: "YAML",
  log: "Log",
  shell: "Shell",
  powershell: "PowerShell",
  batch: "Batch",
  sql: "SQL",
};

const GROUP_ORDER = ["generation", "result", "log", "context", "other"];

function formatDateTime(value) {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function formatBytes(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "未知大小";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(2)} MB`;
}

function hasRunArtifacts(task) {
  return Boolean(task?.last_run_attempt?.output_dir || task?.last_run?.output_dir);
}

function pickDefaultArtifactPath(items) {
  if (!Array.isArray(items) || !items.length) return "";
  const preferredNames = ["generated_code.py", "python_code.py", "execution_script.sh", "summary.txt"];
  for (const name of preferredNames) {
    const matched = items.find((item) => item.name === name);
    if (matched) return matched.path;
  }
  const firstCore = items.find((item) => item.is_core);
  if (firstCore) return firstCore.path;
  return items[0]?.path ?? "";
}

function buildLineNumbers(text) {
  const lineCount = Math.max(1, String(text ?? "").split("\n").length);
  const renderedLineCount = Math.min(lineCount, MAX_RENDERED_LINE_NUMBERS);
  return Array.from({ length: renderedLineCount }, (_item, index) => index + 1);
}

function getLineCount(text) {
  return Math.max(1, String(text ?? "").split("\n").length);
}

function getPreviewText(text, maxChars = MAX_VIEWER_PREVIEW_CHARS) {
  const value = String(text ?? "");
  if (value.length <= maxChars) return { text: value, truncated: false, omitted: 0 };
  return {
    text: value.slice(0, maxChars),
    truncated: true,
    omitted: value.length - maxChars,
  };
}

function rankArtifactForPrefetch(item) {
  if (item?.is_core) return item.recommended_order ?? 0;
  return 100 + (item?.recommended_order ?? 999);
}

function filterArtifacts(items, filterId) {
  const definition = FILTER_DEFINITIONS.find((item) => item.id === filterId) ?? FILTER_DEFINITIONS[0];
  return items.filter(definition.match);
}

function countArtifacts(items, filterId) {
  return filterArtifacts(items, filterId).length;
}

function groupArtifactsForSidebar(items, filterId) {
  if (filterId !== "all") {
    return [{ id: filterId, label: FILTER_DEFINITIONS.find((item) => item.id === filterId)?.label ?? "文件", items }];
  }

  return GROUP_ORDER
    .map((group) => ({
      id: group,
      label: GROUP_LABELS[group] ?? group,
      items: items.filter((item) => item.group === group),
    }))
    .filter((section) => section.items.length);
}

function inferHumanStageFromArtifact(item) {
  if (item?.group === "result") {
    return item?.stage === "summary" || item?.stage === "result_compare" || item?.stage === "predictions"
      ? "report_generation"
      : "training_validation";
  }
  if (item?.category === "log" || item?.stage === "execution" || item?.stage === "repair") return "training_validation";
  if (item?.category === "code" || item?.group === "generation") return "feature_engineering";
  if (item?.group === "context") return "data_analysis";
  return "requirement_analysis";
}

function inferHumanRequestTypeFromArtifact(item) {
  if (item?.category === "code") return "code_review";
  if (item?.group === "result" || item?.category === "result") return "result_review";
  if (item?.group === "context") return "data_review";
  return "requirement_review";
}

function buildHumanRequestPresetFromArtifact(artifact, runOutputDir) {
  const artifactPath = artifact?.path ? [artifact.path] : [];
  const runPathLine = runOutputDir ? `运行目录：${runOutputDir}` : "当前未记录运行目录。";
  return {
    stage: inferHumanStageFromArtifact(artifact),
    request_type: inferHumanRequestTypeFromArtifact(artifact),
    title: `审查文件：${artifact?.name ?? "当前工件"}`,
    summary: `请人工审查当前代码工作区里的 ${artifact?.display_name || artifact?.name || "工件"}。\n${runPathLine}`,
    suggested_action: artifact?.purpose
      ? `${artifact.purpose}\n请确认这个文件是否需要修改，确认后再决定是否继续下一轮运行。`
      : "请确认这个文件是否需要修改，确认后再决定是否继续下一轮运行。",
    artifact_paths: artifactPath,
    notice: "已把当前文件带入协同请求表单。",
  };
}

function FileListItem({ item, active, onSelect }) {
  const tone = CATEGORY_TONES[item.category] ?? "info";

  return (
    <button
      type="button"
      className={active ? "workspace-file active" : "workspace-file"}
      onClick={() => onSelect(item.path)}
    >
      <div className="workspace-file-copy">
        <strong className="workspace-file-name">{item.name}</strong>
        <span className="workspace-file-caption">{item.display_name || item.path}</span>
        <span className="workspace-file-path">{item.path}</span>
      </div>
      <div className="workspace-file-badges">
        {item.is_core ? <span className="runtime-pill success">核心</span> : null}
        <span className={`runtime-pill ${tone}`}>{CATEGORY_LABELS[item.category] ?? "文件"}</span>
      </div>
    </button>
  );
}

export default function CodeWorkspacePanel({
  tasks,
  tasksLoading,
  selectedTask,
  requestContext,
  onSelectTask,
  onOpenHumanCollaboration,
  onOpenTaskDetails,
}) {
  const [workspaceData, setWorkspaceData] = useState(null);
  const [workspaceState, setWorkspaceState] = useState("idle");
  const [workspaceError, setWorkspaceError] = useState("");
  const [activeFilter, setActiveFilter] = useState("core");
  const [activePath, setActivePath] = useState("");
  const [artifactData, setArtifactData] = useState(null);
  const [artifactState, setArtifactState] = useState("idle");
  const [artifactError, setArtifactError] = useState("");
  const [editorValue, setEditorValue] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saveState, setSaveState] = useState("idle");
  const [saveMessage, setSaveMessage] = useState("");
  const [downloadState, setDownloadState] = useState("idle");
  const [rerunState, setRerunState] = useState("idle");
  const [rerunResult, setRerunResult] = useState(null);
  const gutterRef = useRef(null);
  const artifactCacheRef = useRef(new Map());
  const artifactInFlightRef = useRef(new Map());

  const taskItems = Array.isArray(tasks) ? tasks : [];
  const artifactItems = Array.isArray(workspaceData?.items) ? workspaceData.items : [];
  const visibleArtifacts = useMemo(
    () => filterArtifacts(artifactItems, activeFilter),
    [activeFilter, artifactItems],
  );
  const sidebarSections = useMemo(
    () => groupArtifactsForSidebar(visibleArtifacts, activeFilter),
    [activeFilter, visibleArtifacts],
  );
  const activeArtifactEntry = useMemo(
    () => artifactItems.find((item) => item.path === activePath) ?? null,
    [activePath, artifactItems],
  );
  const lineNumbers = useMemo(() => buildLineNumbers(editorValue), [editorValue]);
  const lineCount = useMemo(() => getLineCount(editorValue), [editorValue]);
  const viewerPreview = useMemo(() => getPreviewText(editorValue), [editorValue]);
  const selectedTaskId = selectedTask?.id ?? "";
  const selectedTaskHasRun = hasRunArtifacts(selectedTask);
  const runScopeKey = workspaceData?.run_output_dir
    ?? selectedTask?.last_run_attempt?.output_dir
    ?? selectedTask?.last_run?.output_dir
    ?? "";
  const activeFilterMeta = FILTER_DEFINITIONS.find((item) => item.id === activeFilter) ?? FILTER_DEFINITIONS[0];
  const activeLanguageLabel = LANGUAGE_LABELS[artifactData?.artifact?.language] ?? artifactData?.artifact?.language ?? "未识别";
  const activeCategoryLabel = CATEGORY_LABELS[artifactData?.artifact?.category] ?? "文件";
  const activeCategoryTone = CATEGORY_TONES[artifactData?.artifact?.category] ?? "info";
  const activeStageLabel = artifactData?.artifact?.stage ? (STAGE_LABELS[artifactData.artifact.stage] ?? artifactData.artifact.stage) : "";
  const canEditActiveArtifact = Boolean(artifactData?.artifact?.editable);
  const canRerunActiveArtifact = artifactData?.artifact?.category === "code" && artifactData?.artifact?.language === "python";

  function buildArtifactCacheKey(taskId, path, runOutputDir) {
    return `${taskId}::${runOutputDir}::${path}`;
  }

  function clearTaskCache(taskId) {
    for (const key of Array.from(artifactCacheRef.current.keys())) {
      if (key.startsWith(`${taskId}::`)) {
        artifactCacheRef.current.delete(key);
      }
    }
  }

  function fetchArtifactPayload(taskId, path) {
    const cacheKey = buildArtifactCacheKey(taskId, path, runScopeKey);
    const cached = artifactCacheRef.current.get(cacheKey);
    if (cached) return Promise.resolve(cached);

    const inFlight = artifactInFlightRef.current.get(cacheKey);
    if (inFlight) return inFlight;

    const request = api.taskCodeArtifact(taskId, path, requestContext)
      .then((payload) => {
        artifactCacheRef.current.set(cacheKey, payload);
        return payload;
      })
      .finally(() => {
        artifactInFlightRef.current.delete(cacheKey);
      });

    artifactInFlightRef.current.set(cacheKey, request);
    return request;
  }

  useEffect(() => {
    if (!selectedTaskId || !requestContext?.accessToken || !requestContext?.teamId || !selectedTaskHasRun) {
      setWorkspaceData(null);
      setWorkspaceState("idle");
      setWorkspaceError("");
      setActiveFilter("core");
      setActivePath("");
      setArtifactData(null);
      setArtifactState("idle");
      setArtifactError("");
      setEditorValue("");
      setDirty(false);
      setSaveState("idle");
      setSaveMessage("");
      setDownloadState("idle");
      setRerunState("idle");
      setRerunResult(null);
      return;
    }

    let active = true;
    setWorkspaceState("loading");
    setWorkspaceError("");
    setSaveMessage("");
    setRerunResult(null);
    setArtifactError("");

    api.taskCodeWorkspace(selectedTaskId, requestContext)
      .then((payload) => {
        if (!active) return;
        const nextItems = Array.isArray(payload?.items) ? payload.items : [];
        setWorkspaceData(payload);
        setWorkspaceState("ready");
        setActiveFilter(nextItems.some((item) => item.is_core) ? "core" : "all");
      })
      .catch((error) => {
        if (!active) return;
        setWorkspaceData(null);
        setWorkspaceState("ready");
        setWorkspaceError(error instanceof Error ? error.message : String(error));
      });

    return () => {
      active = false;
    };
  }, [
    requestContext,
    selectedTask?.id,
    selectedTask?.last_run?.output_dir,
    selectedTask?.last_run_attempt?.output_dir,
    selectedTaskHasRun,
    selectedTaskId,
  ]);

  useEffect(() => {
    if (!selectedTaskId || !runScopeKey || !artifactItems.length || !requestContext?.accessToken || !requestContext?.teamId) {
      return;
    }

    const candidates = [...artifactItems]
      .sort((left, right) => rankArtifactForPrefetch(left) - rankArtifactForPrefetch(right))
      .slice(0, MAX_PREFETCH_ARTIFACTS);

    for (const item of candidates) {
      const cacheKey = buildArtifactCacheKey(selectedTaskId, item.path, runScopeKey);
      if (artifactCacheRef.current.has(cacheKey) || artifactInFlightRef.current.has(cacheKey)) {
        continue;
      }
      void fetchArtifactPayload(selectedTaskId, item.path);
    }
  }, [artifactItems, requestContext, runScopeKey, selectedTaskId]);

  useEffect(() => {
    if (!artifactItems.length) {
      setActivePath("");
      setArtifactData(null);
      setArtifactState("idle");
      setArtifactError("");
      setEditorValue("");
      setDirty(false);
      return;
    }

    if (!visibleArtifacts.length) {
      setActivePath("");
      setArtifactData(null);
      setArtifactState("idle");
      setArtifactError("");
      setEditorValue("");
      setDirty(false);
      return;
    }

    if (!activePath || !visibleArtifacts.some((item) => item.path === activePath)) {
      setActivePath(pickDefaultArtifactPath(visibleArtifacts));
    }
  }, [activePath, artifactItems, visibleArtifacts]);

  useEffect(() => {
    if (!selectedTaskId || !activePath || !requestContext?.accessToken || !requestContext?.teamId) {
      setArtifactData(null);
      setArtifactState("idle");
      setArtifactError("");
      setEditorValue("");
      setDirty(false);
      return;
    }

    let active = true;
    setArtifactError("");
    setSaveMessage("");

    const cacheKey = buildArtifactCacheKey(selectedTaskId, activePath, runScopeKey);
    const cached = artifactCacheRef.current.get(cacheKey);
    if (cached) {
      setArtifactData(cached);
      setArtifactState("ready");
      setEditorValue(cached.content ?? "");
      setDirty(false);
      setSaveState("idle");
      return () => {
        active = false;
      };
    }

    setArtifactState("loading");
    setArtifactData(null);
    setEditorValue("");
    setDirty(false);

    fetchArtifactPayload(selectedTaskId, activePath)
      .then((payload) => {
        if (!active) return;
        setArtifactData(payload);
        setArtifactState("ready");
        setEditorValue(payload.content ?? "");
        setDirty(false);
        setSaveState("idle");
      })
      .catch((error) => {
        if (!active) return;
        setArtifactData(null);
        setArtifactState("ready");
        setArtifactError(error instanceof Error ? error.message : String(error));
        setEditorValue("");
        setDirty(false);
      });

    return () => {
      active = false;
    };
  }, [activePath, requestContext, runScopeKey, selectedTaskId]);

  function ensureDiscardChanges() {
    if (!dirty) return true;
    return window.confirm("当前文件还有未保存修改，确认要放弃这些更改吗？");
  }

  function handleSelectTask(nextTaskId) {
    if (!ensureDiscardChanges()) return;
    onSelectTask?.(nextTaskId);
  }

  function handleSelectPath(nextPath) {
    if (nextPath === activePath) return;
    if (!ensureDiscardChanges()) return;
    setActivePath(nextPath);
  }

  function handleSelectFilter(nextFilter) {
    if (nextFilter === activeFilter) return;
    if (!ensureDiscardChanges()) return;
    setActiveFilter(nextFilter);
  }

  function handleRefresh() {
    if (!ensureDiscardChanges()) return;
    if (!selectedTaskId) return;

    clearTaskCache(selectedTaskId);
    setWorkspaceData((current) => (current ? { ...current, items: [] } : current));
    setActivePath("");
    setArtifactData(null);
    setArtifactError("");
    setSaveMessage("");
    setRerunResult(null);
    setWorkspaceState("loading");

    api.taskCodeWorkspace(selectedTaskId, requestContext)
      .then((payload) => {
        const nextItems = Array.isArray(payload?.items) ? payload.items : [];
        setWorkspaceData(payload);
        setWorkspaceState("ready");
        setActiveFilter(nextItems.some((item) => item.is_core) ? "core" : "all");
      })
      .catch((error) => {
        setWorkspaceData(null);
        setWorkspaceState("ready");
        setWorkspaceError(error instanceof Error ? error.message : String(error));
      });
  }

  function handleEditorChange(event) {
    setEditorValue(event.target.value);
    setDirty(true);
    setSaveMessage("");
  }

  function handleEditorScroll(event) {
    if (!gutterRef.current) return;
    gutterRef.current.scrollTop = event.target.scrollTop;
  }

  async function handleSave() {
    if (!selectedTaskId || !activePath || !artifactData?.artifact?.editable || saveState === "saving") return;
    setSaveState("saving");
    setSaveMessage("");
    try {
      const payload = await api.updateTaskCodeArtifact(
        selectedTaskId,
        { path: activePath, content: editorValue },
        requestContext,
      );
      artifactCacheRef.current.set(buildArtifactCacheKey(selectedTaskId, activePath, runScopeKey), payload);
      setArtifactData(payload);
      setEditorValue(payload.content ?? "");
      setDirty(false);
      setSaveState("saved");
      setSaveMessage(payload.version_id ? `已保存到本次运行目录，版本 ${payload.version_id}。` : "已保存到本次运行目录。");
      setWorkspaceData((current) => {
        if (!current) return current;
        return {
          ...current,
          items: current.items.map((item) => (item.path === payload.artifact.path ? payload.artifact : item)),
        };
      });
    } catch (error) {
      setSaveState("idle");
      setSaveMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function handleDownload() {
    if (!selectedTaskId || !activePath || downloadState === "loading") return;
    setDownloadState("loading");
    setSaveMessage("");
    try {
      const payload = await api.downloadTaskCodeArtifact(selectedTaskId, activePath, requestContext);
      const url = URL.createObjectURL(payload.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = payload.filename || artifactData?.artifact?.name || "artifact";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setDownloadState("idle");
    }
  }

  async function handleRerunArtifact() {
    if (!selectedTaskId || !activePath || !canRerunActiveArtifact || rerunState === "loading") return;
    if (dirty) {
      setSaveMessage("请先保存当前文件，再重跑代码工件。");
      return;
    }
    setRerunState("loading");
    setRerunResult(null);
    setSaveMessage("");
    try {
      const payload = await api.rerunTaskCodeArtifact(
        selectedTaskId,
        { path: activePath, time_limit_seconds: 300 },
        requestContext,
      );
      setRerunResult(payload);
      setSaveMessage(payload.detail);
      clearTaskCache(selectedTaskId);
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setRerunState("idle");
    }
  }

  function handleCreateHumanRequestDraft() {
    if (!selectedTaskId || !activeArtifactEntry || !onOpenHumanCollaboration) return;
    if (dirty) {
      setSaveState("idle");
      setSaveMessage("请先保存当前文件，再把它提交到人机协同。");
      return;
    }
    onOpenHumanCollaboration(
      selectedTaskId,
      buildHumanRequestPresetFromArtifact(activeArtifactEntry, workspaceData?.run_output_dir ?? runScopeKey),
    );
  }

  return (
    <section className="section-card code-workspace-card">
      {tasksLoading && !taskItems.length ? (
        <div className="empty-state">正在读取任务和代码工作区入口...</div>
      ) : null}

      {!taskItems.length && !tasksLoading ? (
        <div className="empty-state">当前团队还没有任务。先在任务页创建任务并跑出一次 MLZero 结果。</div>
      ) : null}

      {taskItems.length ? (
        <div className="code-workspace-shell">
          <div className="code-workspace-toolbar">
            <div className="code-workspace-intro">
              <p className="eyebrow">Code Workspace</p>
              <h3>{selectedTask?.name ?? "选择一个任务"}</h3>
              <p>这里直接读取最新一次 MLZero 运行目录里的真实文件。现在默认只展示核心文件，不会把所有中间工件一股脑摊出来；切到“全部工件”时才会看到完整文本工件列表。</p>
            </div>

            <div className="code-workspace-actions">
              <label className="conversation-task-picker">
                <span>当前任务</span>
                <select
                  value={selectedTaskId}
                  onChange={(event) => handleSelectTask(event.target.value)}
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
                  {selectedTask.status}
                </span>
              ) : null}

              {onOpenTaskDetails ? (
                <button type="button" className="ghost-button" onClick={onOpenTaskDetails}>
                  回到任务详情
                </button>
              ) : null}

              <button
                type="button"
                className="ghost-button"
                onClick={handleRefresh}
                disabled={!selectedTaskId || workspaceState === "loading"}
              >
                {workspaceState === "loading" ? "刷新中..." : "刷新工作区"}
              </button>

              <button
                type="button"
                className="ghost-button"
                onClick={handleCreateHumanRequestDraft}
                disabled={!selectedTaskId || !activeArtifactEntry}
              >
                审阅当前文件
              </button>

              <button
                type="button"
                className="ghost-button"
                onClick={() => void handleDownload()}
                disabled={!selectedTaskId || !activePath || downloadState === "loading"}
              >
                {downloadState === "loading" ? "下载中..." : "下载当前文件"}
              </button>

              <button
                type="button"
                className="primary-button"
                onClick={() => void handleSave()}
                disabled={!canEditActiveArtifact || !dirty || saveState === "saving"}
              >
                {saveState === "saving" ? "保存中..." : "保存修改"}
              </button>

              <button
                type="button"
                className="primary-button"
                onClick={() => void handleRerunArtifact()}
                disabled={!selectedTaskId || !canRerunActiveArtifact || rerunState === "loading"}
              >
                {rerunState === "loading" ? "重跑中..." : "重跑当前代码"}
              </button>
            </div>
          </div>

          <div className="conversation-context-strip code-workspace-context">
            <span className="conversation-context-pill">
              <strong>最新运行目录</strong>
              <em>{workspaceData?.run_output_dir ?? selectedTask?.last_run_attempt?.output_dir ?? selectedTask?.last_run?.output_dir ?? "暂无"}</em>
            </span>
            <span className="conversation-context-pill">
              <strong>当前视图</strong>
              <em>{activeFilterMeta.label} · {visibleArtifacts.length}/{artifactItems.length}</em>
            </span>
            <span className="conversation-context-pill">
              <strong>当前文件</strong>
              <em>{activeArtifactEntry?.name ?? "未选择"}</em>
            </span>
            <span className="conversation-context-pill">
              <strong>编辑状态</strong>
              <em>{canEditActiveArtifact ? (dirty ? "有未保存修改" : "可编辑") : "只读"}</em>
            </span>
          </div>

          {saveMessage ? <div className={saveState === "saved" || rerunResult?.success ? "notice-banner" : "error-banner"}>{saveMessage}</div> : null}
          {rerunResult ? (
            <div className="callout">
              <strong>最近一次代码重跑</strong>
              <p>退出码：{rerunResult.exit_code}；stdout：<span className="mono-text">{rerunResult.stdout_path}</span>；stderr：<span className="mono-text">{rerunResult.stderr_path}</span></p>
            </div>
          ) : null}
          {workspaceError ? <div className="error-banner">{workspaceError}</div> : null}
          {artifactError ? <div className="error-banner">{artifactError}</div> : null}
          {Array.isArray(workspaceData?.warnings) && workspaceData.warnings.length ? (
            <div className="callout conversation-warning">
              <strong>读取提醒</strong>
              <div className="conversation-warning-list">
                {workspaceData.warnings.map((warning, index) => <p key={`${warning}-${index}`}>{warning}</p>)}
              </div>
            </div>
          ) : null}

          {!selectedTask ? (
            <div className="empty-state">先在上方选择一个任务，再查看它的 AI 代码工作区。</div>
          ) : !selectedTaskHasRun ? (
            <div className="empty-state">这个任务还没有跑出 MLZero 运行目录。先完成一次运行，代码工作区才会有真实文件。</div>
          ) : (
            <div className="code-workspace-layout">
              <aside className="code-workspace-sidebar">
                <div className="workspace-sidebar-tools">
                  <div className="code-workspace-sidebar-head">
                    <strong>文件视图</strong>
                    <span>{workspaceState === "loading" ? "读取中..." : `${visibleArtifacts.length} 个`}</span>
                  </div>

                  <div className="workspace-filter-bar">
                    {FILTER_DEFINITIONS.map((filter) => (
                      <button
                        key={filter.id}
                        type="button"
                        className={filter.id === activeFilter ? "workspace-filter-pill active" : "workspace-filter-pill"}
                        onClick={() => handleSelectFilter(filter.id)}
                      >
                        <span>{filter.label}</span>
                        <strong>{countArtifacts(artifactItems, filter.id)}</strong>
                      </button>
                    ))}
                  </div>

                  <div className="workspace-filter-note">
                    <strong>{activeFilterMeta.label}</strong>
                    <span>{activeFilterMeta.description}</span>
                  </div>
                </div>

                {!visibleArtifacts.length && workspaceState !== "loading" ? (
                  <div className="empty-state compact">当前视图下没有可展示的文件。你可以切到“全部工件”看看完整文本工件列表。</div>
                ) : (
                  <div className="code-workspace-tree">
                    {sidebarSections.map((section) => (
                      <section key={section.id} className="workspace-section">
                        {activeFilter === "all" ? (
                          <div className="workspace-section-head">
                            <strong>{section.label}</strong>
                            <span>{section.items.length}</span>
                          </div>
                        ) : null}
                        <div className="workspace-section-list">
                          {section.items.map((item) => (
                            <FileListItem
                              key={item.path}
                              item={item}
                              active={item.path === activePath}
                              onSelect={handleSelectPath}
                            />
                          ))}
                        </div>
                      </section>
                    ))}
                  </div>
                )}
              </aside>

              <div className="code-workspace-editor-panel">
                {!activeArtifactEntry ? (
                  <div className="empty-state code-workspace-empty">
                    {artifactState === "loading" ? "正在读取文件内容..." : "从左侧选择一个文件来查看 AI 代码或相关工件。"}
                  </div>
                ) : (
                  <>
                    <div className="code-workspace-filecard">
                      <div className="code-workspace-filecard-copy">
                        <p className="eyebrow">当前文件说明</p>
                        <h4>{activeArtifactEntry.display_name || activeArtifactEntry.name}</h4>
                        <p>{activeArtifactEntry.purpose || "当前没有额外说明。"}</p>
                      </div>
                      <div className="code-workspace-filecard-tags">
                        {activeArtifactEntry.is_core ? <span className="runtime-pill success">核心文件</span> : null}
                        <span className={`runtime-pill ${activeCategoryTone}`}>{activeCategoryLabel}</span>
                        <span className="runtime-pill">{GROUP_LABELS[activeArtifactEntry.group] ?? activeArtifactEntry.group}</span>
                        {activeArtifactEntry.node ? <span className="runtime-pill">{activeArtifactEntry.node}</span> : null}
                        {activeArtifactEntry.stage ? <span className="runtime-pill">{STAGE_LABELS[activeArtifactEntry.stage] ?? activeArtifactEntry.stage}</span> : null}
                        <span className={`runtime-pill ${canEditActiveArtifact ? "success" : "info"}`}>{canEditActiveArtifact ? "可编辑" : "只读"}</span>
                      </div>
                      <div className="workspace-guidance">
                        <strong>怎么用</strong>
                        <p>{activeArtifactEntry.editing_guidance || "当前没有额外的编辑提示。"}</p>
                      </div>
                    </div>

                    <div className="code-workspace-tabbar">
                      <div className="code-workspace-tab active">
                        <span>{activeArtifactEntry.name}</span>
                        {dirty ? <i className="code-workspace-dirty-dot" aria-hidden="true" /> : null}
                      </div>
                    </div>

                    <div className="code-workspace-filemeta">
                      <span className={`runtime-pill ${activeCategoryTone}`}>{activeCategoryLabel}</span>
                      <span className="runtime-pill">{activeLanguageLabel}</span>
                      {activeStageLabel ? <span className="runtime-pill">{activeStageLabel}</span> : null}
                      <span className="runtime-pill">{formatBytes(activeArtifactEntry.size_bytes)}</span>
                      <span className="runtime-pill">{formatDateTime(activeArtifactEntry.updated_at)}</span>
                      {artifactData?.version_id ? <span className="runtime-pill success">版本 {artifactData.version_id}</span> : null}
                      {Array.isArray(artifactData?.version_history) && artifactData.version_history.length ? <span className="runtime-pill info">{artifactData.version_history.length} 个保存版本</span> : null}
                      <span className="workspace-filepath">{activeArtifactEntry.path}</span>
                    </div>

                    {!artifactData ? (
                      <div className="empty-state code-workspace-empty">
                        {artifactState === "loading" ? "正在读取文件内容..." : "暂时没有读到这个文件的内容。"}
                      </div>
                    ) : canEditActiveArtifact ? (
                      <div className="code-editor-shell">
                        <div ref={gutterRef} className="code-editor-gutter" aria-hidden="true">
                          {lineNumbers.map((lineNumber) => <span key={lineNumber}>{lineNumber}</span>)}
                          {lineCount > MAX_RENDERED_LINE_NUMBERS ? <span>...</span> : null}
                        </div>
                        <textarea
                          className="code-editor-input"
                          spellCheck="false"
                          value={editorValue}
                          onChange={handleEditorChange}
                          onScroll={handleEditorScroll}
                        />
                      </div>
                    ) : (
                      <div className="code-viewer-shell">
                        <div className="code-viewer-gutter" aria-hidden="true">
                          {lineNumbers.map((lineNumber) => <span key={lineNumber}>{lineNumber}</span>)}
                          {lineCount > MAX_RENDERED_LINE_NUMBERS ? <span>...</span> : null}
                        </div>
                        <pre className="code-viewer-pre">{viewerPreview.text}</pre>
                        {viewerPreview.truncated ? (
                          <div className="large-content-notice">
                            文件较大，已先预览前 {MAX_VIEWER_PREVIEW_CHARS.toLocaleString("zh-CN")} 个字符，省略 {viewerPreview.omitted.toLocaleString("zh-CN")} 个字符。需要完整内容可下载工件。
                          </div>
                        ) : null}
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
