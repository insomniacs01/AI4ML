import { useEffect, useState } from "react";

function buildInitialForm(mode) {
  return mode === "register"
    ? { displayName: "", email: "", password: "" }
    : { email: "", password: "" };
}

export default function AuthScreen({
  mode,
  busy,
  error,
  message,
  requiresEmailVerification,
  onModeChange,
  onLogin,
  onRegister,
}) {
  const [form, setForm] = useState(() => buildInitialForm(mode));

  useEffect(() => {
    setForm(buildInitialForm(mode));
  }, [mode]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (mode === "register") {
      await onRegister(form);
      return;
    }
    await onLogin(form);
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="auth-copy">
          <p className="eyebrow">Supabase 认证</p>
          <h1>进入 AI4ML 之前先登录</h1>
          <p>
            前端会用 Supabase 处理登录和团队身份，后端再根据当前团队隔离任务和 AI 设置。
            登录后，你就能直接在页面里录入 AI 服务、上传 CSV，并让 AI 理解任务。
          </p>
        </div>

        <div className="auth-tabs">
          <button type="button" className={mode === "login" ? "chip-button active-chip" : "chip-button"} onClick={() => onModeChange("login")}>
            登录
          </button>
          <button type="button" className={mode === "register" ? "chip-button active-chip" : "chip-button"} onClick={() => onModeChange("register")}>
            注册
          </button>
        </div>

        <form className="task-form" onSubmit={handleSubmit}>
          {mode === "register" ? (
            <label className="field">
              <span>显示名称</span>
              <input
                value={form.displayName}
                onChange={(event) => setForm((current) => ({ ...current, displayName: event.target.value }))}
                placeholder="团队成员将看到的名称"
                required
              />
            </label>
          ) : null}

          <label className="field">
            <span>邮箱</span>
            <input
              type="email"
              value={form.email}
              onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
              placeholder="请输入邮箱地址"
              required
            />
          </label>

          <label className="field">
            <span>密码</span>
            <input
              type="password"
              value={form.password}
              onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
              placeholder="至少 6 位字符"
              minLength={6}
              required
            />
          </label>

          {message ? <div className="notice-banner auth-banner">{message}</div> : null}
          {error ? <div className="error-banner">{error}</div> : null}

          <div className="button-row">
            <button type="submit" className="primary-button" disabled={busy}>
              {busy ? "提交中..." : mode === "register" ? "创建账号" : "登录"}
            </button>
          </div>
        </form>

        <p className="helper-text">
          {requiresEmailVerification
            ? "当前 Supabase 项目仍然开启了邮箱验证。注册成功后，如果没有自动登录，请先检查邮箱验证状态。"
            : "当前 Supabase 项目支持注册后直接登录。"}
        </p>
      </section>
    </main>
  );
}
