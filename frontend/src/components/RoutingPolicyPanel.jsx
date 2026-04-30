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
          model_name: current?.model_name || "",
          fallback_connector_id: current?.fallback_connector_id || "",
          fallback_model_name: current?.fallback_model_name || "",
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
        model_name: draft[stage.key]?.model_name?.trim() || null,
        fallback_connector_id: draft[stage.key]?.fallback_connector_id || null,
        fallback_model_name: draft[stage.key]?.fallback_model_name?.trim() || null,
      })),
    });
  }

  return (
    <div className="detail-stack">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>团队默认 AI 路由</h3>
            <p>这里定义的是阶段级默认连接器、模型和回退连接器。任务未显式覆盖时会继承这里的配置。</p>
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
                  <p>主路由优先使用 primary，主路由不可用时再回退到 fallback。</p>
                </div>
              </div>

              <div className="form-row">
                <label className="field">
                  <span>Primary 连接器</span>
                  <select
                    value={draft[stage.key]?.connector_id || ""}
                    onChange={(event) => setDraft((current) => ({
                      ...current,
                      [stage.key]: { ...current[stage.key], connector_id: event.target.value },
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
                  <span>Primary 模型覆盖</span>
                  <input
                    value={draft[stage.key]?.model_name || ""}
                    onChange={(event) => setDraft((current) => ({
                      ...current,
                      [stage.key]: { ...current[stage.key], model_name: event.target.value },
                    }))}
                    placeholder="留空则跟随连接器默认模型"
                    disabled={!canManage}
                  />
                </label>
              </div>

              <div className="form-row">
                <label className="field">
                  <span>Fallback 连接器</span>
                  <select
                    value={draft[stage.key]?.fallback_connector_id || ""}
                    onChange={(event) => setDraft((current) => ({
                      ...current,
                      [stage.key]: { ...current[stage.key], fallback_connector_id: event.target.value },
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
                  <span>Fallback 模型覆盖</span>
                  <input
                    value={draft[stage.key]?.fallback_model_name || ""}
                    onChange={(event) => setDraft((current) => ({
                      ...current,
                      [stage.key]: { ...current[stage.key], fallback_model_name: event.target.value },
                    }))}
                    placeholder="留空则跟随 fallback 连接器默认模型"
                    disabled={!canManage}
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
