async (page) => {
  const origin = 'http://127.0.0.1:5173'
  const userId = 'user-1'
  const teamId = 'team-1'
  const supabaseProjectRef = 'diftsjwilgifuhkkohlk'
  const now = Date.now()
  const session = {
    access_token: 'cache-render-fake-token',
    refresh_token: 'cache-render-fake-refresh',
    expires_at: Math.floor(now / 1000) + 3600,
    expires_in: 3600,
    token_type: 'bearer',
    user: {
      id: userId,
      aud: 'authenticated',
      role: 'authenticated',
      email: 'cache-render@example.com',
      user_metadata: { display_name: 'Cache Render User' },
    },
  }
  const task = {
    id: 'task-cache-render',
    task_id: 'task-cache-render',
    team_id: teamId,
    created_by: userId,
    name: 'Cache Render Task',
    display_name: 'Cache Render Task',
    requirement: 'Verify cached workspace rendering.',
    status: 'running',
    target_column: 'label',
    created_at: new Date(now).toISOString(),
    updated_at: new Date(now).toISOString(),
  }
  const workspaceCache = {
    version: 1,
    userId,
    teamId,
    cachedAt: now,
    activeTaskId: task.task_id,
    tasks: [task],
    task,
    taskRun: {
      progress_percent: 42,
      current_activity: 'Rendered from local cache.',
      codex: {
        session_id: '',
        status: 'running',
        steps: [{ id: 'cache_step', title: 'Cached step', status: 'running', detail: 'Local cache step.' }],
      },
    },
    steps: [{ id: 'cache_step', title: 'Cached step', status: 'running', agent_role: 'Codex', summary: 'Local cache step.' }],
  }

  await page.goto(`${origin}/login`, { waitUntil: 'domcontentloaded' })
  await page.evaluate(({ session, workspaceCache, supabaseProjectRef, teamId, userId }) => {
    localStorage.setItem(`sb-${supabaseProjectRef}-auth-token`, JSON.stringify(session))
    localStorage.setItem('ai4ml-active-team-id', teamId)
    localStorage.setItem(`ai4ml-workspace-cache:${userId}:${teamId}`, JSON.stringify(workspaceCache))
  }, { session, workspaceCache, supabaseProjectRef, teamId, userId })

  const startedAt = Date.now()
  await page.goto(`${origin}/workspace`, { waitUntil: 'domcontentloaded' })
  await page.getByText('Cache Render Task').waitFor({ timeout: 2000 })
  await page.getByText('42%').waitFor({ timeout: 2000 })
  return `workspace cached render verified in ${Date.now() - startedAt}ms`
}
