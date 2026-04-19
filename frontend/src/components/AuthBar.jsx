import { useState } from "react";

import { api } from "../lib/api.js";

export default function AuthBar({ currentUser, onSessionChange }) {
  const [loginUser, setLoginUser] = useState("");
  const [loginPass, setLoginPass] = useState("");
  const [regUser, setRegUser] = useState("");
  const [regPass, setRegPass] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [showRegister, setShowRegister] = useState(false);
  const [busy, setBusy] = useState(false);
  const [registerNotice, setRegisterNotice] = useState("");

  async function handleLogin(event) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.login({ username: loginUser.trim(), password: loginPass });
      setLoginPass("");
      await onSessionChange();
    } finally {
      setBusy(false);
    }
  }

  async function handleRegister(event) {
    event.preventDefault();
    setBusy(true);
    setRegisterNotice("");
    try {
      await api.register({
        username: regUser.trim(),
        password: regPass,
        email: regEmail.trim()
      });
      setRegPass("");
      setShowRegister(false);
      setLoginUser(regUser.trim());
      setRegisterNotice("注册成功，请使用上方表单登录。");
    } finally {
      setBusy(false);
    }
  }

  function handleLogout() {
    api.logout();
    void onSessionChange();
  }

  const roleLabel = {
    admin: "管理员",
    developer: "开发者",
    user: "业务用户"
  };

  return (
    <section className="auth-bar panel">
      {currentUser ? (
        <div className="auth-session">
          <div className="auth-user">
            <strong>{currentUser.username}</strong>
            <span className="muted">
              {roleLabel[currentUser.role] ?? currentUser.role} · 额度 {currentUser.api_token_quota}
            </span>
          </div>
          <button type="button" className="secondary" onClick={handleLogout}>
            退出登录
          </button>
        </div>
      ) : (
        <div className="auth-forms">
          {registerNotice ? <p className="success-notice">{registerNotice}</p> : null}
          <form className="auth-login" onSubmit={handleLogin}>
            <input
              type="text"
              autoComplete="username"
              placeholder="用户名"
              value={loginUser}
              onChange={(e) => setLoginUser(e.target.value)}
              required
            />
            <input
              type="password"
              autoComplete="current-password"
              placeholder="密码"
              value={loginPass}
              onChange={(e) => setLoginPass(e.target.value)}
              required
            />
            <button type="submit" className="primary" disabled={busy}>
              {busy ? "处理中…" : "登录"}
            </button>
          </form>
          <button
            type="button"
            className="link-button"
            onClick={() => setShowRegister((v) => !v)}
          >
            {showRegister ? "收起注册" : "注册新账号"}
          </button>
          {showRegister ? (
            <form className="auth-register" onSubmit={handleRegister}>
              <input
                type="text"
                placeholder="用户名（字母数字下划线）"
                value={regUser}
                onChange={(e) => setRegUser(e.target.value)}
                required
                minLength={3}
              />
              <input
                type="email"
                placeholder="邮箱"
                value={regEmail}
                onChange={(e) => setRegEmail(e.target.value)}
                required
              />
              <input
                type="password"
                placeholder="密码（至少 6 位）"
                value={regPass}
                onChange={(e) => setRegPass(e.target.value)}
                required
                minLength={6}
              />
              <button type="submit" className="secondary" disabled={busy}>
                提交注册
              </button>
            </form>
          ) : null}
        </div>
      )}
    </section>
  );
}
