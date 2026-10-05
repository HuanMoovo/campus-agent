<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Delete, Key, Plus, Refresh, SwitchButton, User as UserIcon } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { t } from '../i18n'
import {
  authMe, changePassword, createUser, deleteUser, listUsers, resetUserPassword, revokeUserSessions,
  updateUser, type AuthUser, type ManagedUser,
} from '../api'

const me = ref<AuthUser | null>(null)
const users = ref<ManagedUser[]>([])
const busy = ref(false)
const error = ref('')

const draft = ref({ username: '', password: '', role: 'user' as 'user' | 'admin' })
const creating = ref(false)
const passwordForm = ref({ current: '', next: '', confirm: '' })
const changing = ref(false)

const isAdmin = computed(() => me.value?.role === 'admin')

async function load() {
  busy.value = true
  error.value = ''
  try {
    me.value = await authMe()
    users.value = isAdmin.value ? await listUsers() : []
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    busy.value = false
  }
}

async function changeOwnPassword() {
  if (passwordForm.value.next !== passwordForm.value.confirm) {
    error.value = t('account.password.mismatch')
    return
  }
  changing.value = true
  error.value = ''
  try {
    await changePassword(passwordForm.value.current, passwordForm.value.next)
    passwordForm.value = { current: '', next: '', confirm: '' }
    ElMessage.success(t('account.password.done'))
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    changing.value = false
  }
}

async function create() {
  creating.value = true
  error.value = ''
  try {
    await createUser(draft.value.username.trim(), draft.value.password, draft.value.role)
    draft.value = { username: '', password: '', role: 'user' }
    ElMessage.success(t('account.users.created'))
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    creating.value = false
  }
}

async function toggleRole(row: ManagedUser) {
  try {
    await updateUser(row.id, { role: row.role === 'admin' ? 'user' : 'admin' })
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  }
}

async function toggleDisabled(row: ManagedUser) {
  try {
    await updateUser(row.id, { disabled: !row.disabled })
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  }
}

async function resetPassword(row: ManagedUser) {
  let value = ''
  try {
    const result = await ElMessageBox.prompt(t('account.users.resetPrompt', { name: row.username }),
                                             t('account.users.resetTitle'), { inputType: 'password', inputValue: '' })
    value = result.value || ''
  } catch {
    return
  }
  if (value.length < 8) {
    error.value = t('account.users.resetTooShort')
    return
  }
  try {
    await resetUserPassword(row.id, value)
    ElMessage.success(t('account.users.resetDone', { name: row.username }))
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  }
}

async function revoke(row: ManagedUser) {
  try {
    const result = await revokeUserSessions(row.id)
    ElMessage.success(t('account.users.revoked', { count: String(result.revoked ?? 0) }))
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  }
}

