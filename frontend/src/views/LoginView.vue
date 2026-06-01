<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { login, register } from '@/api/client'

const route = useRoute()
const router = useRouter()

const authMode = ref('login')
const loading = ref(false)
const error = ref('')
const loginForm = ref({ email: '', password: '' })
const registerForm = ref({ email: '', display_name: '', password: '' })

const isRegisterMode = computed(() => authMode.value === 'register')
const submitText = computed(() => {
  if (loading.value) return isRegisterMode.value ? '注册中' : '登录中'
  return isRegisterMode.value ? '注册并登录' : '登录'
})

function switchAuthMode(mode) {
  authMode.value = mode
  error.value = ''
}

async function submitLogin() {
  loading.value = true
  error.value = ''
  try {
    await login({
      email: loginForm.value.email,
      password: loginForm.value.password,
    })
    router.push(route.query.next || '/workspace')
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function submitRegister() {
  loading.value = true
  error.value = ''
  try {
    await register({
      email: registerForm.value.email,
      user_id: registerForm.value.email,
      display_name: registerForm.value.display_name,
      password: registerForm.value.password,
    })
    await login({
      email: registerForm.value.email,
      password: registerForm.value.password,
    })
    router.push(route.query.next || '/workspace')
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function submitAuthForm() {
  if (isRegisterMode.value) return submitRegister()
  return submitLogin()
}
</script>

<template>
  <main class="auth-simple-page">
    <section class="auth-simple-card" aria-labelledby="auth-simple-title">
      <div class="auth-simple-copy">
        <p class="auth-simple-kicker">Supabase 认证</p>
        <h1 id="auth-simple-title">进入 AI4ML 之前先登录</h1>
        <p>
          前端会用 Supabase 处理登录和团队身份，后端再根据当前团队隔离任务和 AI 设置。
          登录后，你就能直接在页面里录入 AI 服务、上传 CSV，并让 AI 理解任务。
        </p>

        <div class="auth-simple-tabs" role="tablist" aria-label="认证方式">
          <button
            type="button"
            :class="{ active: authMode === 'login' }"
            role="tab"
            :aria-selected="authMode === 'login'"
            @click="switchAuthMode('login')"
          >
            登录
          </button>
          <button
            type="button"
            :class="{ active: authMode === 'register' }"
            role="tab"
            :aria-selected="authMode === 'register'"
            @click="switchAuthMode('register')"
          >
            注册
          </button>
        </div>

        <p class="auth-simple-note">当前 Supabase 项目支持注册后直接登录。</p>
      </div>

      <form class="auth-simple-form" @submit.prevent="submitAuthForm">
        <label class="auth-simple-field">
          <span>邮箱</span>
          <input
            v-if="isRegisterMode"
            v-model.trim="registerForm.email"
            type="email"
            autocomplete="email"
            placeholder="请输入邮箱地址"
            required
          />
          <input
            v-else
            v-model.trim="loginForm.email"
            type="email"
            autocomplete="email"
            placeholder="请输入邮箱地址"
            required
          />
        </label>

        <label v-if="isRegisterMode" class="auth-simple-field">
          <span>显示名（可选）</span>
          <input v-model.trim="registerForm.display_name" autocomplete="name" placeholder="用于团队成员列表展示" />
        </label>

        <label class="auth-simple-field">
          <span>密码</span>
          <input
            v-if="isRegisterMode"
            v-model="registerForm.password"
            type="password"
            autocomplete="new-password"
            placeholder="至少 6 位字符"
            minlength="6"
            required
          />
          <input
            v-else
            v-model="loginForm.password"
            type="password"
            autocomplete="current-password"
            placeholder="至少 6 位字符"
            required
          />
        </label>

        <p v-if="error" class="form-error">{{ error }}</p>

        <button
          class="primary-action auth-simple-submit"
          type="submit"
          :disabled="
            loading ||
            (isRegisterMode
              ? !registerForm.email || !registerForm.password
              : !loginForm.email || !loginForm.password)
          "
        >
          {{ submitText }}
        </button>
      </form>
    </section>
  </main>
</template>
