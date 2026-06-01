import { optionalRequest, request } from '@/api/request'
import { nativeRole, normalizeRole } from '@/api/session'

export async function getUsers() {
  const [memberData, quotaData] = await Promise.all([
    request('/members'),
    optionalRequest('/quotas', {}, { items: [] }),
  ])
  const quotaByUser = new Map(
    (quotaData.items || [])
      .filter((item) => item.scope_type === 'member' && (item.user_id || item.scope_key))
      .map((item) => [item.user_id || item.scope_key, item]),
  )
  return {
    items: (memberData.items || []).map((member) => {
      const quota = quotaByUser.get(member.user_id) || {}
      return {
        user_id: member.user_id,
        display_name: member.profile?.display_name || member.profile?.email || member.user_id,
        email: member.profile?.email,
        original_display_name: member.profile?.display_name || member.profile?.email || member.user_id,
        role: normalizeRole(member.role),
        original_role: normalizeRole(member.role),
        native_role: member.role,
        original_native_role: member.role,
        member_status: member.member_status || 'active',
        token_quota: Number(quota.token_quota || 0),
        original_token_quota: Number(quota.token_quota || 0),
        token_used: Number(quota.token_used || 0),
        token_remaining: quota.token_remaining === null || quota.token_remaining === undefined
          ? Math.max(0, Number(quota.token_quota || 0) - Number(quota.token_used || 0))
          : Number(quota.token_remaining),
        quota_status: quota.status || 'active',
        original_quota_status: quota.status || 'active',
        warning_threshold: quota.warning_threshold || 0,
        original_warning_threshold: quota.warning_threshold || 0,
        is_active: member.member_status === 'active' && quota.status !== 'frozen',
        original_is_active: member.member_status === 'active' && quota.status !== 'frozen',
      }
    }),
  }
}

export async function getTeamSettings() {
  const data = await request('/settings')
  return data.team || null
}

export async function getTeamMembers() {
  const data = await request('/members')
  return {
    team_id: data.team_id,
    items: (data.items || []).map((member) => ({
      user_id: member.user_id,
      display_name: member.profile?.display_name || member.profile?.email || member.user_id,
      email: member.profile?.email || '',
      role: member.role || 'member',
      role_label: normalizeRole(member.role),
      member_status: member.member_status || 'active',
      joined_at: member.joined_at || null,
      invited_by: member.invited_by || '',
    })),
  }
}

export async function createTeamInvite(payload = {}) {
  return request('/members/invite', {
    method: 'POST',
    body: JSON.stringify({
      email: payload.email || null,
      note: payload.note || null,
    }),
  })
}

export async function updateTeamMemberRole(userId, role) {
  const result = await request(`/members/${userId}/role`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  })
  return result.member
}

export async function updateTeamMemberStatus(userId, memberStatus) {
  const result = await request(`/members/${userId}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ member_status: memberStatus }),
  })
  return result.member
}

export async function updateUser(userId, payload) {
  const body = {}
  if (
    Object.prototype.hasOwnProperty.call(payload, 'display_name')
    && String(payload.display_name || '').trim() !== String(payload.original_display_name || '').trim()
  ) {
    body.display_name = String(payload.display_name || '').trim()
  }
  const nextRole = nativeRole(payload.role)
  const originalNativeRole = payload.original_native_role || ''
  if (!(originalNativeRole === 'team_owner' && nextRole === 'admin') && nextRole !== originalNativeRole) {
    body.role = nextRole
  }
  const nextActive = Boolean(payload.is_active)
  if (nextActive !== Boolean(payload.original_is_active)) {
    body.member_status = nextActive ? 'active' : 'frozen'
    body.quota_status = nextActive ? 'active' : 'frozen'
  } else if (nextActive && payload.original_quota_status && payload.original_quota_status !== 'active') {
    body.quota_status = 'active'
  }
  const nextTokenQuota = Number(payload.token_quota || 0)
  if (nextTokenQuota !== Number(payload.original_token_quota || 0)) {
    body.token_quota = nextTokenQuota
    if (
      !body.quota_status
      && payload.original_quota_status === 'exhausted'
      && nextTokenQuota > Number(payload.token_used || 0)
    ) {
      body.quota_status = 'active'
    }
  }
  const nextWarningThreshold = Number(payload.warning_threshold || 0)
  if (nextWarningThreshold !== Number(payload.original_warning_threshold || 0)) {
    body.warning_threshold = nextWarningThreshold
  }
  return request(`/admin/users/${userId}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export async function resetUserPassword(userId, password) {
  return request(`/admin/users/${userId}/reset-password`, {
    method: 'POST',
    body: JSON.stringify({ password }),
  })
}

export async function getPlatformLimits() {
  return request('/admin/platform-limits')
}

export async function updatePlatformLimits(payload) {
  return request('/admin/platform-limits', { method: 'PUT', body: JSON.stringify(payload) })
}
