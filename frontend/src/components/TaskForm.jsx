const STAGE_OPTIONS = [
  { value: "requirement_analysis", label: "需求解析" },
  { value: "data_analysis", label: "数据分析" },
  { value: "feature_engineering", label: "特征工程" },
  { value: "model_selection", label: "模型选择" },
  { value: "training_validation", label: "训练验证" },
  { value: "report_generation", label: "报告生成" },
];

const TRIGGER_MODE_OPTIONS = [
  { value: "before_run", label: "运行前" },
  { value: "in_run", label: "运行后复核" },
];

const ASSIGNEE_TYPE_OPTIONS = [
  { value: "member", label: "指定成员" },
  { value: "role", label: "按角色" },
  { value: "candidate_pool", label: "候选组" },
];

const REQUEST_TYPE_OPTIONS = [
  { value: "requirement_review", label: "需求确认" },
  { value: "data_review", label: "数据复核" },
  { value: "code_review", label: "代码复核" },
  { value: "result_review", label: "结果复核" },
];

export default function TaskForm({
  form,
  connectors,
  selectedFile,
  fileInputKey,
  onFieldChange,
  onStageRoutingChange,
  onAddPolicy,
  onPolicyChange,
  onRemovePolicy,
  onFileChange,
  onSubmit,
  submitting,
}) {
  const connectorOptions = Array.isArray(connectors) ? connectors : [];

  const derivedName = form.name?.trim() || selectedFile?.name?.replace(/\.csv$/i, "") || form.description?.trim()?.slice(0, 24) || "";

  return (
    <section className="showcase-card task-form-card task-panel">
      <form className="showcase-task-form" onSubmit={(event) => {
        if (!form.name?.trim() && derivedName) onFieldChange("name", derivedName);
        onSubmit(event);
      }}>
        <input type="hidden" name="name" value={form.name} />

        <label className="showcase-big-field">
          <span>这次想解决什么问题？</span>
          <textarea
            name="description"
            value={form.description}
            onChange={(event) => {
              const value = event.target.value;
              onFieldChange("description", value);
              if (!form.name?.trim() && value.trim()) onFieldChange("name", value.trim().slice(0, 24));
            }}
            placeholder="例如：根据土壤和天气数据预测作物产量"
            rows={4}
            required
          />
        </label>

        <label className="showcase-upload-zone">
          <input key={fileInputKey} type="file" accept=".csv" onChange={(event) => {
            const file = event.target.files?.[0] ?? null;
            if (file && !form.name?.trim()) onFieldChange("name", file.name.replace(/\.csv$/i, ""));
            onFileChange(event);
          }} required />
          <span className="upload-cloud">☁</span>
          <strong>拖入 CSV，或点击上传</strong>
          <small>{selectedFile ? `已选择：${selectedFile.name}` : "仅支持 .csv 文件，大小不超过 200MB"}</small>
        </label>

        <div className="showcase-form-actions">
          <button type="submit" className="primary-button task-submit-button" disabled={submitting}>
            {submitting ? "提交中..." : "让 AI 先理解我的需求"}
          </button>
        </div>

        <details className="task-advanced-section" hidden>
          <summary>
            <div>
              <strong>高级设置（可不填）</strong>
              <span>默认会自动选择 AI 和复核方式，只有特殊情况才需要展开</span>
            </div>
            <em>展开</em>
          </summary>

          <section className="task-subsection">
            <div className="section-head">
              <div>
                <h3>单独指定 AI</h3>
                <p>只在当前任务上生效。留空表示使用团队默认 AI 设置。</p>
              </div>
            </div>

            <div className="stage-routing-grid">
              {STAGE_OPTIONS.map((stage) => {
                const current = form.stage_routing?.find((item) => item.stage === stage.value) ?? { stage: stage.value, connector_id: "", model_name: "" };
                return (
                  <article key={stage.value} className="stage-route-card">
                    <div className="section-head">
                      <div>
                        <h3>{stage.label}</h3>
                        <p>单独指定当前任务在这个步骤使用的 AI 服务和模型。</p>
                      </div>
                    </div>
                    <div className="form-row">
                      <label className="field">
                        <span>AI 服务</span>
                        <select
                          value={current.connector_id || ""}
                          onChange={(event) => onStageRoutingChange(stage.value, "connector_id", event.target.value)}
                        >
                          <option value="">继承团队默认</option>
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
                          value={current.model_name || ""}
                          onChange={(event) => onStageRoutingChange(stage.value, "model_name", event.target.value)}
                          placeholder="留空则使用该 AI 服务的默认模型"
                          disabled={!current.connector_id}
                        />
                      </label>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>

          <section className="task-subsection">
            <div className="section-head">
              <div>
                <h3>人工确认设置</h3>
                <p>你可以让任务在某一步前后停下来，等待指定成员确认。</p>
              </div>
              <button type="button" className="ghost-button" onClick={onAddPolicy}>
                添加确认
              </button>
            </div>

            {!form.interaction_policies?.length ? <div className="empty-state compact">当前还没有人工确认设置。</div> : null}

            <div className="policy-list">
              {(form.interaction_policies ?? []).map((policy, index) => (
                <article key={policy.client_id ?? `${policy.stage}-${index}`} className="policy-card">
                  <div className="section-head">
                    <div>
                      <h3>确认设置 {index + 1}</h3>
                      <p>到达对应步骤时创建一个复核待办。</p>
                    </div>
                    <button type="button" className="ghost-button" onClick={() => onRemovePolicy(index)}>
                      删除
                    </button>
                  </div>

                  <div className="form-row">
                    <label className="field">
                      <span>阶段</span>
                      <select value={policy.stage} onChange={(event) => onPolicyChange(index, "stage", event.target.value)}>
                        {STAGE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="field">
                      <span>触发时机</span>
                      <select value={policy.trigger_mode} onChange={(event) => onPolicyChange(index, "trigger_mode", event.target.value)}>
                        {TRIGGER_MODE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="field">
                      <span>请求类型</span>
                      <select value={policy.request_type} onChange={(event) => onPolicyChange(index, "request_type", event.target.value)}>
                        {REQUEST_TYPE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>

                  <div className="form-row">
                    <label className="field">
                      <span>指派方式</span>
                      <select value={policy.assignee_type} onChange={(event) => onPolicyChange(index, "assignee_type", event.target.value)}>
                        {ASSIGNEE_TYPE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="field">
                      <span>指派值</span>
                      <input
                        value={policy.assignee_value}
                        onChange={(event) => onPolicyChange(index, "assignee_value", event.target.value)}
                        placeholder="例如：某个用户 ID、developer_user、ml-reviewers"
                        required
                      />
                    </label>

                    <label className="field">
                      <span>超时（分钟）</span>
                      <input
                        type="number"
                        min="5"
                        step="5"
                        value={policy.timeout_minutes}
                        onChange={(event) => onPolicyChange(index, "timeout_minutes", event.target.value)}
                        placeholder="例如：60"
                      />
                    </label>
                  </div>

                  <label className="field">
                    <span>标题</span>
                    <input
                      value={policy.title}
                      onChange={(event) => onPolicyChange(index, "title", event.target.value)}
                      placeholder="例如：运行前确认指标与标签列"
                      required
                    />
                  </label>

                  <label className="field">
                    <span>复核说明</span>
                    <textarea
                      rows={3}
                      value={policy.summary}
                      onChange={(event) => onPolicyChange(index, "summary", event.target.value)}
                      placeholder="明确告诉审阅人需要确认什么、为什么要停下来。"
                      required
                    />
                  </label>

                  <label className="field">
                    <span>建议动作</span>
                    <textarea
                      rows={2}
                      value={policy.suggested_action}
                      onChange={(event) => onPolicyChange(index, "suggested_action", event.target.value)}
                      placeholder="例如：确认 metric_name 是否应改为 F1。"
                    />
                  </label>
                </article>
              ))}
            </div>
          </section>
        </details>
      </form>
    </section>
  );
}
