import { formatDateTime } from "../lib/taskPresentation.js";

const STATUS_LABELS = {
  draft: "草稿",
  uploaded: "已上传数据集",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
};

const TABLE_RENDER_LIMIT = 200;

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
  return `发送 ${formatTokenValue(report.input_tokens)} / 返回 ${formatTokenValue(report.output_tokens)} / 总计 ${formatTokenValue(report.total_tokens)}`;
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
              <span>发送给 AI</span>
              <strong>{formatTokenValue(report.input_tokens)}</strong>
            </article>
            <article className="summary-item">
              <span>AI 返回</span>
              <strong>{formatTokenValue(report.output_tokens)}</strong>
            </article>
            <article className="summary-item">
              <span>合计用量</span>
              <strong>{formatTokenValue(report.total_tokens)}</strong>
            </article>
          </div>

          {asNonNegativeInteger(report.total_tokens) === 0 ? (
            <div className="callout token-usage-note">
              <strong>这次记录为 0</strong>
              <p>这里的 0 是真实记录值，不代表缺失数据。当前步骤可能没有实际调用 AI。</p>
            </div>
          ) : null}

          {showBreakdown && sessionEntries.length ? (
            <div className="detail-stack">
              <p className="eyebrow token-breakdown-title">分步骤明细</p>
              <div className="summary-grid token-breakdown-grid">
                {sessionEntries.map((entry, index) => (
                  <article key={`${entry.session_name ?? "session"}-${index}`} className="summary-item token-breakdown-item">
                    <span>{entry.session_name ?? `session-${index + 1}`}</span>
                    <strong>{formatTokenValue(entry.total_tokens)}</strong>
                    <small>发送 {formatTokenValue(entry.input_tokens)} / 返回 {formatTokenValue(entry.output_tokens)}</small>
                  </article>
                ))}
              </div>
            </div>
          ) : null}

          {showBreakdown && conversationEntries.length ? (
            <div className="detail-stack">
              <p className="eyebrow token-breakdown-title">对话明细</p>
              <div className="summary-grid token-breakdown-grid">
                {conversationEntries.map((entry, index) => (
                  <article key={`${entry.conversation_id ?? "conversation"}-${index}`} className="summary-item token-breakdown-item">
                    <span>{entry.conversation_id ?? `conversation-${index + 1}`}</span>
                    <strong>{formatTokenValue(entry.total_tokens)}</strong>
                    <small>发送 {formatTokenValue(entry.input_tokens)} / 返回 {formatTokenValue(entry.output_tokens)}</small>
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
  const visibleItems = items.slice(0, TABLE_RENDER_LIMIT);
  const visibleLedgerItems = ledgerItems.slice(0, TABLE_RENDER_LIMIT);

  return (
    <div className="detail-stack">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>团队 AI 使用总览</h3>
            <p>只展示系统真实记录到的 AI 使用情况。`未记录` 表示当前还没有采集到该阶段数据，`0` 表示已经记录但本次没有实际调用 AI。</p>
          </div>
          <button type="button" className="chip-button" onClick={onRefresh} disabled={loading}>
            {loading ? "刷新中..." : "刷新统计"}
          </button>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}

        {!summary && loading ? <div className="empty-state">正在汇总当前团队的 AI 使用情况...</div> : null}

        {summary ? (
          <div className="detail-stack">
            <div className="metrics-grid compact">
              <article className="metric-card small">
                <div className="metric-top"><span>团队总用量</span></div>
                <strong>{formatTokenValue(summary.combined_totals?.total_tokens)}</strong>
                <p>{describeTokenUsage(summary.combined_totals)}</p>
              </article>
              <article className="metric-card small">
                <div className="metric-top"><span>理解任务用量</span></div>
                <strong>{formatTokenValue(summary.analysis_totals?.total_tokens)}</strong>
                <p>{summary.tasks_with_analysis_usage ?? 0} 个任务已记录</p>
              </article>
              <article className="metric-card small">
                <div className="metric-top"><span>自动建模用量</span></div>
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

        {!summary && !loading && !error ? <div className="empty-state">当前团队还没有可展示的 AI 使用统计。</div> : null}
      </section>

      <details className="expert-advanced-fold">
        <summary>
          <span>按任务查看用量</span>
          <small>{items.length ? `${items.length} 个任务` : "暂无任务记录"}</small>
        </summary>
        <div className="expert-advanced-stack">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>任务级明细</h3>
            <p>这里把“理解任务”和“自动建模”分开展示，避免把“未记录”和真实 0 混在一起。</p>
          </div>
        </div>

        {items.length > TABLE_RENDER_LIMIT ? <div className="notice-banner compact">当前仅渲染前 {TABLE_RENDER_LIMIT} 条任务级明细，避免大表格拖慢页面。</div> : null}
        {items.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>任务</th>
                  <th>状态</th>
                  <th>理解任务</th>
                  <th>自动建模</th>
                  <th>合计</th>
                  <th>更新时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {visibleItems.map((item) => {
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
          <div className="empty-state">当前团队还没有任何任务级使用记录。</div>
        )}
      </section>
        </div>
      </details>

      <details className="expert-advanced-fold">
        <summary>
          <span>逐次调用记录</span>
          <small>{canViewLedgers ? `${ledgerItems.length} 条记录` : "管理员可见"}</small>
        </summary>
        <div className="expert-advanced-stack">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>逐次调用记录</h3>
            <p>管理员可以看到每次是谁、在哪个任务、调用了哪个 AI，以及系统记录的用量。</p>
          </div>
          <span className="runtime-pill info">{canViewLedgers ? `${ledgerItems.length} 条` : "管理员可见"}</span>
        </div>

        {ledgerError ? <div className="error-banner">{ledgerError}</div> : null}
        {!canViewLedgers ? <div className="empty-state">当前账号不是团队管理员，不能查看团队级调用流水。</div> : null}
        {canViewLedgers && ledgersLoading && !ledgerItems.length ? <div className="empty-state">正在读取逐次调用记录...</div> : null}

        {canViewLedgers && ledgerItems.length > TABLE_RENDER_LIMIT ? <div className="notice-banner compact">当前仅显示最近 {TABLE_RENDER_LIMIT} 条调用记录，避免大表格拖慢页面。</div> : null}
        {canViewLedgers && ledgerItems.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>成员</th>
                  <th>任务 / 阶段</th>
                  <th>AI / 模型</th>
                  <th>用量</th>
                  <th>记录方式</th>
                </tr>
              </thead>
              <tbody>
                {visibleLedgerItems.map((ledger) => (
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
                        <strong>{ledger.connector_display_name || ledger.connector_id || "未记录 AI"}</strong>
                        <span>{ledger.model_name || "未记录模型"}</span>
                      </div>
                    </td>
                    <td>
                      <div className="table-cell-stack">
                        <strong>{formatTokenValue(ledger.total_tokens)}</strong>
                        <span>发送 {formatTokenValue(ledger.input_tokens)} / 返回 {formatTokenValue(ledger.output_tokens)}</span>
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
          <div className="empty-state">当前团队还没有逐次调用记录。</div>
        ) : null}
      </section>
        </div>
      </details>
    </div>
  );
}
