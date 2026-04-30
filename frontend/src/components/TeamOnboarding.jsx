import { useState } from "react";

export default function TeamOnboarding({
  userLabel,
  busy,
  error,
  message,
  onCreateTeam,
  onJoinTeam,
  onLogout,
}) {
  const [teamName, setTeamName] = useState("");
  const [teamCode, setTeamCode] = useState("");

  async function handleCreate(event) {
    event.preventDefault();
    await onCreateTeam(teamName);
    setTeamName("");
  }

  async function handleJoin(event) {
    event.preventDefault();
    await onJoinTeam(teamCode);
    setTeamCode("");
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="auth-copy">
          <p className="eyebrow">团队初始化</p>
          <h1>先进入一个团队，再开始录入连接器和任务</h1>
          <p>
            当前登录账号是 <strong>{userLabel}</strong>。任务、CSV、连接器和运行结果都会按团队隔离，
            所以第一次进入时需要先创建团队，或者输入邀请码加入已有团队。
          </p>
        </div>

        {message ? <div className="notice-banner auth-banner">{message}</div> : null}
        {error ? <div className="error-banner">{error}</div> : null}

        <div className="auth-grid">
          <form className="section-card" onSubmit={handleCreate}>
            <div className="section-head">
              <div>
                <h3>创建团队</h3>
                <p>创建后你会自动成为该团队的管理员。</p>
              </div>
            </div>

            <label className="field">
              <span>团队名称</span>
              <input
                value={teamName}
                onChange={(event) => setTeamName(event.target.value)}
                placeholder="例如：农业产量分析组"
                required
              />
            </label>

            <div className="button-row">
              <button type="submit" className="primary-button" disabled={busy}>
                {busy ? "处理中..." : "创建团队"}
              </button>
            </div>
          </form>

          <form className="section-card" onSubmit={handleJoin}>
            <div className="section-head">
              <div>
                <h3>加入团队</h3>
                <p>请输入管理员分享给你的 8 位邀请码。</p>
              </div>
            </div>

            <label className="field">
              <span>邀请码</span>
              <input
                value={teamCode}
                onChange={(event) => setTeamCode(event.target.value.toUpperCase())}
                placeholder="AB12CD34"
                required
              />
            </label>

            <div className="button-row">
              <button type="submit" className="ghost-button" disabled={busy}>
                {busy ? "处理中..." : "加入团队"}
              </button>
            </div>
          </form>
        </div>

        <div className="button-row">
          <button type="button" className="chip-button" onClick={onLogout}>
            退出登录
          </button>
        </div>
      </section>
    </main>
  );
}
