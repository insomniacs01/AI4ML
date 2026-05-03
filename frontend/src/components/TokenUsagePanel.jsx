const STATUS_LABELS = {
  draft: "草稿",
  uploaded: "已上传数据集",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
};

function asNonNegativeInteger(value) {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.trunc(value)) : 0;
}

export function hasTokenUsage(report) {
  return Boolean(report) && typeof report === "object";
}

export function formatTokenValue(value) {
  return asNonNegativeInteger(value).toLocaleString("zh-CN");
}

export function describeTokenUsage(report) {
  if (!hasTokenUsage(report)) return "未记录";
  return `输入 ${formatTokenValue(report.input_tokens)} / 输出 ${formatTokenValue(report.output_tokens)} / 总计 ${formatTokenValue(report.total_tokens)}`;
}

function formatDateTime(value) {
  if (!value) return "暂无";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatStatus(status) {
  return STATUS_LABELS[status] ?? status;
}

function getBreakdownEntries(report, keyName) {
  if (!hasTokenUsage(report)) return [];
  return Array.isArray(report[keyName]) ? report[keyName].filter((item) => item && typeof item === "object") : [];
}

function getRecordedTone(report) {
  if (!hasTokenUsage(report)) return "info";
  return asNonNegativeInteger(report.total_tokens) > 0 ? "success" : "warning";
}

export function TokenUsageCard({
  title,
  report,
  emptyText,
  description,
  showBreakdown = false,
  embedded = false,
}) {
  const sessionEntries = getBreakdownEntries(report, "sessions");
  const conversationEntries = getBreakdownEntries(report, "conversations");

  return (
    <section className={embedded ? "token-usage-card-embedded" : "section-card"}>
      <div className="section-head">
        <div>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
        <span className={`runtime-pill ${getRecordedTone(report)}`}>{hasTokenUsage(report) ? "已记录" : "未记录"}</span>
      </div>

      {hasTokenUsage(report) ? (
        <div className="detail-stack">
          <div className="summary-grid">
            <article className="summary-item">
              <span>输入 Token</span>
              <strong>{formatTokenValue(report.input_tokens)}</strong>
            </article>
            <article className="summary-item">
              <span>输出 Token</span>
              <strong>{formatTokenValue(report.output_tokens)}</strong>
            </article>
            <article className="summary-item">
              <span>总 Token</span>
              <strong>{formatTokenValue(report.total_tokens)}</strong>
            </article>
          </div>

          {asNonNegativeInteger(report.total_tokens) === 0 ? (
            <div className="callout token-usage-note">
              <strong>这次记录为 0</strong>
              <p>这里的 0 是真实记录值，不代表缺失数据。当前路径可能走了本地确定性逻辑，因此没有消耗模型 token。</p>
            </div>
          ) : null}

          {showBreakdown && sessionEntries.length ? (
            <div className="detail-stack">
              <p className="eyebrow token-breakdown-title">Session 明细</p>
              <div className="summary-grid token-breakdown-grid">
                {sessionEntries.map((entry, index) => (
                  <article key={`${entry.session_name ?? "session"}-${index}`} className="summary-item token-breakdown-item">
                    <span>{entry.session_name ?? `session-${index + 1}`}</span>
                    <strong>{formatTokenValue(entry.total_tokens)}</strong>
                    <small>输入 {formatTokenValue(entry.input_tokens)} / 输出 {formatTokenValue(entry.output_tokens)}</small>
                  </article>
                ))}
              </div>
            </div>
          ) : null}

          {showBreakdown && conversationEntries.length ? (
            <div className="detail-stack">
              <p className="eyebrow token-breakdown-title">Conversation 明细</p>
              <div className="summary-grid token-breakdown-grid">
                {conversationEntries.map((entry, index) => (
                  <article key={`${entry.conversation_id ?? "conversation"}-${index}`} className="summary-item token-breakdown-item">
                    <span>{entry.conversation_id ?? `conversation-${index + 1}`}</span>
                    <strong>{formatTokenValue(entry.total_tokens)}</strong>
                    <small>输入 {formatTokenValue(entry.input_tokens)} / 输出 {formatTokenValue(entry.output_tokens)}</small>
                  </article>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="empty-state">{emptyText}</div>
      )}
    </section>
  );
}

export default function TokenUsagePanel({
  summary,
  ledgers,
  loading,
  ledgersLoading,
  error,
  ledgerError,
  canViewLedgers,
  onRefresh,
  onSelectTask,
}) {
  const items = Array.isArray(summary?.items) ? summary.items : [];
  const ledgerItems = Array.isArray(ledgers?.items) ? ledgers.items : [];

  return (
    <div className="detail-stack">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>团队 Token 总览</h3>
            <p>只展示真实记录到系统里的 token。`未记录` 表示当前还没有采集到该阶段数据，`0` 表示已经记录但本次没有实际消耗模型 token。</p>
          </div>
          <button type="button" className="chip-button" onClick={onRefresh} disabled={loading}>
            {loading ? "刷新中..." : "刷新统计"}
          </button>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}

        {!summary && loading ? <div className="empty-state">正在汇总当前团队的 Token 用量...</div> : null}

        {summary ? (
          <div className="detail-stack">
            <div className="metrics-grid compact">
              <article className="metric-card small">
                <div className="metric-top"><span>团队总 Token</span></div>
                <strong>{formatTokenValue(summary.combined_totals?.total_tokens)}</strong>
                <p>{describeTokenUsage(summary.combined_totals)}</p>
              </article>
              <article className="metric-card small">
                <div className="metric-top"><span>AI 解析 Token</span></div>
                <strong>{formatTokenValue(summary.analysis_totals?.total_tokens)}</strong>
                <p>{summary.tasks_with_analysis_usage ?? 0} 个任务已记录</p>
              </article>
              <article className="metric-card small">
                <div className="metric-top"><span>MLZero 运行 Token</span></div>
                <strong>{formatTokenValue(summary.run_totals?.total_tokens)}</strong>
                <p>{summary.tasks_with_run_usage ?? 0} 个任务已记录</p>
              </article>
              <article className="metric-card small">
                <div className="metric-top"><span>已记录任务数</span></div>
                <strong>{items.filter((item) => hasTokenUsage(item.analysis_token_usage) || hasTokenUsage(item.run_token_usage)).length}</strong>
                <p>团队任务总数 {summary.task_count ?? 0}</p>
              </article>
            </div>
          </div>
        ) : null}

        {!summary && !loading && !error ? <div className="empty-state">当前团队还没有可展示的 Token 统计。</div> : null}
      </section>

      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>任务级明细</h3>
            <p>这里把 AI 解析阶段和 MLZero 运行阶段分开展示，避免把“未记录”和真实 0 混在一起。</p>
          </div>
        </div>

        {items.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>任务</th>
                  <th>状态</th>
                  <th>AI 解析</th>
                  <th>MLZero</th>
                  <th>合计</th>
                  <th>更新时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const combinedReport = hasTokenUsage(item.analysis_token_usage) || hasTokenUsage(item.run_token_usage)
                    ? item.combined_token_usage
                    : null;

                  return (
                    <tr key={item.task_id}>
                      <td>
                        <div className="table-cell-stack">
                          <strong>{item.task_name}</strong>
                          <span>{item.dataset_filename ?? "未上传数据集"}</span>
                        </div>
                      </td>
                      <td>{formatStatus(item.status)}</td>
                      <td>
                        <div className="table-cell-stack">
                          <strong>{hasTokenUsage(item.analysis_token_usage) ? formatTokenValue(item.analysis_token_usage.total_tokens) : "未记录"}</strong>
                          <span>{describeTokenUsage(item.analysis_token_usage)}</span>
                        </div>
                      </td>
                      <td>
                        <div className="table-cell-stack">
                          <strong>{hasTokenUsage(item.run_token_usage) ? formatTokenValue(item.run_token_usage.total_tokens) : "未记录"}</strong>
                          <span>{describeTokenUsage(item.run_token_usage)}</span>
                        </div>
                      </td>
                      <td>
                        <div className="table-cell-stack">
                          <strong>{hasTokenUsage(combinedReport) ? formatTokenValue(combinedReport.total_tokens) : "未记录"}</strong>
                          <span>{describeTokenUsage(combinedReport)}</span>
                        </div>
                      </td>
                      <td>{formatDateTime(item.updated_at)}</td>
                      <td>
                        <button type="button" className="ghost-button token-table-button" onClick={() => onSelectTask?.(item.task_id)}>
                          查看任务
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">当前团队还没有任何任务级 Token 记录。</div>
        )}
      </section>

      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>Token 调用流水</h3>
            <p>管理员可追溯到成员、任务、阶段、连接器和核算方式；这张表来自 TokenLedger，不是按任务摘要反推。</p>
          </div>
          <span className="runtime-pill info">{canViewLedgers ? `${ledgerItems.length} 条` : "管理员可见"}</span>
        </div>

        {ledgerError ? <div className="error-banner">{ledgerError}</div> : null}
        {!canViewLedgers ? <div className="empty-state">当前账号不是团队管理员，不能查看团队级调用流水。</div> : null}
        {canViewLedgers && ledgersLoading && !ledgerItems.length ? <div className="empty-state">正在读取 Token 调用流水...</div> : null}

        {canViewLedgers && ledgerItems.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>成员</th>
                  <th>任务 / 阶段</th>
                  <th>连接器 / 模型</th>
                  <th>Token</th>
                  <th>核算方式</th>
                </tr>
              </thead>
              <tbody>
                {ledgerItems.map((ledger) => (
                  <tr key={ledger.id}>
                    <td>{formatDateTime(ledger.created_at)}</td>
                    <td>
                      <div className="table-cell-stack">
                        <strong>{ledger.user_display_name || ledger.user_email || ledger.user_id || "未记录"}</strong>
                        <span>{ledger.phase}</span>
                      </div>
                    </td>
                    <td>
                      <div className="table-cell-stack">
                        <strong>{ledger.task_name || ledger.task_id || "未关联任务"}</strong>
                        <span>{ledger.stage_key || "未记录阶段"}</span>
                      </div>
                    </td>
                    <td>
                      <div className="table-cell-stack">
                        <strong>{ledger.connector_display_name || ledger.connector_id || "未记录连接器"}</strong>
                        <span>{ledger.model_name || "未记录模型"}</span>
                      </div>
                    </td>
                    <td>
                      <div className="table-cell-stack">
                        <strong>{formatTokenValue(ledger.total_tokens)}</strong>
                        <span>输入 {formatTokenValue(ledger.input_tokens)} / 输出 {formatTokenValue(ledger.output_tokens)}</span>
                      </div>
                    </td>
                    <td>{ledger.calculation_method || "未记录"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {canViewLedgers && !ledgerItems.length && !ledgersLoading && !ledgerError ? (
          <div className="empty-state">当前团队还没有逐次 Token 调用流水。</div>
        ) : null}
      </section>
    </div>
  );
}
