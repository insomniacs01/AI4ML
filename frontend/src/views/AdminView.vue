<script setup>
import { Check, ClipboardList, FileText, RefreshCw, Settings2, Trash2, UserRound, Users, X } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useAdminManagement } from '@/composables/useAdminManagement'
import { assetIntro, assetTypeLabel } from '@/utils/communityAssets'
import { formatDateTimeWithSeconds as formatDateTime, quotaRemaining } from '@/utils/formatters'
import { teamRoleLabel, teamStatusLabel } from '@/utils/labels'

const {
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
} = useAdminManagement()
</script>

<template>
  <PageHeader :title="pageTitle">
    <template #actions>
      <button class="secondary-action refresh-action" type="button" :disabled="loading" @click="load">
        <RefreshCw :class="{ spinning: loading }" :size="18" />刷新
      </button>
    </template>
  </PageHeader>

  <p v-if="error" class="form-error">{{ error }}</p>
  <p v-if="message" class="form-success">{{ message }}</p>

  <LoadingBlock v-if="loading" />

  <template v-else>
    <section class="admin-tabs">
      <button :class="{ active: activeSection === 'team' }" type="button" @click="activeSection = 'team'"><Users :size="17" />团队管理</button>
      <button :class="{ active: activeSection === 'community' }" type="button" @click="activeSection = 'community'"><ClipboardList :size="17" />社区审核</button>
      <button v-if="isSystemAdmin" :class="{ active: activeSection === 'model' }" type="button" @click="activeSection = 'model'"><Settings2 :size="17" />模型配置</button>
      <button v-if="isSystemAdmin" :class="{ active: activeSection === 'users' }" type="button" @click="activeSection = 'users'"><UserRound :size="17" />用户与额度</button>
    </section>

    <section v-if="activeSection === 'team'" class="team-admin-stack">
      <div class="panel team-overview-panel">
        <div class="team-section-head">
          <div>
            <div class="panel-title"><span>当前团队</span></div>
            <p>这里显示当前小组、你的身份和邀请码，方便课堂展示和成员加入。</p>
          </div>
          <button class="secondary-action" type="button" :disabled="teamLoading" @click="refreshTeam">
            <RefreshCw :class="{ spinning: teamLoading }" :size="17" />刷新团队
          </button>
        </div>
        <div class="team-summary-grid">
          <div class="team-summary-card">
            <span>团队名称</span>
            <strong>{{ currentTeamName }}</strong>
          </div>
          <div class="team-summary-card">
            <span>我的角色</span>
            <strong>{{ teamRoleLabel(currentTeamRole) }}</strong>
          </div>
          <div class="team-summary-card">
            <span>邀请码</span>
            <strong>{{ currentTeamInviteCode }}</strong>
          </div>
          <div class="team-summary-card">
            <span>成员数量</span>
            <strong>{{ teamMembers.length }}</strong>
          </div>
          <div class="team-summary-card">
            <span>加入时间</span>
            <strong>{{ formatDateTime(currentTeamJoinTime) }}</strong>
          </div>
        </div>
      </div>

      <div class="panel team-invite-panel">
        <div class="panel-title"><span>邀请成员</span></div>
        <p>当前版本沿用邀请码入队。这里会返回团队邀请码和可直接转发的分享文案。</p>
        <div class="team-invite-form">
          <label class="field">
            <span>成员邮箱（可选）</span>
            <input v-model="inviteForm.email" type="email" placeholder="仅用于生成更明确的分享文案" />
          </label>
          <label class="field">
            <span>备注（可选）</span>
            <input v-model="inviteForm.note" placeholder="例如：给模型评审同学加入团队" />
          </label>
          <button class="primary-action" type="button" @click="generateInviteInfo">生成邀请信息</button>
        </div>
        <div v-if="inviteInfo" class="team-invite-result">
          <strong>{{ inviteInfo.detail }}</strong>
          <p>{{ inviteInfo.share_text }}</p>
          <span>邀请码：{{ inviteInfo.invite_code }}</span>
        </div>
      </div>

      <div class="panel team-members-panel">
        <div class="panel-title"><span>团队成员</span></div>
        <p>查看小组成员和分工。展示时重点看谁负责创建任务、谁负责复核。</p>
        <EmptyState v-if="!teamMembers.length" title="暂无团队成员" description="刷新团队后仍为空时，请检查当前账号是否已加入团队。" />
        <div v-else class="team-member-table-wrap">
          <table class="team-member-table">
            <thead>
              <tr>
                <th>名称</th>
                <th>邮箱</th>
                <th>角色</th>
                <th>状态</th>
                <th>加入时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="member in teamMembers" :key="member.user_id">
                <td>
                  <strong>{{ teamMemberName(member) }}</strong>
                  <small v-if="member.user_id === currentUser?.user_id">当前账号</small>
                </td>
                <td>{{ member.email || '-' }}</td>
                <td>{{ teamRoleLabel(member.role) }}</td>
                <td>
                  <span class="team-status-pill" :class="member.member_status">{{ teamStatusLabel(member.member_status) }}</span>
                </td>
                <td>{{ formatDateTime(member.joined_at) }}</td>
                <td>
                  <div class="team-member-actions">
                    <select v-model="member.role" :disabled="!canEditMemberRole(member)">
                      <option v-if="member.role === 'team_owner'" value="team_owner">所有者</option>
                      <option v-for="option in teamRoleOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                    </select>
                    <button
                      class="secondary-action"
                      type="button"
                      :disabled="teamLoading || !canEditMemberRole(member) || isSavingMember(member, 'role')"
                      @click="saveTeamMemberRole(member)"
                    >
                      {{ isSavingMember(member, 'role') ? '保存中' : '保存角色' }}
                    </button>
                    <select v-model="member.member_status">
                      <option v-for="option in teamStatusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                    </select>
                    <button
                      class="secondary-action"
                      type="button"
                      :disabled="teamLoading || isSavingMember(member, 'status')"
                      @click="saveTeamMemberStatus(member)"
                    >
                      {{ isSavingMember(member, 'status') ? '保存中' : '保存状态' }}
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <section v-else-if="activeSection === 'users' && isSystemAdmin" class="panel">
      <div class="panel-title"><span>用户权限与调用额度</span></div>
      <div class="admin-user-table">
        <div class="admin-user-head">
          <span>用户</span>
          <span>角色</span>
          <span>Token 额度</span>
          <span>使用情况</span>
          <span>预警阈值</span>
          <span>状态</span>
          <span>操作</span>
        </div>
        <div v-for="user in users" :key="user.user_id" class="admin-user-row">
          <div class="admin-user-identity">
            <input v-model="user.display_name" />
            <small>{{ user.email || user.user_id }}</small>
          </div>
          <select v-model="user.role">
            <option v-if="user.original_native_role === 'team_owner'" value="admin">所有者</option>
            <option value="business">业务用户</option>
            <option value="developer">开发者</option>
            <option value="community_admin">社区管理员</option>
            <option value="admin">系统管理员</option>
          </select>
          <input v-model.number="user.token_quota" type="number" min="0" />
          <span class="quota-chip">已用 {{ user.token_used || 0 }} / 余 {{ quotaRemaining(user) }}</span>
          <input v-model.number="user.warning_threshold" type="number" min="0" />
          <label class="admin-user-toggle"><input v-model="user.is_active" type="checkbox" />启用</label>
          <div class="admin-user-actions">
            <button class="secondary-action" type="button" :disabled="isSavingUser(user, 'save')" @click="saveUser(user)">
              {{ isSavingUser(user, 'save') ? '保存中' : '保存' }}
            </button>
            <input v-model="resetPasswords[user.user_id]" type="password" placeholder="新密码" />
            <button class="secondary-action" type="button" :disabled="isSavingUser(user, 'password')" @click="resetPassword(user)">
              {{ isSavingUser(user, 'password') ? '重置中' : '重置密码' }}
            </button>
          </div>
        </div>
      </div>
      <div class="divider-line"></div>
      <div class="panel-title"><span>任务资源限制</span></div>
      <div class="resource-limit-grid">
        <label class="field"><span>同时运行任务数</span><input v-model.number="platformLimits.max_concurrent_tasks_per_user" type="number" min="0" /></label>
        <label class="field"><span>待启动任务数</span><input v-model.number="platformLimits.max_queued_tasks_per_user" type="number" min="0" /></label>
        <label class="field"><span>最大训练预算（秒）</span><input v-model.number="platformLimits.max_task_time_budget_s" type="number" min="0" /></label>
        <button class="secondary-action" type="button" @click="savePlatformLimits">保存限制</button>
      </div>
    </section>

    <section v-else-if="activeSection === 'model' && isSystemAdmin" class="panel model-config-panel">
      <div class="panel-title"><span>模型配置</span></div>
      <p class="muted">这里直接管理本机模型运行配置。保存后会写入配置文件，并让空闲运行会话重新加载。</p>
      <div class="model-config-grid">
        <label class="field model-name-field">
          <span>前端显示名称</span>
          <input v-model="modelConfig.display_name" maxlength="48" placeholder="例如：deepseek、课程助教模型" />
        </label>
        <label class="field config-file-field">
          <span>auth.json 路径</span>
          <input :value="modelConfig.auth_path" readonly />
        </label>
        <label class="field config-file-field">
          <span>config.toml 路径</span>
          <input :value="modelConfig.config_path" readonly />
        </label>
      </div>
      <div class="model-config-editors">
        <label class="field">
          <span>auth.json</span>
          <textarea v-model="modelConfig.auth_json" class="config-textarea" rows="12" spellcheck="false"></textarea>
        </label>
        <label class="field">
          <span>config.toml</span>
          <textarea v-model="modelConfig.config_toml" class="config-textarea" rows="16" spellcheck="false"></textarea>
        </label>
      </div>
      <div class="form-actions">
        <button class="primary-action" type="button" :disabled="savingModelConfig" @click="saveModelConfig">
          <Settings2 :size="17" />{{ savingModelConfig ? '保存中' : '保存并应用' }}
        </button>
      </div>
    </section>

    <section v-else-if="activeSection === 'users'" class="panel">
      <div class="panel-title"><span>社区管理员权限</span></div>
      <p class="muted">你可以审核和删除社区提示词与执行方案。用户权限与额度只允许系统管理员管理。</p>
    </section>

    <section v-else class="admin-community-grid">
      <div class="panel">
        <div class="panel-title admin-review-title">
          <span>社区资源审核</span>
          <label class="admin-review-filter">
            <span>资源类型</span>
            <select v-model="reviewTypeFilter">
              <option value="all">全部（{{ pendingPromptCount + pendingPlanCount }}）</option>
              <option value="prompt">提示词（{{ pendingPromptCount }}）</option>
              <option value="plan">执行方案（{{ pendingPlanCount }}）</option>
            </select>
          </label>
        </div>
        <EmptyState v-if="!reviewItems.length && !loading" title="暂无待审核资源" description="用户提交提示词或执行方案后，会先进入这里等待管理员审核。" />
        <div v-else class="review-list">
          <article v-for="item in reviewItems" :key="assetId(item)" class="review-card asset-review-card">
            <div class="review-main">
              <strong>
                <FileText v-if="assetType(item) === 'prompt'" :size="17" />
                <ClipboardList v-else :size="17" />
                {{ item.name }}
              </strong>
              <StatusBadge :status="item.status" />
              <p>{{ assetIntro(item) }}</p>
            </div>
            <div class="asset-type-line">{{ assetTypeLabel(assetType(item)) }}</div>
            <label class="field">
              <span>审核备注</span>
              <input v-model="draftFor(item).review_note" />
            </label>
            <div class="form-actions">
              <button class="secondary-action" type="button" @click="review(assetType(item), item, 'approved')"><Check :size="17" />通过并上架</button>
              <button class="danger-action" type="button" @click="review(assetType(item), item, 'rejected')"><X :size="17" />驳回</button>
              <button class="danger-action" type="button" @click="removeAsset(assetType(item), item)"><Trash2 :size="17" />删除</button>
            </div>
          </article>
        </div>
      </div>
    </section>
  </template>
</template>
