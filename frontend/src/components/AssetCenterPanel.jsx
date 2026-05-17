import { useMemo, useState } from "react";

import { formatDateTime } from "../lib/taskPresentation.js";

const ASSET_TYPE_OPTIONS = [
  { value: "dataset", label: "数据集" },
  { value: "model", label: "模型" },
  { value: "workflow", label: "工作流" },
  { value: "report", label: "报告" },
];

const STATUS_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "marketplace", label: "广场" },
  { value: "private", label: "私有" },
  { value: "pending_review", label: "待审核" },
  { value: "forked", label: "Fork" },
];

const STATUS_LABELS = {
  private: "私有",
  pending_review: "待审核",
  approved: "已通过",
  published: "已发布",
  rejected: "已驳回",
};

const ASSET_RENDER_LIMIT = 200;

const EMPTY_FORM = {
  asset_type: "dataset",
  title: "",
  description: "",
  storage_path: "",
  category: "",
  tags: "",
  visibility: "private",
  version: "1.0.0",
  source_task_id: "",
  model_card: "",
  review_status: "private",
};

export default function AssetCenterPanel({
  assets,
  selectedTask,
  loading,
  creating,
  reviewingAssetId,
  publishingAssetId,
  forkingAssetId,
  message,
  error,
  isAdmin,
  onRefresh,
  onCreate,
  onReview,
  onPublish,
  onFork,
  onCreateFromTask,
}) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [activeType, setActiveType] = useState("all");
  const [activeStatus, setActiveStatus] = useState("all");
  const visibleAssets = useMemo(
    () => (Array.isArray(assets) ? assets : []).filter((item) => {
      const typeMatched = activeType === "all" ? true : item.asset_type === activeType;
      if (!typeMatched) return false;
      if (activeStatus === "all") return true;
      if (activeStatus === "marketplace") return item.review_status === "published";
      if (activeStatus === "forked") return Boolean(item.metadata?.fork?.forked_from_asset_id);
      return item.review_status === activeStatus;
    }),
    [activeStatus, activeType, assets],
  );
  const renderedAssets = visibleAssets.slice(0, ASSET_RENDER_LIMIT);
  const marketplaceCount = useMemo(
    () => (Array.isArray(assets) ? assets : []).filter((item) => item.review_status === "published").length,
    [assets],
  );
  const forkedCount = useMemo(
    () => (Array.isArray(assets) ? assets : []).filter((item) => item.metadata?.fork?.forked_from_asset_id).length,
    [assets],
  );

  function handleSubmit(event) {
    event.preventDefault();
    let modelCard = null;
    if (form.model_card.trim()) {
      try {
        modelCard = JSON.parse(form.model_card);
      } catch {
        window.alert("模型卡片 JSON 格式不正确。");
        return;
      }
    }
    onCreate?.({
      asset_type: form.asset_type,
      title: form.title.trim(),
      description: form.description.trim() || null,
      storage_path: form.storage_path.trim() || null,
      category: form.category.trim() || null,
      tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean),
      visibility: form.visibility,
      version: form.version.trim() || null,
      source_task_id: form.source_task_id.trim() || null,
      model_card: modelCard,
      review_status: form.review_status,
    });
    setForm(EMPTY_FORM);
  }

  function handleEditMetadata(asset) {
    const category = window.prompt("分类", asset.category || "");
    if (category === null) return;
    const tags = window.prompt("标签，用逗号分隔", Array.isArray(asset.tags) ? asset.tags.join(", ") : "");
    if (tags === null) return;
    const visibility = window.prompt("可见性：private / team / public / unlisted", asset.visibility || "private");
    if (visibility === null) return;
    onReview?.(asset.id, {
      review_status: asset.review_status,
      category: category.trim() || null,
      tags: tags.split(",").map((item) => item.trim()).filter(Boolean),
      visibility: visibility.trim() || "private",
    });
  }

  return (
    <div className="detail-stack asset-page-layout">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>资产广场</h3>
            <p>这里统一管理数据集、模型、工作流和报告记录，已支持团队内发布和 Fork 派生。</p>
          </div>
          <button type="button" className="chip-button" onClick={onRefresh} disabled={loading}>
            {loading ? "刷新中..." : "刷新资产"}
          </button>
        </div>

        {message ? <div className="notice-banner">{message}</div> : null}
        {error ? <div className="error-banner">{error}</div> : null}

        <div className="summary-grid">
          <article className="summary-item"><span>资产总数</span><strong>{Array.isArray(assets) ? assets.length : 0}</strong></article>
          <article className="summary-item"><span>广场发布</span><strong>{marketplaceCount}</strong></article>
          <article className="summary-item"><span>Fork 资产</span><strong>{forkedCount}</strong></article>
          <article className="summary-item"><span>当前筛选</span><strong>{visibleAssets.length}</strong></article>
        </div>

        <details className="expert-advanced-fold">
          <summary>
            <span>登记或沉淀新资产</span>
            <small>手工登记、从当前任务沉淀数据集/模型/报告</small>
          </summary>
          <div className="expert-advanced-stack">
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
            <label className="field">
              <span>可见性</span>
              <select value={form.visibility} onChange={(event) => setForm((current) => ({ ...current, visibility: event.target.value }))}>
                <option value="private">private</option>
                <option value="team">team</option>
                <option value="public">public</option>
                <option value="unlisted">unlisted</option>
              </select>
            </label>
          </div>
          <div className="form-row">
            <label className="field">
              <span>分类</span>
              <input value={form.category} onChange={(event) => setForm((current) => ({ ...current, category: event.target.value }))} placeholder="例如：tabular_regression" />
            </label>
            <label className="field">
              <span>标签</span>
              <input value={form.tags} onChange={(event) => setForm((current) => ({ ...current, tags: event.target.value }))} placeholder="多个标签用逗号分隔" />
            </label>
            <label className="field">
              <span>版本</span>
              <input value={form.version} onChange={(event) => setForm((current) => ({ ...current, version: event.target.value }))} />
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
          <label className="field">
            <span>来源任务 ID</span>
            <input value={form.source_task_id} onChange={(event) => setForm((current) => ({ ...current, source_task_id: event.target.value }))} placeholder="可选，关联任务来源" />
          </label>
          <label className="field">
            <span>模型卡片 JSON</span>
            <textarea value={form.model_card} onChange={(event) => setForm((current) => ({ ...current, model_card: event.target.value }))} rows={4} placeholder='模型资产可填写，例如 {"metric_name":"accuracy","metric_value":0.91}' />
          </label>
          <div className="button-row">
            <button type="submit" className="primary-button" disabled={creating}>{creating ? "创建中..." : "登记资产"}</button>
          </div>
        </form>

        <div className="callout">
          <strong>从当前任务沉淀</strong>
          <p>{selectedTask ? `当前任务：${selectedTask.name}` : "先在任务页选择一个任务，再把数据集、模型、报告或工作流登记为待审核资产。"}</p>
          <div className="button-row">
            <button type="button" className="ghost-button" disabled={!selectedTask || creating} onClick={() => onCreateFromTask?.("dataset")}>数据集</button>
            <button type="button" className="ghost-button" disabled={!selectedTask || creating} onClick={() => onCreateFromTask?.("model")}>模型</button>
            <button type="button" className="ghost-button" disabled={!selectedTask || creating} onClick={() => onCreateFromTask?.("report")}>报告</button>
            <button type="button" className="ghost-button" disabled={!selectedTask || creating} onClick={() => onCreateFromTask?.("workflow")}>工作流</button>
          </div>
        </div>
          </div>
        </details>
      </section>

      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>数据 / 模型 / 工作流广场</h3>
            <p>列表展示已经写入平台资产表的真实记录；Fork 会保留来源资产 ID 和来源元数据。</p>
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
            <div className="segmented-control">
              {STATUS_OPTIONS.map((option) => (
                <button key={option.value} type="button" className={activeStatus === option.value ? "segment-button active" : "segment-button"} onClick={() => setActiveStatus(option.value)}>
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {!visibleAssets.length ? <div className="empty-state">当前筛选条件下还没有资产记录。</div> : null}

        {visibleAssets.length > ASSET_RENDER_LIMIT ? <div className="notice-banner compact">当前仅渲染前 {ASSET_RENDER_LIMIT} 条资产记录，避免大表格拖慢页面。</div> : null}
        {visibleAssets.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>标题</th><th>类型</th><th>分类 / 标签</th><th>来源</th><th>状态</th><th>更新时间</th><th>操作</th></tr>
              </thead>
              <tbody>
                {renderedAssets.map((asset) => (
                  <tr key={asset.id}>
                    <td>
                      <div className="table-cell-stack">
                        <strong>{asset.title}</strong>
                        <span>{asset.storage_path || asset.description || "暂无描述"}</span>
                      </div>
                    </td>
                    <td>{asset.asset_type}</td>
                    <td>
                      <div className="table-cell-stack">
                        <strong>{asset.category || "未分类"}</strong>
                        <span>{Array.isArray(asset.tags) && asset.tags.length ? asset.tags.join(" / ") : "未打标签"}</span>
                        <span>{asset.visibility || "private"} · v{asset.version || "未记录"}</span>
                      </div>
                    </td>
                    <td>
                      <div className="table-cell-stack">
                        <strong>{asset.creator_display_name || asset.creator_email || asset.created_by || "-"}</strong>
                        <span>{asset.source_asset_id || asset.metadata?.fork?.forked_from_asset_id ? `Fork 自 ${asset.source_asset_id || asset.metadata.fork.forked_from_asset_id}` : asset.source_task_id ? `任务 ${asset.source_task_id}` : "原始登记"}</span>
                      </div>
                    </td>
                    <td>{STATUS_LABELS[asset.review_status] ?? asset.review_status}</td>
                    <td>{formatDateTime(asset.updated_at)}</td>
                    <td>
                      <div className="button-row">
                        <button type="button" className="ghost-button" disabled={forkingAssetId === asset.id} onClick={() => onFork?.(asset)}>
                          {forkingAssetId === asset.id ? "Fork 中..." : "Fork"}
                        </button>
                        <button type="button" className="ghost-button" disabled={publishingAssetId === asset.id || asset.review_status === "published"} onClick={() => onPublish?.(asset.id, "public")}>
                          {publishingAssetId === asset.id ? "发布中..." : "发布"}
                        </button>
                        {isAdmin ? (
                          <>
                          <button type="button" className="ghost-button" disabled={reviewingAssetId === asset.id} onClick={() => handleEditMetadata(asset)}>
                            分类标签
                          </button>
                          <button type="button" className="ghost-button" disabled={reviewingAssetId === asset.id} onClick={() => onReview?.(asset.id, { review_status: "approved" })}>
                            {reviewingAssetId === asset.id ? "处理中..." : "通过"}
                          </button>
                          <button type="button" className="ghost-button" disabled={reviewingAssetId === asset.id} onClick={() => onReview?.(asset.id, { review_status: "rejected" })}>
                            驳回
                          </button>
                          </>
                        ) : null}
                      </div>
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
