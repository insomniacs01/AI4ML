import { useEffect, useState } from "react";

const TEST_STATUS_LABELS = {
  untested: "未测试",
  passed: "测试通过",
  failed: "测试失败",
};

const TEST_STATUS_TONES = {
  untested: "warning",
  passed: "success",
  failed: "danger",
};

const WIRE_API_LABELS = {
  chat_completions: "chat/completions",
  responses: "responses",
};

function formatDateTime(value) {
  if (!value) return "尚未测试";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function getStatusLabel(status) {
  return TEST_STATUS_LABELS[status] ?? status;
}

function getStatusTone(status) {
  return TEST_STATUS_TONES[status] ?? "warning";
}

function getWireApiLabel(wireApi) {
  return WIRE_API_LABELS[wireApi] ?? wireApi;
}

function buildEditForm(connector) {
  return {
    display_name: connector?.display_name ?? "",
    endpoint_url: connector?.endpoint_url || connector?.base_url || "",
    model_name: connector?.model_name ?? "",
    wire_api: connector?.wire_api ?? "chat_completions",
    api_key: "",
  };
}

export default function ConnectorManagementPanel({
  activeTeamName,
  connectorsState,
  connectors,
  form,
  savingConnector,
  testingConnectorId,
  activatingConnectorId,
  updatingConnectorId,
  deactivatingConnectorId,
  deletingConnectorId,
  healthCheckingConnectors,
  message,
  error,
  onFormChange,
  onSubmit,
  onRefresh,
  onTest,
  onActivate,
  onUpdate,
  onDeactivate,
  onDelete,
  onHealthCheck,
}) {
  const [editingConnectorId, setEditingConnectorId] = useState("");
  const [editForm, setEditForm] = useState(buildEditForm(null));

  useEffect(() => {
    if (!editingConnectorId) return;
    const connector = connectors.find((item) => item.id === editingConnectorId);
    if (!connector) {
      setEditingConnectorId("");
      setEditForm(buildEditForm(null));
    }
  }, [connectors, editingConnectorId]);

  function beginEdit(connector) {
    setEditingConnectorId(connector.id);
    setEditForm(buildEditForm(connector));
  }

  async function handleEditSubmit(event, connectorId) {
    event.preventDefault();
    const payload = {
      display_name: editForm.display_name.trim(),
      endpoint_url: editForm.endpoint_url.trim(),
      model_name: editForm.model_name.trim(),
      wire_api: editForm.wire_api,
    };
    if (editForm.api_key.trim()) payload.api_key = editForm.api_key.trim();
    const ok = await onUpdate?.(connectorId, payload);
    if (ok !== false) {
      setEditingConnectorId("");
      setEditForm(buildEditForm(null));
    }
  }

  return (
    <>
      <section className="page-header connector-hero">
        <div>
          <p className="eyebrow">AI Connectors</p>
          <h1>录入 OpenAI 兼容连接器</h1>
          <p className="page-copy">
            在这里填你真实要调用的模型服务。连接器会保存到当前团队的 Supabase 数据里。点“设为当前运行时”后，这个团队后续的 AI 解析和 MLZero 都会走它。
          </p>
        </div>
      </section>

      {message ? <div className="notice-banner">{message}</div> : null}
      {error ? <div className="error-banner">{error}</div> : null}

      <div className="connector-page-grid">
        <section className="section-card connector-form-card">
          <div className="section-head">
            <div>
              <p className="eyebrow">New Connector</p>
              <h3>新建连接器</h3>
              <p>
                当前团队：{activeTeamName || "未选择团队"}。可以粘贴完整接口地址，后端会自动归一化成 MLZero 需要的 base URL。
              </p>
            </div>
          </div>

          <div className="connector-form-note">
            <strong>录入示例</strong>
            <code>https://api.example.com/v2/chat/completions</code>
          </div>

          <form className="task-form connector-form" onSubmit={onSubmit}>
            <div className="form-row">
              <label className="field">
                <span>连接器名称</span>
                <input value={form.display_name} onChange={(event) => onFormChange("display_name", event.target.value)} placeholder="例如：ModelArts DeepSeek" maxLength={120} required />
              </label>
              <label className="field">
                <span>模型 ID</span>
                <input value={form.model_name} onChange={(event) => onFormChange("model_name", event.target.value)} placeholder="例如：deepseek-v3.2" maxLength={200} required />
              </label>
            </div>

            <label className="field">
              <span>API 地址</span>
              <input value={form.endpoint_url} onChange={(event) => onFormChange("endpoint_url", event.target.value)} placeholder="例如：https://api.example.com/v2/chat/completions" maxLength={500} required />
            </label>

            <div className="form-row">
              <label className="field">
                <span>Wire API</span>
                <select value={form.wire_api} onChange={(event) => onFormChange("wire_api", event.target.value)}>
                  <option value="auto">自动判断（推荐）</option>
                  <option value="chat_completions">chat/completions</option>
                  <option value="responses">responses</option>
                </select>
              </label>
              <label className="field">
                <span>API Key</span>
                <input type="password" value={form.api_key} onChange={(event) => onFormChange("api_key", event.target.value)} placeholder="输入这个连接器的 API Key" maxLength={500} required />
              </label>
            </div>

            <p className="helper-text">
              “连接器名称”是给人看的备注名，“模型 ID”必须填服务商真正支持的模型标识。保存后建议先点击“测试连接”。
            </p>

            <div className="button-row connector-actions">
              <button type="submit" className="primary-button" disabled={savingConnector}>{savingConnector ? "保存中..." : "保存连接器"}</button>
              <button type="button" className="ghost-button" onClick={onRefresh} disabled={connectorsState === "loading"}>{connectorsState === "loading" ? "刷新中..." : "刷新列表"}</button>
            </div>
          </form>
        </section>

        <section className="section-card connector-list-card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Runtime Pool</p>
              <h3>已保存的连接器</h3>
              <p>这里可以测试、编辑、启停和删除连接器。批量健康检查会真实调用每一个连接器并写回测试状态。</p>
            </div>
            <div className="connector-chip-row">
              <span className="runtime-pill info">{connectors.length} 个连接器</span>
              <button type="button" className="ghost-button" onClick={onHealthCheck} disabled={!connectors.length || healthCheckingConnectors}>
                {healthCheckingConnectors ? "检查中..." : "批量健康检查"}
              </button>
            </div>
          </div>

          {connectorsState === "loading" && !connectors.length ? <p className="meta-note">正在读取连接器列表...</p> : null}
          {connectorsState !== "loading" && !connectors.length ? <p className="meta-note">当前团队还没有保存任何连接器。</p> : null}

          {connectors.length ? (
            <div className="connector-card-list">
              {connectors.map((connector) => {
                const isEditing = editingConnectorId === connector.id;
                const busy = testingConnectorId === connector.id
                  || activatingConnectorId === connector.id
                  || updatingConnectorId === connector.id
                  || deactivatingConnectorId === connector.id
                  || deletingConnectorId === connector.id;
                return (
                  <article key={connector.id} className={connector.is_active ? "connector-card active" : "connector-card"}>
                    <div className="connector-card-head">
                      <div>
                        <p className="eyebrow">OpenAI-compatible connector</p>
                        <h4>{connector.display_name}</h4>
                        <span>{connector.model_name}</span>
                      </div>
                      <div className="connector-chip-row">
                        {connector.is_active ? <span className="runtime-pill info">当前运行时</span> : null}
                        <span className={`runtime-pill ${getStatusTone(connector.last_test_status)}`}>{getStatusLabel(connector.last_test_status)}</span>
                      </div>
                    </div>

                    <div className="connector-card-grid">
                      <article><span>Base URL</span><strong>{connector.base_url}</strong></article>
                      <article><span>Wire API</span><strong>{getWireApiLabel(connector.wire_api)}</strong></article>
                      <article><span>API Key</span><strong>{connector.api_key_masked}</strong></article>
                      <article><span>最后测试</span><strong>{formatDateTime(connector.last_tested_at)}</strong></article>
                    </div>

                    {connector.last_test_detail ? <p className="meta-note connector-detail">{connector.last_test_detail}</p> : null}

                    {isEditing ? (
                      <form className="task-form connector-edit-form" onSubmit={(event) => handleEditSubmit(event, connector.id)}>
                        <div className="form-row">
                          <label className="field">
                            <span>连接器名称</span>
                            <input value={editForm.display_name} onChange={(event) => setEditForm((current) => ({ ...current, display_name: event.target.value }))} maxLength={120} required />
                          </label>
                          <label className="field">
                            <span>模型 ID</span>
                            <input value={editForm.model_name} onChange={(event) => setEditForm((current) => ({ ...current, model_name: event.target.value }))} maxLength={200} required />
                          </label>
                        </div>
                        <label className="field">
                          <span>API 地址</span>
                          <input value={editForm.endpoint_url} onChange={(event) => setEditForm((current) => ({ ...current, endpoint_url: event.target.value }))} maxLength={500} required />
                        </label>
                        <div className="form-row">
                          <label className="field">
                            <span>Wire API</span>
                            <select value={editForm.wire_api} onChange={(event) => setEditForm((current) => ({ ...current, wire_api: event.target.value }))}>
                              <option value="chat_completions">chat/completions</option>
                              <option value="responses">responses</option>
                              <option value="auto">自动判断</option>
                            </select>
                          </label>
                          <label className="field">
                            <span>新 API Key（留空则不变）</span>
                            <input type="password" value={editForm.api_key} onChange={(event) => setEditForm((current) => ({ ...current, api_key: event.target.value }))} maxLength={500} />
                          </label>
                        </div>
                        <div className="button-row connector-actions">
                          <button type="submit" className="primary-button" disabled={updatingConnectorId === connector.id}>
                            {updatingConnectorId === connector.id ? "保存中..." : "保存修改"}
                          </button>
                          <button type="button" className="ghost-button" onClick={() => setEditingConnectorId("")} disabled={updatingConnectorId === connector.id}>
                            取消
                          </button>
                        </div>
                      </form>
                    ) : null}

                    <div className="button-row connector-actions">
                      <button type="button" className="ghost-button" onClick={() => onTest(connector.id)} disabled={busy || healthCheckingConnectors}>
                        {testingConnectorId === connector.id ? "测试中..." : "测试连接"}
                      </button>
                      <button type="button" className="primary-button" onClick={() => onActivate(connector.id)} disabled={busy || connector.is_active}>
                        {activatingConnectorId === connector.id ? "切换中..." : connector.is_active ? "已是当前运行时" : "设为当前运行时"}
                      </button>
                      <button type="button" className="ghost-button" onClick={() => beginEdit(connector)} disabled={busy || isEditing}>
                        编辑
                      </button>
                      <button type="button" className="ghost-button" onClick={() => onDeactivate(connector.id)} disabled={busy || !connector.is_active}>
                        {deactivatingConnectorId === connector.id ? "停用中..." : "停用"}
                      </button>
                      <button type="button" className="danger-button" onClick={() => onDelete(connector.id)} disabled={busy}>
                        {deletingConnectorId === connector.id ? "删除中..." : "删除"}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : null}
        </section>
      </div>
    </>
  );
}
