import { useEffect, useMemo, useState, useTransition, useDeferredValue } from "react";

import AuthBar from "./components/AuthBar.jsx";
import TaskCard from "./components/TaskCard.jsx";
import TaskForm from "./components/TaskForm.jsx";
import SystemPanel from "./components/SystemPanel.jsx";
import { api, hasAuthToken } from "./lib/api.js";

const initialForm = {
  name: "",
  description: "",
  label_column: "",
  problem_type: "classification"
};

const stageOrder = ["需求解析", "数据分析", "模型选择", "训练验证", "报告生成"];
const allPageDefs = [
  { key: "overview", label: "系统状态", desc: "健康检查与运行环境" },
  { key: "tasks", label: "任务中心", desc: "创建、上传、运行、查看" },
  { key: "workflow", label: "工作流进度", desc: "阶段状态与简要日志" },
  { key: "report", label: "模型分析报告", desc: "指标与排行榜" },
  { key: "code", label: "代码查看/编辑", desc: "产物路径与脚本" },
  { key: "admin", label: "管理员后台", desc: "用户、角色、额度", adminOnly: true },
  { key: "assets", label: "资产中心", desc: "数据集 / 模型 / 工作流" }
];

function deriveStages(task) {
  if (!task) return stageOrder.map((name) => ({ name, status: "pending" }));
  const status = task.status;
  if (status === "completed") {
    return stageOrder.map((name) => ({ name, status: "done" }));
  }
  if (status === "running") {
    return stageOrder.map((name, index) => ({
      name,
      status: index < 3 ? "done" : index === 3 ? "running" : "pending"
    }));
  }
  if (status === "uploaded") {
    return stageOrder.map((name, index) => ({ name, status: index < 1 ? "done" : "pending" }));
  }
  return stageOrder.map((name, index) => ({ name, status: index === 0 ? "running" : "pending" }));
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [users, setUsers] = useState([]);
  const [currentUser, setCurrentUser] = useState(null);
  const [file, setFile] = useState(null);
  const [form, setForm] = useState(initialForm);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [runningTaskId, setRunningTaskId] = useState("");
  const [activePage, setActivePage] = useState("overview");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [roleDraft, setRoleDraft] = useState({});
  const [quotaDraft, setQuotaDraft] = useState({});
  const [isPending, startTransition] = useTransition();
  const deferredTasks = useDeferredValue(tasks);

  const selectedTask = useMemo(
    () => deferredTasks.find((task) => task.id === selectedTaskId) ?? deferredTasks[0] ?? null,
    [deferredTasks, selectedTaskId]
  );
  const stageRows = useMemo(() => deriveStages(selectedTask), [selectedTask]);
  const totalDone = stageRows.filter((item) => item.status === "done").length;
  const progress = Math.round((totalDone / stageRows.length) * 100);

  const pageDefs = useMemo(
    () => allPageDefs.filter((p) => !p.adminOnly || currentUser?.role === "admin"),
    [currentUser]
  );

  async function refreshAll() {
    try {
      let profile = null;
      if (hasAuthToken()) {
        try {
          profile = await api.me();
          setCurrentUser(profile);
        } catch {
          api.logout();
          profile = null;
          setCurrentUser(null);
        }
      } else {
        setCurrentUser(null);
      }

      const [healthData, taskData] = await Promise.all([api.health(), api.listTasks()]);

      let userItems = [];
      if (profile?.role === "admin") {
        try {
          userItems = (await api.listUsers()).items ?? [];
        } catch {
          userItems = [];
        }
      }

      startTransition(() => {
        setHealth(healthData);
        setTasks(taskData.items);
        setUsers(userItems);
        setSelectedTaskId((prev) => {
          if (prev && taskData.items.some((t) => t.id === prev)) return prev;
          return taskData.items[0]?.id ?? "";
        });
      });
    } catch (error) {
      setMessage(error.message);
    }
  }

  useEffect(() => {
    void refreshAll();
  }, []);

  useEffect(() => {
    if (activePage === "admin" && currentUser?.role !== "admin") {
      setActivePage("overview");
    }
  }, [activePage, currentUser]);

  useEffect(() => {
    if (!selectedTask || selectedTask.status !== "running") return undefined;
    const id = selectedTask.id;
    const timer = window.setInterval(async () => {
      try {
        const updated = await api.getTask(id);
        setTasks((prev) => prev.map((t) => (t.id === id ? updated : t)));
      } catch {
        /* ignore transient errors */
      }
    }, 4000);
    return () => window.clearInterval(timer);
  }, [selectedTask?.id, selectedTask?.status]);

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
      setMessage("请先选择 CSV 文件。");
      return;
    }
    setSubmitting(true);
    setMessage("");
    try {
      const task = await api.createTask(form);
      await api.uploadDataset(task.id, file);
      setForm(initialForm);
      setFile(null);
      setMessage(`任务 ${task.id} 创建成功。`);
      await refreshAll();
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
      setMessage(`任务 ${taskId} 已完成一次 MLZero 运行。`);
      await refreshAll();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setRunningTaskId("");
    }
  }

  async function handleRoleUpdate(userId) {
    const role = roleDraft[userId];
    if (!role) return;
    try {
      await api.updateUserRole(userId, role);
      setMessage(`用户 ${userId} 角色已更新为 ${role}。`);
      await refreshAll();
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function handleQuotaUpdate(userId) {
    const draft = Number(quotaDraft[userId]);
    if (Number.isNaN(draft)) return;
    try {
      await api.updateUserQuota(userId, draft);
      setMessage(`用户 ${userId} 配额已更新为 ${draft}。`);
      await refreshAll();
    } catch (error) {
      setMessage(error.message);
    }
  }

  function renderPage() {
    if (activePage === "overview") {
      return <SystemPanel health={health} />;
    }

    if (activePage === "tasks") {
      return (
        <section className="page-grid">
          <div className="left-column">
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
                <p className="eyebrow">任务列表与详情</p>
                <h2>任务中心</h2>
              </div>
              <span className="muted">{isPending ? "刷新中..." : `${deferredTasks.length} 个任务`}</span>
            </div>
            <div className="task-grid">
              {deferredTasks.map((task) => (
                <button
                  type="button"
                  key={task.id}
                  className={`task-picker ${selectedTask?.id === task.id ? "is-active" : ""}`}
                  onClick={() => setSelectedTaskId(task.id)}
                >
                  <span>{task.name}</span>
                  <small>{task.status}</small>
                </button>
              ))}
            </div>
            {selectedTask ? (
              <TaskCard task={selectedTask} onRun={handleRun} running={runningTaskId === selectedTask.id} />
            ) : (
              <div className="empty-state">
                <strong>暂无任务</strong>
              </div>
            )}
          </section>
        </section>
      );
    }

    if (activePage === "workflow") {
      return (
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">工作流</p>
              <h2>阶段进度</h2>
            </div>
            <span className="muted">当前任务：{selectedTask?.id ?? "未选择"}</span>
          </div>
          <div className="progress-bar">
            <span style={{ width: `${progress}%` }} />
          </div>
          <p className="muted">
            完成度约 {progress}%。任务处于「运行中」时每 4 秒自动刷新；下方展示平台备注。
          </p>
          {selectedTask?.notes ? (
            <pre className="log-preview">{selectedTask.notes}</pre>
          ) : (
            <p className="muted">暂无运行备注。</p>
          )}
          <div className="stage-list">
            {stageRows.map((item) => (
              <div key={item.name} className={`stage-row stage-${item.status}`}>
                <strong>{item.name}</strong>
                <span>
                  {item.status === "done" ? "已完成" : item.status === "running" ? "进行中" : "未开始"}
                </span>
              </div>
            ))}
          </div>
        </section>
      );
    }

    if (activePage === "report") {
      const leaderboard = selectedTask?.last_run?.leaderboard ?? [];
      return (
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">分析报告</p>
              <h2>模型与指标</h2>
            </div>
          </div>
          {selectedTask?.last_run ? (
            <div className="report-stack">
              <div className="report-grid">
                <div>
                  <span className="meta-label">最佳模型</span>
                  <strong>{selectedTask.last_run.best_model}</strong>
                </div>
                <div>
                  <span className="meta-label">核心指标</span>
                  <strong>
                    {selectedTask.last_run.metric_name}: {selectedTask.last_run.metric_value.toFixed(4)}
                  </strong>
                </div>
                <div>
                  <span className="meta-label">说明</span>
                  <p className="muted">
                    {selectedTask.last_run.metric_name} 为当前运行返回的主指标，可根据问题类型解读优劣。
                  </p>
                </div>
              </div>
              {leaderboard.length > 0 ? (
                <div className="leaderboard">
                  <p className="eyebrow">节点与得分摘要</p>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>节点</th>
                        <th>工具</th>
                        <th>validation_score</th>
                      </tr>
                    </thead>
                    <tbody>
                      {leaderboard.slice(0, 12).map((row, idx) => (
                        <tr key={idx}>
                          <td>{String(row.node ?? "")}</td>
                          <td className="muted">{String(row.tool ?? "")}</td>
                          <td>
                            {typeof row.validation_score === "number"
                              ? row.validation_score.toFixed(4)
                              : String(row.validation_score ?? "")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </div>
          ) : (
            <p className="muted">该任务暂无运行结果。请先在「任务中心」完成一次运行。</p>
          )}
        </section>
      );
    }

    if (activePage === "code") {
      const outDir = selectedTask?.last_run?.output_dir ?? "";
      const snippet = outDir
        ? `# 本次运行输出目录（本地）\n# ${outDir}\n`
        : `# 运行完成后将显示产物目录。\n# 代码编辑能力将在后端开放 artifacts 接口后启用。\n`;
      return (
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">代码与产物</p>
              <h2>脚本与路径</h2>
            </div>
          </div>
          <p className="muted">
            下方展示本次 MLZero 运行的本地输出路径；完整脚本托管能力待后端 artifacts API 就绪后对接。
          </p>
          {selectedTask?.notes ? <pre className="log-preview">{selectedTask.notes}</pre> : null}
          <textarea className="code-box" readOnly value={snippet} />
        </section>
      );
    }

    if (activePage === "admin") {
      return (
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">管理后台</p>
              <h2>用户与额度</h2>
            </div>
          </div>
          {users.length ? (
            <div className="admin-grid">
              {users.map((user) => (
                <article className="user-card" key={user.id}>
                  <strong>{user.username}</strong>
                  <p className="muted">{user.email}</p>
                  <div className="inline-form">
                    <select
                      value={roleDraft[user.id] ?? user.role}
                      onChange={(event) => setRoleDraft((current) => ({ ...current, [user.id]: event.target.value }))}
                    >
                      <option value="user">user（业务用户）</option>
                      <option value="developer">developer（开发者）</option>
                      <option value="admin">admin（管理员）</option>
                    </select>
                    <button type="button" className="secondary" onClick={() => handleRoleUpdate(user.id)}>
                      更新角色
                    </button>
                  </div>
                  <div className="inline-form">
                    <input
                      type="number"
                      min={0}
                      value={quotaDraft[user.id] ?? user.api_token_quota ?? 0}
                      onChange={(event) =>
                        setQuotaDraft((current) => ({ ...current, [user.id]: event.target.value }))
                      }
                    />
                    <button type="button" className="secondary" onClick={() => handleQuotaUpdate(user.id)}>
                      更新额度
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <p className="muted">请以管理员账号登录后查看用户列表。</p>
          )}
        </section>
      );
    }

    return (
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">资产中心</p>
            <h2>数据集 · 模型 · 工作流</h2>
          </div>
          <span className="pill">即将上线</span>
        </div>
        <div className="asset-grid">
          <article>
            <strong>数据集</strong>
            <p className="muted">审核、可见范围与公开发布。</p>
          </article>
          <article>
            <strong>模型</strong>
            <p className="muted">指标对比、复用与下架管理。</p>
          </article>
          <article>
            <strong>工作流</strong>
            <p className="muted">发布、Fork 与版本沉淀。</p>
          </article>
        </div>
      </section>
    );
  }

  return (
    <main className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">AI4ML 平台</p>
          <h1>AI4ML 智能建模平台</h1>
          <p className="hero-copy">
            面向零基础业务用户与开发者：任务与数据上传、运行跟踪、结果解读与平台治理一站完成。
          </p>
        </div>
        <div className="hero-badge">
          <span>执行底座</span>
          <strong>{health?.selected_project_base ?? "MLZero / AutoGluon Assistant"}</strong>
        </div>
      </header>

      <AuthBar currentUser={currentUser} onSessionChange={() => refreshAll()} />

      {message ? <div className="message">{message}</div> : null}
      <nav className="page-tabs">
        {pageDefs.map((page) => (
          <button
            key={page.key}
            type="button"
            className={activePage === page.key ? "tab is-active" : "tab"}
            onClick={() => setActivePage(page.key)}
          >
            <strong>{page.label}</strong>
            <small>{page.desc}</small>
          </button>
        ))}
      </nav>
      {renderPage()}
    </main>
  );
}