async function remove(row: ManagedUser) {
  try {
    await ElMessageBox.confirm(t('account.users.deleteConfirm', { name: row.username }),
                               t('account.users.deleteTitle'), { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteUser(row.id)
    ElMessage.success(t('account.users.deleted', { name: row.username }))
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  }
}

function formatTime(value: string | null) {
  return value ? value.slice(0, 16).replace('T', ' ') : t('account.never')
}

onMounted(load)
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">MENS ACCOUNT</div>
      <h1>{{ t('account.title') }}</h1>
      <p>{{ t('account.subtitle') }}</p>
    </div>
    <el-button text :icon="Refresh" :loading="busy" @click="load">{{ t('account.refresh') }}</el-button>
  </div>

  <el-alert v-if="error" class="alert" :title="error" type="error" show-icon :closable="false" />

  <div class="settings-section">
    <div class="settings-copy">
      <h2>{{ t('account.profile.title') }}</h2>
      <p v-if="me">
        {{ t('account.profile.signedIn', { name: me.username }) }} ·
        {{ me.role === 'admin' ? t('account.role.admin') : t('account.role.user') }} ·
        {{ t('account.profile.since', { time: formatTime(me.created_at) }) }}
      </p>
      <p v-else-if="busy">{{ t('account.profile.loading') }}</p>
      <p v-else>{{ t('account.profile.noSession') }}</p>
    </div>
    <div v-if="me" class="settings-form">
      <label class="field"><span>{{ t('account.password.current') }}</span>
        <el-input v-model="passwordForm.current" type="password" show-password autocomplete="current-password" />
      </label>
      <label class="field"><span>{{ t('account.password.next') }}</span>
        <el-input v-model="passwordForm.next" type="password" show-password autocomplete="new-password" />
      </label>
      <label class="field"><span>{{ t('account.password.confirm') }}</span>
        <el-input v-model="passwordForm.confirm" type="password" show-password autocomplete="new-password" />
      </label>
      <el-button type="primary" :icon="Key" :loading="changing"
                 :disabled="!passwordForm.current || !passwordForm.next" @click="changeOwnPassword">
        {{ t('account.password.submit') }}
      </el-button>
    </div>
  </div>

  <template v-if="isAdmin">
    <div class="section-toolbar">
      <div><strong>{{ t('account.users.title') }}</strong><span>{{ users.length }}</span></div>
    </div>

    <div class="install-band">
      <div>
        <h2>{{ t('account.users.createTitle') }}</h2>
        <p>{{ t('account.users.createHint') }}</p>
      </div>
      <div class="mcp-form">
        <el-input v-model="draft.username" :placeholder="t('account.users.name')" maxlength="64" />
        <el-input v-model="draft.password" type="password" show-password :placeholder="t('account.users.password')" />
        <el-select v-model="draft.role">
          <el-option value="user" :label="t('account.role.user')" />
          <el-option value="admin" :label="t('account.role.admin')" />
        </el-select>
        <div class="mcp-form-actions">
          <span />
          <el-button type="primary" :icon="Plus" :loading="creating"
                     :disabled="draft.username.trim().length < 3 || draft.password.length < 8" @click="create">
            {{ t('account.users.create') }}
          </el-button>
        </div>
      </div>
    </div>

    <div class="table-scroll" v-loading="busy">
      <el-table :data="users" stripe border>
        <el-table-column :label="t('account.users.name')" min-width="150">
          <template #default="scope">
            <el-icon><UserIcon /></el-icon> {{ scope.row.username }}
          </template>
        </el-table-column>
        <el-table-column :label="t('account.users.role')" width="110">
          <template #default="scope">
            <el-tag :type="scope.row.role === 'admin' ? 'success' : 'info'" size="small">
              {{ scope.row.role === 'admin' ? t('account.role.admin') : t('account.role.user') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('account.users.state')" width="110">
          <template #default="scope">
            <el-tag :type="scope.row.disabled ? 'danger' : 'success'" size="small">
              {{ scope.row.disabled ? t('account.users.disabled') : t('account.users.active') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('account.users.created')" width="150">
          <template #default="scope">{{ formatTime(scope.row.created_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('account.users.lastLogin')" width="150">
          <template #default="scope">{{ formatTime(scope.row.last_login_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('account.users.actions')" min-width="330">
          <template #default="scope">
            <el-button link type="primary" @click="toggleRole(scope.row)">
              {{ scope.row.role === 'admin' ? t('account.users.demote') : t('account.users.promote') }}
            </el-button>
            <el-button link type="primary" @click="toggleDisabled(scope.row)">
              {{ scope.row.disabled ? t('account.users.enable') : t('account.users.disable') }}
            </el-button>
            <el-button link type="primary" @click="resetPassword(scope.row)">{{ t('account.users.reset') }}</el-button>
            <el-button link type="warning" :icon="SwitchButton" @click="revoke(scope.row)">{{ t('account.users.revoke') }}</el-button>
            <el-button link type="danger" :icon="Delete" @click="remove(scope.row)">{{ t('account.users.delete') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <p class="management-note">{{ t('account.users.note') }}</p>
  </template>
</template>

<style scoped>
.settings-form { display: flex; flex-direction: column; gap: 10px; min-width: 280px; }
</style>
