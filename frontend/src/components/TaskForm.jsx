export default function TaskForm({
  form,
  onChange,
  onFileChange,
  onSubmit,
  submitting
}) {
  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">任务创建表单</p>
          <h2>创建任务并上传数据</h2>
        </div>
      </div>
      <form className="task-form" onSubmit={onSubmit}>
        <label>
          任务名称
          <input
            name="name"
            value={form.name}
            onChange={onChange}
            placeholder="例如：农作物产量预测"
            required
          />
        </label>
        <label>
          任务描述
          <textarea
            name="description"
            value={form.description}
            onChange={onChange}
            placeholder="使用上传的数据集预测目标列，并给出可解释结果。"
            required
            rows={4}
          />
        </label>
        <div className="form-row">
          <label>
            标签列
            <input
              name="label_column"
              value={form.label_column}
              onChange={onChange}
              placeholder="yield"
              required
            />
          </label>
          <label>
            问题类型
            <select name="problem_type" value={form.problem_type} onChange={onChange}>
              <option value="classification">classification（分类）</option>
              <option value="regression">regression（回归）</option>
            </select>
          </label>
        </div>
        <label>
          CSV 数据集
          <input type="file" accept=".csv" onChange={onFileChange} required />
        </label>
        <button type="submit" className="primary" disabled={submitting}>
          {submitting ? "提交中..." : "创建任务并上传 CSV"}
        </button>
      </form>
    </section>
  );
}
