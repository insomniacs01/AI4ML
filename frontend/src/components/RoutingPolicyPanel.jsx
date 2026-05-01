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
        fallback_connector_id: null,
        fallback_model_name: null,
      })),
    });
  }

  return (
    <div className="detail-stack">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>团队默认 AI 路由</h3>
            <p>这里定义的是阶段级默认连接器和模型。任务未显式覆盖时会继承这里的配置；未配置则在运行时直接报错。</p>
          </div>
          <button type="button" className="chip-button" onClick={onRefresh} disabled={loading}>
            {loading ? "刷新中..." : "刷新配置"}
          </button>
        </div>

        {message ? <div className="notice-banner">{message}</div> : null}
        {error ? <div className="error-banner">{error}</div> : null}

        <form className="task-form" onSubmit={handleSubmit}>
          {STAGE_OPTIONS.map((stage) => (
            <div key={stage.key} className="section-card">
              <div className="section-head">
                <div>
                  <h3>{stage.label}</h3>
                  <p>这个阶段必须使用一个明确的连接器。只填模型名不会自动借用当前运行时连接器。</p>
                </div>
              </div>

              <div className="form-row">
                <label className="field">
                  <span>连接器</span>
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
                  <span>模型覆盖</span>
                  <input
                    value={draft[stage.key]?.model_name || ""}
                    onChange={(event) => setDraft((current) => ({
                      ...current,
                      [stage.key]: { ...current[stage.key], model_name: event.target.value },
                    }))}
                    placeholder="留空则跟随连接器默认模型"
                    disabled={!canManage || !draft[stage.key]?.connector_id}
                  />
                </label>
              </div>
            </div>
          ))}

          <div className="button-row">
            <button type="submit" className="primary-button" disabled={saving || !canManage}>
              {saving ? "保存中..." : "保存默认 AI 路由"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
