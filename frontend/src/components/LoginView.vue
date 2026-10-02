<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Lock, User } from '@element-plus/icons-vue'
import mensLogo from '../assets/mens.png'
import { authLogin, authRegister, healthInfo, type AuthUser } from '../api'
import { t } from '../i18n'

const emit = defineEmits<{ authenticated: [user: AuthUser] }>()

const mode = ref<'login' | 'register'>('login')
const allowRegister = ref(false)
const codeRequired = ref(false)
const username = ref('')
const password = ref('')
const confirm = ref('')
const code = ref('')
const busy = ref(false)
const error = ref('')

onMounted(async () => {
  try {
    const health = await healthInfo()
    allowRegister.value = Boolean((health as { allow_registration?: boolean }).allow_registration)
    codeRequired.value = Boolean((health as { register_code_required?: boolean }).register_code_required)
  } catch {
    allowRegister.value = false
  }
})

function switchMode(next: 'login' | 'register') {
  mode.value = next
  error.value = ''
  password.value = ''
  confirm.value = ''
}

async function submit() {
  if (busy.value || !username.value.trim() || !password.value) return
  if (mode.value === 'register' && password.value !== confirm.value) {
    error.value = t('auth.register.mismatch')
    return
  }
  if (mode.value === 'register' && codeRequired.value && !code.value.trim()) {
    error.value = t('auth.register.codeRequired')
    return
  }
  busy.value = true
  error.value = ''
  try {
    const user = mode.value === 'login'
      ? await authLogin(username.value.trim(), password.value)
      : await authRegister(username.value.trim(), password.value, code.value.trim())
    emit('authenticated', user)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
    password.value = ''
    confirm.value = ''
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login-shell">
    <form class="login-card" @submit.prevent="submit">
      <div class="login-brand">
        <img :src="mensLogo" alt="" />
        <div>
          <strong>Mens</strong>
          <span>{{ t('auth.subtitle') }}</span>
        </div>
      </div>
      <h1>{{ mode === 'login' ? t('auth.title') : t('auth.register.title') }}</h1>
      <p class="login-hint">{{ mode === 'login' ? t('auth.hint') : t('auth.register.hint') }}</p>

      <label class="login-field">
        <span>{{ t('auth.username') }}</span>
        <el-input v-model="username" :prefix-icon="User" autocomplete="username" :disabled="busy" :maxlength="64" />
      </label>
      <label class="login-field">
        <span>{{ t('auth.password') }}</span>
        <el-input v-model="password" type="password" show-password :prefix-icon="Lock"
                  :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" :disabled="busy" />
      </label>
      <template v-if="mode === 'register'">
        <label class="login-field">
          <span>{{ t('auth.register.confirm') }}</span>
          <el-input v-model="confirm" type="password" show-password :prefix-icon="Lock"
                    autocomplete="new-password" :disabled="busy" />
        </label>
        <label v-if="codeRequired" class="login-field">
          <span>{{ t('auth.register.code') }}</span>
          <el-input v-model="code" :disabled="busy" :maxlength="200" />
        </label>
        <p class="login-rule">{{ t('auth.register.rule') }}</p>
      </template>

      <el-alert v-if="error" class="alert" :title="error" type="error" show-icon :closable="false" />
      <div class="login-actions">
        <el-button type="primary" native-type="submit" :loading="busy" :disabled="!username.trim() || !password">
          {{ mode === 'login' ? t('auth.submit') : t('auth.register.submit') }}
        </el-button>
        <el-button v-if="allowRegister && mode === 'login'" text :disabled="busy" @click="switchMode('register')">
          {{ t('auth.register.switch') }}
        </el-button>
        <el-button v-else-if="mode === 'register'" text :disabled="busy" @click="switchMode('login')">
          {{ t('auth.register.back') }}
        </el-button>
      </div>
      <p class="login-foot">{{ t('auth.foot') }}</p>
    </form>
  </div>
</template>

<style scoped>
.login-shell { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center;
  background: var(--el-bg-color-page, #f5f7fa); z-index: 3000; padding: 24px; overflow: auto; }
.login-card { width: min(400px, 100%); display: flex; flex-direction: column; gap: 14px;
  padding: 28px; border-radius: 16px; border: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color); box-shadow: 0 18px 48px rgba(0, 0, 0, 0.12); }
.login-brand { display: flex; align-items: center; gap: 12px; }
.login-brand img { width: 40px; height: 40px; border-radius: 10px; }
.login-brand strong { display: block; font-size: 18px; }
.login-brand span { color: var(--el-text-color-secondary); font-size: 12px; }
.login-card h1 { margin: 4px 0 0; font-size: 22px; }
.login-hint { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; }
.login-field { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.login-rule { margin: 0; color: var(--el-text-color-placeholder); font-size: 12px; }
.login-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.login-foot { margin: 0; color: var(--el-text-color-placeholder); font-size: 12px; }
</style>
