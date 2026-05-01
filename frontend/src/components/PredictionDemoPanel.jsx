import { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api.js";

function buildSampleFeatures(task) {
  const profile = task?.structured_requirements?.dataset_profile;
  const preview = Array.isArray(profile?.preview_rows) ? profile.preview_rows[0] : null;
  if (preview && typeof preview === "object") {
    const next = { ...preview };
    if (task?.label_column) delete next[task.label_column];
    return next;
  }
  return {};
}

function formatJson(value) {
  return JSON.stringify(value ?? {}, null, 2);
}

export default function PredictionDemoPanel({
  tasks,
  tasksLoading,
  selectedTask,
  requestContext,
  onSelectTask,
}) {
  const [featuresText, setFeaturesText] = useState("{}");
  const [response, setResponse] = useState(null);
  const [state, setState] = useState("idle");
  const [error, setError] = useState("");

  const taskItems = Array.isArray(tasks) ? tasks : [];
  const sampleFeatures = useMemo(() => buildSampleFeatures(selectedTask), [selectedTask]);

  useEffect(() => {
    setFeaturesText(formatJson(sampleFeatures));
    setResponse(null);
    setError("");
    setState("idle");
  }, [sampleFeatures, selectedTask?.id]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!selectedTask?.id) return;
    setState("loading");
    setError("");
    setResponse(null);
    let features;
    try {
      features = JSON.parse(featuresText);
    } catch (parseError) {
      setState("ready");
      setError(parseError instanceof Error ? `JSON 解析失败：${parseError.message}` : "JSON 解析失败。");
      return;
    }
    if (!features || Array.isArray(features) || typeof features !== "object") {
      setState("ready");
      setError("请输入单行预测所需的 JSON 对象，不能是数组或空值。");
      return;
    }
    try {
      setResponse(await api.taskPredictionDemo(selectedTask.id, { features }, requestContext));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : String(requestError));
    } finally {
      setState("ready");
    }
  }

  return (
    <div className="detail-stack">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>选择任务</h3>
            <p>在线预测只会调用真实运行产物。没有 AutoGluon predictor 或统一预测合约时，接口会明确返回暂不支持。</p>
          </div>
        </div>

        {!taskItems.length && !tasksLoading ? <div className="empty-state">当前团队还没有任务。</div> : null}
        {taskItems.length ? (
          <label className="field">
            <span>当前任务</span>
            <select value={selectedTask?.id ?? ""} onChange={(event) => onSelectTask?.(event.target.value)} disabled={tasksLoading}>
              {taskItems.map((task) => (
                <option key={task.id} value={task.id}>{task.name}</option>
              ))}
            </select>
          </label>
        ) : null}
      </section>

      {selectedTask ? (
        <section className="section-card">
          <div className="section-head">
            <div>
              <h3>单行在线预测</h3>
              <p>输入字段必须匹配训练时的特征列。目标列会在后端自动忽略。</p>
            </div>
            <span className={selectedTask.last_run ? "runtime-pill success" : "runtime-pill warning"}>
              {selectedTask.last_run ? "已有运行产物" : "暂无成功运行"}
            </span>
          </div>

          <form className="task-form" onSubmit={handleSubmit}>
            <label className="field">
              <span>Features JSON</span>
              <textarea
                rows={12}
                className="mono-text"
                value={featuresText}
                onChange={(event) => setFeaturesText(event.target.value)}
                spellCheck={false}
              />
            </label>
            <div className="button-row">
              <button type="submit" className="primary-button" disabled={state === "loading" || !selectedTask.last_run}>
                {state === "loading" ? "预测中..." : "运行在线预测"}
              </button>
              <button type="button" className="ghost-button" onClick={() => setFeaturesText(formatJson(sampleFeatures))}>
                使用数据预览样例
              </button>
            </div>
          </form>

          {error ? <div className="error-banner">{error}</div> : null}
          {response ? (
            <div className={response.supported ? "notice-banner" : "error-banner"}>
              {response.detail}
            </div>
          ) : null}
          {response?.prediction ? (
            <pre className="conversation-state-body">{formatJson(response.prediction)}</pre>
          ) : null}
          {response?.command_hint ? (
            <div className="callout">
              <strong>真实入口</strong>
              <p className="mono-text">{response.command_hint}</p>
            </div>
          ) : null}
        </section>
      ) : (
        <div className="empty-state">先选择一个任务，再打开 Web Demo。</div>
      )}
    </div>
  );
}
