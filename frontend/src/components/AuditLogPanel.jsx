import { compactDisplayText, looksLikeRawRuntimeText } from "../lib/errorMessages.js";
import { formatDateTime } from "../lib/taskPresentation.js";

const AUDIT_LOG_RENDER_LIMIT = 200;
const AUDIT_DETAIL_SUMMARY_LIMIT = 180;

function stringifyDetail(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function pickDetailValue(detail, keys) {
  if (!detail || typeof detail !== "object") return "";
  for (const key of keys) {
    const value = detail[key];
    if (value == null || value === "") continue;
    return String(value);
  }
  return "";
}

function buildAuditDetailSummary(detail) {
  if (detail == null) return "-";
  if (typeof detail !== "object") {
    return looksLikeRawRuntimeText(detail)
      ? "原始运行日志已收起；请在任务详情或运行详情里查看诊断结论。"
      : compactDisplayText(detail, AUDIT_DETAIL_SUMMARY_LIMIT);
  }

  const rawDetail = pickDetailValue(detail, ["diagnosis", "diagnosis_detail", "summary", "message", "detail"]);
  const pathDetail = pickDetailValue(detail, ["error_artifact_path", "error_log_path", "output_dir"]);
  const statusValue = pickDetailValue(detail, ["status"]);
  const summaryParts = [];
  if (statusValue) summaryParts.push(`状态：${statusValue}`);
  if (rawDetail) {
    summaryParts.push(
      looksLikeRawRuntimeText(rawDetail)
        ? "原始运行日志已收起"
        : compactDisplayText(rawDetail, 96),
    );
  }
  if (pathDetail) summaryParts.push(`文件：${pathDetail}`);
  if (summaryParts.length) return compactDisplayText(summaryParts.join(" · "), AUDIT_DETAIL_SUMMARY_LIMIT);

  const rawJson = stringifyDetail(detail);
  return looksLikeRawRuntimeText(rawJson)
    ? "原始运行日志已收起；请在任务详情或运行详情里查看诊断结论。"
    : compactDisplayText(rawJson, AUDIT_DETAIL_SUMMARY_LIMIT);
}

function AuditDetailCell({ detail }) {
  if (detail == null) return <span>-</span>;
  return (
    <div className="audit-detail-cell">
      <span className="audit-detail-summary">{buildAuditDetailSummary(detail)}</span>
      <details className="audit-detail-raw">
        <summary>完整内容</summary>
        <pre>{stringifyDetail(detail)}</pre>
      </details>
    </div>
  );
}

export default function AuditLogPanel({
  logs,
  loading,
  error,
  onRefresh,
}) {
  const visibleLogs = Array.isArray(logs) ? logs.slice(0, AUDIT_LOG_RENDER_LIMIT) : [];
  return (
    <div className="detail-stack audit-page-layout">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>操作记录</h3>
            <p>这里展示团队里已经真实保存的重要操作记录。</p>
          </div>
          <button type="button" className="chip-button" onClick={onRefresh} disabled={loading}>
            {loading ? "刷新中..." : "刷新记录"}
          </button>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}
        {!logs?.length && !loading ? <div className="empty-state">当前团队还没有操作记录。</div> : null}

        {Array.isArray(logs) && logs.length > AUDIT_LOG_RENDER_LIMIT ? (
          <div className="notice-banner compact">当前仅显示最近 {AUDIT_LOG_RENDER_LIMIT} 条操作记录，避免大表格拖慢页面。</div>
        ) : null}

        {visibleLogs.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>时间</th><th>操作者</th><th>动作</th><th>资源</th><th>详情</th></tr>
              </thead>
              <tbody>
                {visibleLogs.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDateTime(item.created_at)}</td>
                    <td>{item.actor_display_name || item.actor_email || item.actor_id || "-"}</td>
                    <td>{item.action}</td>
                    <td>{item.resource_type ? `${item.resource_type}${item.resource_id ? ` / ${item.resource_id}` : ""}` : "-"}</td>
                    <td><AuditDetailCell detail={item.detail} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
