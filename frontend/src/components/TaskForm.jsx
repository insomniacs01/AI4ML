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
          <p className="eyebrow">Week 3 input path</p>
          <h2>Create a task</h2>
        </div>
      </div>
      <form className="task-form" onSubmit={onSubmit}>
        <label>
          Task name
          <input
            name="name"
            value={form.name}
            onChange={onChange}
            placeholder="Crop yield prediction"
            required
          />
        </label>
        <label>
          Task description
          <textarea
            name="description"
            value={form.description}
            onChange={onChange}
            placeholder="Use the uploaded tabular dataset to predict the target column."
            required
            rows={4}
          />
        </label>
        <div className="form-row">
          <label>
            Target column
            <input
              name="label_column"
              value={form.label_column}
              onChange={onChange}
              placeholder="yield"
              required
            />
          </label>
          <label>
            Problem type
            <select name="problem_type" value={form.problem_type} onChange={onChange}>
              <option value="classification">classification</option>
              <option value="regression">regression</option>
            </select>
          </label>
        </div>
        <label>
          CSV dataset
          <input type="file" accept=".csv" onChange={onFileChange} required />
        </label>
        <button type="submit" className="primary" disabled={submitting}>
          {submitting ? "Submitting..." : "Create task and upload CSV"}
        </button>
      </form>
    </section>
  );
}
