import { computed, onMounted, ref } from 'vue'
import {
  deleteCommunityPlan,
  deleteCommunityPrompt,
  createTeamInvite,
  getMe,
  getModelConfig,
  getPlatformLimits,
  getPlansForReview,
  getPrompts,
  getTeamMembers,
  getTeamSettings,
  getUsers,
  reviewPlan,
  reviewPrompt,
  resetUserPassword,
  updateTeamMemberRole,
  updateTeamMemberStatus,
  updatePlatformLimits,
  updateUser,
  updateModelConfig,
} from '@/api/client'
import { assetIdForItem, assetTypeForItem } from '@/utils/communityAssets'
import { setModelDisplayName } from '@/utils/modelProfile'

const DEFAULT_PLATFORM_LIMITS = {
  max_concurrent_tasks_per_user: 2,
  max_queued_tasks_per_user: 5,
  max_task_time_budget_s: 300,
}

const DEFAULT_MODEL_CONFIG = {
  display_name: 'Codex',
  auth_json: '',
  config_toml: '',
  auth_path: '',
  config_path: '',
}

export function useAdminManagement() {
  const currentUser = ref(null)
  const users = ref([])
  const teamSettings = ref(null)
  const teamMembers = ref([])
  const prompts = ref([])
  const plans = ref([])
  const platformLimits = ref({ ...DEFAULT_PLATFORM_LIMITS })
  const modelConfig = ref({ ...DEFAULT_MODEL_CONFIG })
  const drafts = ref({})
  const resetPasswords = ref({})
  const inviteForm = ref({ email: '', note: '' })
  const inviteInfo = ref(null)
  const teamLoading = ref(false)
  const savingMemberAction = ref('')
  const savingModelConfig = ref(false)
  const savingUserAction = ref('')
  const error = ref('')
  const message = ref('')
  const loading = ref(false)
  const activeSection = ref('community')
  const reviewTypeFilter = ref('all')
  const teamRoleOptions = [
    { value: 'admin', label: '管理员' },
    { value: 'member', label: '成员' },
    { value: 'business_user', label: '业务用户' },
    { value: 'developer_user', label: '开发者' },
  ]
  const teamStatusOptions = [
    { value: 'active', label: '正常' },
    { value: 'frozen', label: '冻结' },
    { value: 'invited', label: '已邀请' },
    { value: 'removed', label: '已移除' },
  ]

  const isSystemAdmin = computed(() => currentUser.value?.role === 'admin')
  const pageTitle = computed(() => (activeSection.value === 'team' ? '团队管理' : '管理台'))
  const reviewItems = computed(() => {
    const items = [
      ...prompts.value.map((item) => ({ ...item, review_type: 'prompt' })),
      ...plans.value.map((item) => ({ ...item, review_type: 'plan' })),
    ].filter((item) => item.status === 'pending')
    if (reviewTypeFilter.value === 'all') return items
    return items.filter((item) => item.review_type === reviewTypeFilter.value)
  })
  const pendingPromptCount = computed(() => prompts.value.filter((item) => item.status === 'pending').length)
  const pendingPlanCount = computed(() => plans.value.filter((item) => item.status === 'pending').length)
  const currentTeamMember = computed(() => teamMembers.value.find((item) => item.user_id === currentUser.value?.user_id) || null)
  const activeMembership = computed(() => {
    const memberships = currentUser.value?.memberships || []
    const activeTeamId = currentUser.value?.active_team_id || teamSettings.value?.id
    return memberships.find((item) => item.id === activeTeamId || item.team_id === activeTeamId) || memberships[0] || null
  })
  const currentTeamName = computed(() => teamSettings.value?.name || currentUser.value?.active_team_name || activeMembership.value?.name || '-')
  const currentTeamInviteCode = computed(() => teamSettings.value?.invite_code || activeMembership.value?.invite_code || '-')
  const currentTeamRole = computed(() => currentTeamMember.value?.role || currentUser.value?.native_role || currentUser.value?.role || '-')
  const currentTeamJoinTime = computed(() => currentTeamMember.value?.joined_at || activeMembership.value?.joined_at || teamSettings.value?.created_at || '')

  function teamMemberName(member) {
    return member.display_name || member.email || member.user_id
  }

  function canEditMemberRole(member) {
    return member.role !== 'team_owner'
  }

  function memberActionKey(member, action) {
    return `${member.user_id}:${action}`
  }

  function isSavingMember(member, action) {
    return savingMemberAction.value === memberActionKey(member, action)
  }

  function isSavingUser(user, action) {
    return savingUserAction.value === memberActionKey(user, action)
  }

  function assetId(item) {
    return assetIdForItem(item)
  }

  function assetType(item) {
    return assetTypeForItem(item)
  }

  function draftFor(item) {
    const id = assetId(item)
    if (!drafts.value[id]) {
      drafts.value[id] = {
        review_note: item.review_note || item.note || '',
      }
    }
    return drafts.value[id]
  }

  function applyModelConfig(payload) {
    modelConfig.value = {
      display_name: payload?.display_name || 'Codex',
      auth_json: payload?.auth_json || '',
      config_toml: payload?.config_toml || '',
      auth_path: payload?.auth_path || '',
      config_path: payload?.config_path || '',
    }
    setModelDisplayName(modelConfig.value.display_name)
  }

  async function runAdminAction(action, successMessage = '') {
    error.value = ''
    try {
      await action()
      if (successMessage) message.value = successMessage
    } catch (err) {
      error.value = err.message
    }
  }

  async function runSavingAction(savingRef, actionKey, action, successMessage = '') {
    savingRef.value = actionKey
    try {
      await runAdminAction(action, successMessage)
    } finally {
      savingRef.value = ''
    }
  }

  async function load() {
    loading.value = true
    error.value = ''
    try {
      const me = await getMe()
      currentUser.value = me.user
      const requests = [getPrompts(true), getPlansForReview(true), getTeamSettings(), getTeamMembers()]
      if (me.user?.role === 'admin') {
        requests.push(getUsers())
        requests.push(getPlatformLimits())
        requests.push(getModelConfig())
      }
      const [promptData, planData, teamData, memberData, userData, limitData, modelData] = await Promise.all(requests)
      prompts.value = promptData.items || []
      plans.value = planData.items || []
      teamSettings.value = teamData
      teamMembers.value = memberData?.items || []
      users.value = userData?.items || []
      if (limitData) platformLimits.value = limitData
      if (modelData) applyModelConfig(modelData)
      drafts.value = {}
      prompts.value.forEach(draftFor)
      plans.value.forEach(draftFor)
    } catch (err) {
      error.value = err.message
    } finally {
      loading.value = false
    }
  }

  async function refreshTeam(options = {}) {
    teamLoading.value = true
    error.value = ''
    try {
      const [teamData, memberData] = await Promise.all([getTeamSettings(), getTeamMembers()])
      teamSettings.value = teamData
      teamMembers.value = memberData?.items || []
      if (!options.silent) message.value = '团队信息已刷新'
    } catch (err) {
      error.value = err.message
    } finally {
      teamLoading.value = false
    }
  }

  async function generateInviteInfo() {
    await runAdminAction(async () => {
      inviteInfo.value = await createTeamInvite({
        email: inviteForm.value.email.trim(),
        note: inviteForm.value.note.trim(),
      })
    }, '邀请信息已生成')
  }

  async function saveTeamMemberRole(member) {
    if (!canEditMemberRole(member)) return
    await runSavingAction(savingMemberAction, memberActionKey(member, 'role'), async () => {
      await updateTeamMemberRole(member.user_id, member.role)
      await refreshTeam({ silent: true })
    }, '成员角色已更新')
  }

  async function saveTeamMemberStatus(member) {
    await runSavingAction(savingMemberAction, memberActionKey(member, 'status'), async () => {
      await updateTeamMemberStatus(member.user_id, member.member_status)
      await refreshTeam({ silent: true })
    }, '成员状态已更新')
  }

  async function saveUser(user) {
    await runSavingAction(savingUserAction, memberActionKey(user, 'save'), async () => {
      await updateUser(user.user_id, {
        display_name: user.display_name,
        original_display_name: user.original_display_name,
        role: user.role,
        original_native_role: user.original_native_role,
        token_quota: Number(user.token_quota),
        original_token_quota: Number(user.original_token_quota || 0),
        token_used: Number(user.token_used || 0),
        is_active: Boolean(user.is_active),
        original_is_active: Boolean(user.original_is_active),
        original_quota_status: user.original_quota_status,
        warning_threshold: Number(user.warning_threshold || 0),
        original_warning_threshold: Number(user.original_warning_threshold || 0),
      })
      message.value = '用户权限与额度已更新'
      await load()
    })
  }

  async function resetPassword(user) {
    const password = String(resetPasswords.value[user.user_id] || '').trim()
    if (password.length < 6) {
      error.value = '新密码至少 6 位'
      return
    }
    await runSavingAction(savingUserAction, memberActionKey(user, 'password'), async () => {
      await resetUserPassword(user.user_id, password)
      resetPasswords.value[user.user_id] = ''
    }, '密码已重置')
  }

  async function savePlatformLimits() {
    await runAdminAction(async () => {
      platformLimits.value = await updatePlatformLimits({
        max_concurrent_tasks_per_user: Number(platformLimits.value.max_concurrent_tasks_per_user),
        max_queued_tasks_per_user: Number(platformLimits.value.max_queued_tasks_per_user),
        max_task_time_budget_s: Number(platformLimits.value.max_task_time_budget_s),
      })
    }, '平台任务限制已更新')
  }

  async function saveModelConfig() {
    savingModelConfig.value = true
    try {
      await runAdminAction(async () => {
        const nextConfig = await updateModelConfig(modelConfig.value)
        applyModelConfig(nextConfig)
      }, '模型配置已保存并应用')
    } finally {
      savingModelConfig.value = false
    }
  }

  async function review(type, item, status) {
    const draft = draftFor(item)
    const payload = {
      status,
      review_note: draft.review_note || (status === 'approved' ? '通过' : '驳回'),
      task_category: type,
    }
    await runAdminAction(async () => {
      if (type === 'plan') await reviewPlan(item.plan_id, payload)
      else await reviewPrompt(item.prompt_id, payload)
      message.value = '审核状态已更新'
      await load()
    })
  }

  async function removeAsset(type, item) {
    const name = item.name || assetId(item)
    if (!window.confirm(`删除社区条目“${name}”？`)) return
    await runAdminAction(async () => {
      if (type === 'plan') await deleteCommunityPlan(item.plan_id)
      else await deleteCommunityPrompt(item.prompt_id)
      message.value = '社区条目已删除'
      await load()
    })
  }

  onMounted(load)

  return {
    activeSection,
    canEditMemberRole,
    currentTeamInviteCode,
    currentTeamJoinTime,
    currentTeamName,
    currentTeamRole,
    currentUser,
    draftFor,
    error,
    generateInviteInfo,
    inviteForm,
    inviteInfo,
    isSavingMember,
    isSavingUser,
    isSystemAdmin,
    loading,
    load,
    message,
    modelConfig,
    pageTitle,
    pendingPlanCount,
    pendingPromptCount,
    platformLimits,
    refreshTeam,
    removeAsset,
    resetPassword,
    resetPasswords,
    review,
    reviewItems,
    reviewTypeFilter,
    saveModelConfig,
    savePlatformLimits,
    saveTeamMemberRole,
    saveTeamMemberStatus,
    saveUser,
    savingModelConfig,
    teamLoading,
    teamMemberName,
    teamMembers,
    teamRoleOptions,
    teamStatusOptions,
    users,
    assetId,
    assetType,
  }
}
