import { useEffect, useMemo, useState } from "react";

const STAGE_OPTIONS = [
  { key: "requirement_analysis", label: "需求解析" },
  { key: "data_analysis", label: "数据分析" },
  { key: "feature_engineering", label: "特征工程" },
  { key: "model_selection", label: "模型选择" },
  { key: "training_validation", label: "训练验证" },
  { key: "report_generation", label: "报告生成" },
];

function buildInitialDraft(policies) {
  const policyMap = new Map((Array.isArray(policies) ? policies : []).map((item) => [item.stage, item]));
  return Object.fromEntries(
    STAGE_OPTIONS.map((stage) => {
      const current = policyMap.get(stage.key);
      return [
        stage.key,
        {
          connector_id: current?.connector_id || "",
          model_name: current?.connector_id ? current?.model_name || "" : "",
        },
      ];
    }),
  );
}

export default function RoutingPolicyPanel({
  connectors,
  policies,
  loading,
  saving,
  canManage = false,
  message,
  error,
  onRefresh,
  onSave,
}) {
  const [draft, setDraft] = useState(() => buildInitialDraft(policies));

  useEffect(() => {
    setDraft(buildInitialDraft(policies));
  }, [policies]);

  const connectorOptions = useMemo(() => (Array.isArray(connectors) ? connectors : []), [connectors]);

  function handleSubmit(event) {
    event.preventDefault();
    onSave?.({
      items: STAGE_OPTIONS.map((stage) => ({
        stage: stage.key,
        connector_id: draft[stage.key]?.connector_id || null,
        model_name: draft[stage.key]?.connector_id ? draft[stage.key]?.model_name?.trim() || null : null,
      })),
    });
  }

  return (
    <div className="detail-stack routing-page-layout">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>团队默认 AI 设置</h3>
            <p>这里设置每一步默认使用哪个 AI 服务。任务没有单独指定时，会自动沿用这里的设置。</p>
          </div>
          <button type="button" className="chip-button" onClick={onRefresh} disabled={loading}>
            {loading ? "刷新中..." : "刷新配置"}
          </button>
        </div>

        {message ? <div className="notice-banner">{message}</div> : null}
        {error ? <div className="error-banner">{error}</div> : null}

        <form className="task-form routing-stage-form" onSubmit={handleSubmit}>
          {STAGE_OPTIONS.map((stage) => (
            <div key={stage.key} className="section-card routing-stage-card">
              <div className="section-head">
                <div>
                  <h3>{stage.label}</h3>
                  <p>这个步骤需要指定一个可用的 AI 服务。只填模型名称是不够的。</p>
                </div>
              </div>

              <div className="form-row">
                <label className="field">
                  <span>AI 服务</span>
                  <select
                    value={draft[stage.key]?.connector_id || ""}
                    onChange={(event) => setDraft((current) => ({
                      ...current,
                      [stage.key]: {
                        ...current[stage.key],
                        connector_id: event.target.value,
                        model_name: event.target.value ? current[stage.key]?.model_name || "" : "",
                      },
                    }))}
                    disabled={!canManage}
                  >
                    <option value="">不指定</option>
                    {connectorOptions.map((connector) => (
                      <option key={connector.id} value={connector.id}>
                        {connector.display_name} · {connector.model_name}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="field">
                  <span>单独指定模型</span>
                  <input
                    value={draft[stage.key]?.model_name || ""}
                    onChange={(event) => setDraft((current) => ({
                      ...current,
                      [stage.key]: { ...current[stage.key], model_name: event.target.value },
                    }))}
                    placeholder="留空则使用该服务的默认模型"
                    disabled={!canManage || !draft[stage.key]?.connector_id}
                  />
                </label>
              </div>
            </div>
          ))}

          <div className="button-row">
            <button type="submit" className="primary-button" disabled={saving || !canManage}>
              {saving ? "保存中..." : "保存默认 AI 设置"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
