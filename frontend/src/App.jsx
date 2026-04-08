import { useEffect, useState, useTransition, useDeferredValue } from "react";

import TaskCard from "./components/TaskCard.jsx";
import TaskForm from "./components/TaskForm.jsx";
import SystemPanel from "./components/SystemPanel.jsx";
import { api } from "./lib/api.js";

const initialForm = {
  name: "",
  description: "",
  label_column: "",
  problem_type: "classification"
};

export default function App() {
  const [health, setHealth] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [file, setFile] = useState(null);
  const [form, setForm] = useState(initialForm);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [runningTaskId, setRunningTaskId] = useState("");
  const [isPending, startTransition] = useTransition();
  const deferredTasks = useDeferredValue(tasks);

  useEffect(() => {
    void refresh();
  }, []);

  async function refresh() {
    try {
      const [healthData, taskData] = await Promise.all([api.health(), api.listTasks()]);
      startTransition(() => {
        setHealth(healthData);
        setTasks(taskData.items);
      });
    } catch (error) {
      setMessage(error.message);
    }
  }

  function handleChange(event) {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
  }

  function handleFileChange(event) {
    const nextFile = event.target.files?.[0] ?? null;
    setFile(nextFile);
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!file) {
      setMessage("Please choose a CSV file first.");
      return;
    }
    setSubmitting(true);
    setMessage("");
    try {
      const task = await api.createTask(form);
      await api.uploadDataset(task.id, file);
      setForm(initialForm);
      setFile(null);
      setMessage(`Task ${task.id} created.`);
      await refresh();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRun(taskId) {
    setRunningTaskId(taskId);
    setMessage("");
    try {
      await api.runTask(taskId, 20);
      setMessage(`Task ${taskId} finished an MLZero run.`);
      await refresh();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setRunningTaskId("");
    }
  }

  return (
    <main className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">AI4ML / Week 2</p>
          <h1>Task intake and MLZero validation runtime</h1>
          <p className="hero-copy">
            This console locks in the Week 2 repo structure: task creation,
            CSV upload, backend status, and a verified local MLZero execution path.
          </p>
        </div>
        <div className="hero-badge">
          <span>Selected kernel</span>
          <strong>MLZero / AutoGluon Assistant</strong>
        </div>
      </header>

      {message ? <div className="message">{message}</div> : null}

      <section className="layout">
        <div className="left-column">
          <SystemPanel health={health} />
          <TaskForm
            form={form}
            onChange={handleChange}
            onFileChange={handleFileChange}
            onSubmit={handleSubmit}
            submitting={submitting}
          />
        </div>
        <section className="panel right-column">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Local task store</p>
              <h2>Tasks</h2>
            </div>
            <span className="muted">{isPending ? "Refreshing..." : `${deferredTasks.length} task(s)`}</span>
          </div>
          <div className="task-grid">
            {deferredTasks.length ? (
              deferredTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  onRun={handleRun}
                  running={runningTaskId === task.id}
                />
              ))
            ) : (
              <div className="empty-state">
                <strong>No tasks yet.</strong>
                <p>Create the first CSV task to seed the Week 3 prototype flow.</p>
              </div>
            )}
          </div>
        </section>
      </section>
    </main>
  );
}
