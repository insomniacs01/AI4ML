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

export default function ConnectorManagementPanel({
  activeTeamName,
  connectorsState,
  connectors,
  form,
  savingConnector,
  testingConnectorId,
  activatingConnectorId,
  message,
  error,
  onFormChange,
  onSubmit,
  onRefresh,
  onTest,
  onActivate,
}) {
  return (
    <>
      <section className="page-header">
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

      <section className="placeholder-panel">
        <strong>新建连接器</strong>
        <p>
          当前团队：{activeTeamName || "未选择团队"}。如果你拿到的是完整接口地址，例如
          <code> https://api.example.com/v2/chat/completions </code>
          ，可以直接粘贴进去，后端会自动归一化成 MLZero 需要的 base URL。
        </p>

        <form className="task-form" onSubmit={onSubmit}>
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

      <section className="placeholder-panel">
        <strong>已保存的连接器</strong>
        <p>“设为当前运行时”现在是团队级切换，不再依赖本地 `storage/connectors`。切换之后，这个团队任务页里的“AI 解析”和后续 MLZero 执行都会使用这个连接器。</p>

        {connectorsState === "loading" && !connectors.length ? <p className="meta-note">正在读取连接器列表...</p> : null}
        {connectorsState !== "loading" && !connectors.length ? <p className="meta-note">当前团队还没有保存任何连接器。</p> : null}

        {connectors.length ? (
          <div className="task-cards">
            {connectors.map((connector) => (
              <article key={connector.id} className="task-card">
                <div className="button-row">
                  <div>
                    <p className="eyebrow">OpenAI-compatible connector</p>
                    <h4>{connector.display_name}</h4>
                  </div>
                  <div className="connector-chip-row">
                    {connector.is_active ? <span className="runtime-pill info">当前运行时</span> : null}
                    <span className={`runtime-pill ${getStatusTone(connector.last_test_status)}`}>{getStatusLabel(connector.last_test_status)}</span>
                  </div>
                </div>

                <div className="summary-grid">
                  <article className="summary-item connector-summary-item"><span>Base URL</span><strong className="connector-break">{connector.base_url}</strong></article>
                  <article className="summary-item"><span>模型 ID</span><strong>{connector.model_name}</strong></article>
                  <article className="summary-item"><span>Wire API</span><strong>{getWireApiLabel(connector.wire_api)}</strong></article>
                  <article className="summary-item"><span>API Key</span><strong>{connector.api_key_masked}</strong></article>
                  <article className="summary-item connector-summary-item"><span>录入地址</span><strong className="connector-break">{connector.endpoint_url || connector.base_url}</strong></article>
                  <article className="summary-item"><span>最后测试</span><strong>{formatDateTime(connector.last_tested_at)}</strong></article>
                </div>

                {connector.last_test_detail ? <p className="meta-note connector-detail">{connector.last_test_detail}</p> : null}

                <div className="button-row connector-actions">
                  <button type="button" className="ghost-button" onClick={() => onTest(connector.id)} disabled={testingConnectorId === connector.id || activatingConnectorId === connector.id}>
                    {testingConnectorId === connector.id ? "测试中..." : "测试连接"}
                  </button>
                  <button type="button" className="primary-button" onClick={() => onActivate(connector.id)} disabled={activatingConnectorId === connector.id}>
                    {activatingConnectorId === connector.id ? "切换中..." : connector.is_active ? "已是当前运行时" : "设为当前运行时"}
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </section>
    </>
  );
}
