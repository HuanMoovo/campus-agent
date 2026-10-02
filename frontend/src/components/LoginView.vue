<script setup lang="ts">
import { ref } from 'vue'
import { Lock, User } from '@element-plus/icons-vue'
import mensLogo from '../assets/mens.png'
import { authLogin, authLogout, type AuthUser } from '../api'
import { t } from '../i18n'

const emit = defineEmits<{ authenticated: [user: AuthUser]; cancelled: [] }>()

const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')

async function submit() {
  if (busy.value || !username.value.trim() || !password.value) return
  busy.value = true
  error.value = ''
  try {
    const user = await authLogin(username.value.trim(), password.value)
    emit('authenticated', user)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
    password.value = ''
  } finally {
    busy.value = false
  }
}

async function leave() {
  await authLogout().catch(() => undefined)
  emit('cancelled')
}
</script>

<template>
  <div class="login-shell" :class="{ 'desktop-app': false }">
    <form class="login-card" @submit.prevent="submit">
      <div class="login-brand">
        <img :src="mensLogo" alt="" />
        <div>
          <strong>Mens</strong>
          <span>{{ t('auth.subtitle') }}</span>
        </div>
      </div>
      <h1>{{ t('auth.title') }}</h1>
      <p class="login-hint">{{ t('auth.hint') }}</p>
      <label class="login-field">
        <span>{{ t('auth.username') }}</span>
        <el-input v-model="username" :prefix-icon="User" autocomplete="username" :disabled="busy" />
      </label>
      <label class="login-field">
        <span>{{ t('auth.password') }}</span>
        <el-input v-model="password" type="password" show-password :prefix-icon="Lock"
                  autocomplete="current-password" :disabled="busy" @keyup.enter="submit" />
      </label>
      <el-alert v-if="error" class="alert" :title="error" type="error" show-icon :closable="false" />
      <div class="login-actions">
        <el-button type="primary" native-type="submit" :loading="busy" :disabled="!username.trim() || !password">
          {{ t('auth.submit') }}
        </el-button>
        <el-button text :disabled="busy" @click="leave">{{ t('auth.back') }}</el-button>
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
.login-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.login-foot { margin: 0; color: var(--el-text-color-placeholder); font-size: 12px; }
</style>
