<script setup>
import { computed, onMounted, ref } from 'vue'
import { UserRound } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import MetricCard from '@/components/MetricCard.vue'
import { changePassword, getProfile, getProfileBase, updateProfile } from '@/api/auth'

const profile = ref(null)
const displayName = ref('')
const passwordForm = ref({ old_password: '', new_password: '' })
const error = ref('')
const message = ref('')
const savingProfile = ref(false)
const changingPassword = ref(false)
const quotaLoading = ref(false)

const tokenQuota = computed(() => Number(profile.value?.token_quota || 0))
const tokenUsed = computed(() => Number(profile.value?.token_used || 0))
const quotaRemaining = computed(() => Math.max(0, tokenQuota.value - tokenUsed.value))
const quotaLoaded = computed(() => profile.value?.quota_loaded === true)
const quotaStatusText = computed(() => (quotaLoading.value ? '同步中' : '未同步'))
const tokenQuotaDisplay = computed(() => (quotaLoaded.value ? tokenQuota.value : quotaStatusText.value))
const tokenUsedDisplay = computed(() => (quotaLoaded.value ? tokenUsed.value : quotaStatusText.value))
const quotaRemainingDisplay = computed(() => (quotaLoaded.value ? quotaRemaining.value : quotaStatusText.value))

function roleLabel(role) {
  const map = { admin: '管理员', community_admin: '社区管理员', developer: '开发者', business: '业务用户' }
  return map[role] || '-'
}

async function load() {
  error.value = ''
  try {
    applyProfile(await getProfileBase())
  } catch (err) {
    error.value = err.message
    return
  }
  loadQuota()
}

async function loadQuota() {
  quotaLoading.value = true
  try {
    applyProfile(await getProfile())
  } catch (err) {
    error.value = err.message
  } finally {
    quotaLoading.value = false
  }
}

function applyProfile(profileData) {
  profile.value = { ...(profile.value || {}), ...profileData }
  displayName.value = profileData.display_name || ''
}

async function saveProfile() {
  error.value = ''
  message.value = ''
  savingProfile.value = true
  try {
    applyProfile(await updateProfile({ display_name: displayName.value }))
    message.value = '个人信息已更新'
  } catch (err) {
    error.value = err.message
  } finally {
    savingProfile.value = false
  }
}

async function updatePassword() {
  error.value = ''
  message.value = ''
  if (!passwordForm.value.old_password || passwordForm.value.new_password.length < 6) {
    error.value = '请输入原密码，新密码至少 6 位'
    return
  }
  changingPassword.value = true
  try {
    await changePassword(passwordForm.value)
    passwordForm.value = { old_password: '', new_password: '' }
    message.value = '密码已更新'
  } catch (err) {
    error.value = err.message
  } finally {
    changingPassword.value = false
  }
}

onMounted(load)
</script>

<template>
  <PageHeader title="个人空间" description="管理当前账号和调用额度。" />
  <p v-if="error" class="form-error">{{ error }}</p>
  <p v-if="message" class="form-success">{{ message }}</p>

  <section class="metric-grid">
    <MetricCard label="角色" :value="roleLabel(profile?.role)" />
    <MetricCard label="总额度" :value="tokenQuotaDisplay" />
    <MetricCard label="已用额度" :value="tokenUsedDisplay" />
    <MetricCard label="剩余额度" :value="quotaRemainingDisplay" />
  </section>

  <section class="panel quota-panel">
    <div class="panel-title"><span>调用额度</span></div>
    <div class="quota-overview">
      <div>
        <span>总额度</span>
        <strong>{{ tokenQuotaDisplay }}</strong>
      </div>
      <div>
        <span>已用额度</span>
        <strong>{{ tokenUsedDisplay }}</strong>
      </div>
      <div>
        <span>剩余额度</span>
        <strong>{{ quotaRemainingDisplay }}</strong>
      </div>
    </div>
  </section>

  <section class="split-grid profile-layout account-settings-layout">
    <div class="panel form-stack">
      <div class="panel-title"><span><UserRound :size="18" />账号信息</span></div>
      <label class="field"><span>用户 ID</span><input :value="profile?.user_id" disabled /></label>
      <label class="field"><span>显示名称</span><input v-model="displayName" /></label>
      <label class="field"><span>身份</span><input :value="roleLabel(profile?.role)" disabled /></label>
      <button class="primary-action" type="button" :disabled="savingProfile" @click="saveProfile">
        {{ savingProfile ? '保存中' : '保存信息' }}
      </button>
    </div>

    <div class="panel form-stack">
      <div class="panel-title"><span>账号密码</span></div>
      <label class="field"><span>原密码</span><input v-model="passwordForm.old_password" type="password" /></label>
      <label class="field"><span>新密码</span><input v-model="passwordForm.new_password" type="password" /></label>
      <button class="secondary-action" type="button" :disabled="changingPassword" @click="updatePassword">
        {{ changingPassword ? '修改中' : '修改密码' }}
      </button>
    </div>
  </section>
</template>
