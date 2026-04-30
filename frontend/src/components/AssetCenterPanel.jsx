import { useMemo, useState } from "react";

const ASSET_TYPE_OPTIONS = [
  { value: "dataset", label: "数据集" },
  { value: "model", label: "模型" },
  { value: "workflow", label: "工作流" },
  { value: "report", label: "报告" },
];

function formatDateTime(value) {
  if (!value) return "暂无";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

const EMPTY_FORM = {
  asset_type: "dataset",
  title: "",
  description: "",
  storage_path: "",
  review_status: "private",
};

export default function AssetCenterPanel({
  assets,
  loading,
  creating,
  reviewingAssetId,
  message,
  error,
  isAdmin,
  onRefresh,
  onCreate,
  onReview,
}) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [activeType, setActiveType] = useState("all");
  const visibleAssets = useMemo(
    () => (Array.isArray(assets) ? assets : []).filter((item) => activeType === "all" ? true : item.asset_type === activeType),
    [activeType, assets],
  );

  function handleSubmit(event) {
    event.preventDefault();
    onCreate?.({
      asset_type: form.asset_type,
      title: form.title.trim(),
      description: form.description.trim() || null,
      storage_path: form.storage_path.trim() || null,
      review_status: form.review_status,
    });
    setForm(EMPTY_FORM);
  }

  return (
    <div className="detail-stack">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>资产中心</h3>
            <p>这里统一管理数据集、模型、工作流和报告记录。当前版本先提供真实元数据登记和审核状态流转。</p>
          </div>
          <button type="button" className="chip-button" onClick={onRefresh} disabled={loading}>
            {loading ? "刷新中..." : "刷新资产"}
          </button>
        </div>

        {message ? <div className="notice-banner">{message}</div> : null}
        {error ? <div className="error-banner">{error}</div> : null}

        <form className="task-form" onSubmit={handleSubmit}>
          <div className="form-row">
            <label className="field">
              <span>资产类型</span>
              <select value={form.asset_type} onChange={(event) => setForm((current) => ({ ...current, asset_type: event.target.value }))}>
                {ASSET_TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="field">
              <span>审核状态</span>
              <select value={form.review_status} onChange={(event) => setForm((current) => ({ ...current, review_status: event.target.value }))}>
                <option value="private">private</option>
                <option value="pending_review">pending_review</option>
                <option value="approved">approved</option>
                <option value="published">published</option>
                <option value="rejected">rejected</option>
              </select>
            </label>
          </div>
          <label className="field">
            <span>标题</span>
            <input value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} required />
          </label>
          <label className="field">
            <span>描述</span>
            <textarea value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} rows={3} />
          </label>
          <label className="field">
            <span>存储路径</span>
            <input value={form.storage_path} onChange={(event) => setForm((current) => ({ ...current, storage_path: event.target.value }))} placeholder="例如：storage/mlzero_runs/task-1/run_summary.json" />
          </label>
          <div className="button-row">
            <button type="submit" className="primary-button" disabled={creating}>{creating ? "创建中..." : "登记资产"}</button>
          </div>
        </form>
      </section>

      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>资产列表</h3>
            <p>这里显示的是已经写入平台资产表的真实记录。</p>
          </div>
          <div className="toolbar">
            <div className="segmented-control">
              <button type="button" className={activeType === "all" ? "segment-button active" : "segment-button"} onClick={() => setActiveType("all")}>全部</button>
              {ASSET_TYPE_OPTIONS.map((option) => (
                <button key={option.value} type="button" className={activeType === option.value ? "segment-button active" : "segment-button"} onClick={() => setActiveType(option.value)}>
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {!visibleAssets.length ? <div className="empty-state">当前筛选条件下还没有资产记录。</div> : null}

        {visibleAssets.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>标题</th><th>类型</th><th>创建人</th><th>状态</th><th>更新时间</th><th>操作</th></tr>
              </thead>
              <tbody>
                {visibleAssets.map((asset) => (
                  <tr key={asset.id}>
                    <td>
                      <div className="table-cell-stack">
                        <strong>{asset.title}</strong>
                        <span>{asset.storage_path || asset.description || "暂无描述"}</span>
                      </div>
                    </td>
                    <td>{asset.asset_type}</td>
                    <td>{asset.creator_display_name || asset.creator_email || asset.created_by || "-"}</td>
                    <td>{asset.review_status}</td>
                    <td>{formatDateTime(asset.updated_at)}</td>
                    <td>
                      {isAdmin ? (
                        <div className="button-row">
                          <button type="button" className="ghost-button" disabled={reviewingAssetId === asset.id} onClick={() => onReview?.(asset.id, { review_status: "approved" })}>
                            {reviewingAssetId === asset.id ? "处理中..." : "通过"}
                          </button>
                          <button type="button" className="ghost-button" disabled={reviewingAssetId === asset.id} onClick={() => onReview?.(asset.id, { review_status: "rejected" })}>
                            驳回
                          </button>
                        </div>
                      ) : (
                        <span className="meta-note">仅管理员可审核</span>
                      )}
                    </td>
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
