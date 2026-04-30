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

  return (
    <section className="section-card task-form-card">
      <div className="section-head">
        <div>
          <p className="eyebrow">Step 1</p>
          <h3>创建任务并上传 CSV</h3>
          <p>这里一次性配置任务描述、阶段 AI 覆盖和人工参与策略。未覆盖的阶段会继承团队默认路由。</p>
        </div>
      </div>

      <form className="task-form" onSubmit={onSubmit}>
        <label className="field">
          <span>任务名称</span>
          <input
            name="name"
            value={form.name}
            onChange={(event) => onFieldChange("name", event.target.value)}
            placeholder="例如：预测产量"
            required
          />
        </label>

        <label className="field">
          <span>任务描述</span>
          <textarea
            name="description"
            value={form.description}
            onChange={(event) => onFieldChange("description", event.target.value)}
            placeholder="例如：请根据土壤和气象特征预测作物产量，目标列是 yield。"
            rows={5}
            required
          />
        </label>

        <div className="placeholder-panel">
          <strong>技术字段仍然由 AI 自动解析</strong>
          <p>上传后，系统会把任务描述、CSV 列名和预览样本发给当前阶段路由对应的 AI，自动填充目标列、任务类型和建议指标。</p>
        </div>

        <section className="task-subsection">
          <div className="section-head">
            <div>
              <h3>阶段 AI 覆盖</h3>
              <p>只在当前任务上生效。留空表示继承团队默认 AI 路由。</p>
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
                      <p>覆盖当前任务在这个阶段使用的连接器和模型。</p>
                    </div>
                  </div>
                  <div className="form-row">
                    <label className="field">
                      <span>连接器</span>
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
                      <span>模型覆盖</span>
                      <input
                        value={current.model_name || ""}
                        onChange={(event) => onStageRoutingChange(stage.value, "model_name", event.target.value)}
                        placeholder="留空则跟随选中连接器或团队默认模型"
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
              <h3>人工参与策略</h3>
              <p>你可以在运行前或运行后自动插入人工复核节点。这里的配置会写入任务本身。</p>
            </div>
            <button type="button" className="ghost-button" onClick={onAddPolicy}>
              添加策略
            </button>
          </div>

          {!form.interaction_policies?.length ? <div className="empty-state compact">当前还没有人工参与策略。</div> : null}

          <div className="policy-list">
            {(form.interaction_policies ?? []).map((policy, index) => (
              <article key={policy.client_id ?? `${policy.stage}-${index}`} className="policy-card">
                <div className="section-head">
                  <div>
                    <h3>策略 {index + 1}</h3>
                    <p>这个策略会在对应阶段自动创建一个人机协同节点。</p>
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

        <label className="field">
          <span>CSV 数据集</span>
          <input key={fileInputKey} type="file" accept=".csv" onChange={onFileChange} required />
          <small className="helper-text">{selectedFile ? `已选择：${selectedFile.name}` : "只支持 .csv 文件"}</small>
        </label>

        <button type="submit" className="primary-button" disabled={submitting}>
          {submitting ? "提交中..." : "提交需求并上传 CSV"}
        </button>
      </form>
    </section>
  );
}
