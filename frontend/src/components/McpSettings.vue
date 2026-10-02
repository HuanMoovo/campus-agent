<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Connection, Delete, Refresh, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { t } from '../i18n'
import {
  createMcpServer, deleteMcpServer, listMcpServers, listMcpTools, testMcpServer, updateMcpServer,
  type McpServer, type McpServerInput,
} from '../api'

defineProps<{ desktop: boolean }>()

const servers = ref<McpServer[]>([])
const sharedTools = ref<{ server: string; tool: string; function: string; description: string }[]>([])
const busy = ref(false)
const error = ref('')
const expanded = ref<Record<string, boolean>>({})

const draft = ref({ name: '', command: '', argsText: '', envText: '', enabled: true })
const adding = ref(false)


async function load() {
  busy.value = true
  error.value = ''
  try {
    servers.value = await listMcpServers()
    sharedTools.value = await listMcpTools()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    busy.value = false
  }
}

function parseEnv(text: string): Record<string, string> {
  const result: Record<string, string> = {}
  for (const line of text.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed) continue
    const index = trimmed.indexOf('=')
    if (index <= 0) throw new Error(t('mcp.error.envFormat', { line: trimmed }))
    result[trimmed.slice(0, index).trim()] = trimmed.slice(index + 1)
  }
  return result
}

async function add() {
  adding.value = true
  error.value = ''
  try {
    const payload: McpServerInput = {
      name: draft.value.name.trim(),
      command: draft.value.command.trim(),
      args: draft.value.argsText.split(/\s+/).filter(Boolean),
      env: parseEnv(draft.value.envText),
      enabled: draft.value.enabled,
    }
    await createMcpServer(payload)
    draft.value = { name: '', command: '', argsText: '', envText: '', enabled: true }
    ElMessage.success(t('mcp.added'))
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    adding.value = false
  }
}

async function test(server: McpServer) {
  busy.value = true
  error.value = ''
  try {
    const result = await testMcpServer(server.id)
    if (result.ok) {
      ElMessage.success(t('mcp.testOk', { server: result.server || server.name, count: String(result.tool_count ?? 0) }))
      expanded.value[server.id] = true
    } else {
      error.value = result.error || t('mcp.testFailed')
    }
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    busy.value = false
  }
}

async function toggle(server: McpServer) {
  busy.value = true
  try {
    await updateMcpServer(server.id, { enabled: !server.enabled })
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    busy.value = false
  }
}

async function remove(server: McpServer) {
  try {
    await ElMessageBox.confirm(t('mcp.removeConfirm', { name: server.name }), t('mcp.removeTitle'), { type: 'warning' })
  } catch {
    return
  }
  busy.value = true
  try {
    await deleteMcpServer(server.id)
    ElMessage.success(t('mcp.removed'))
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    busy.value = false
  }
}


onMounted(load)
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">MENS EXTENSIONS</div>
      <h1>{{ t('mcp.title') }}</h1>
      <p>{{ t('mcp.subtitle') }}</p>
    </div>
    <el-button text :icon="Refresh" :loading="busy" @click="load">{{ t('mcp.refresh') }}</el-button>
  </div>

  <el-alert v-if="error" class="alert" :title="error" type="error" show-icon :closable="false" />
  <p v-if="!desktop" class="management-note">{{ t('mcp.adminNote') }}</p>

  <div class="section-toolbar">
    <div><strong>{{ t('mcp.installed') }}</strong><span>{{ servers.length }}</span></div>
  </div>

  <div class="mcp-list" v-loading="busy">
    <el-empty v-if="!busy && servers.length === 0" :description="t('mcp.empty')" :image-size="96" />
    <div v-for="server in servers" :key="server.id" class="mcp-row">
      <div class="mcp-head">
        <el-icon class="mcp-icon" :size="20"><Connection /></el-icon>
        <div class="mcp-meta">
          <div class="mcp-name">
            {{ server.name }}
            <el-tag size="small" :type="server.enabled ? 'success' : 'info'">
              {{ server.enabled ? t('mcp.enabled') : t('mcp.disabled') }}
            </el-tag>
          </div>
          <code class="mcp-command">{{ server.command }} {{ server.args.join(' ') }}</code>
          <div class="mcp-stats">
            <span>{{ t('mcp.toolCount', { count: String(server.tool_count) }) }}</span>
            <span v-if="server.env_keys.length">{{ t('mcp.envCount', { count: String(server.env_keys.length) }) }}</span>
            <span v-if="server.last_checked_at">{{ t('mcp.checkedAt', { time: server.last_checked_at }) }}</span>
            <span v-else>{{ t('mcp.neverChecked') }}</span>
          </div>
          <div v-if="server.last_error" class="mcp-error">{{ server.last_error }}</div>
        </div>
        <div class="mcp-actions">
          <el-button size="small" :icon="VideoPlay" :disabled="busy" @click="test(server)">{{ t('mcp.test') }}</el-button>
          <el-button size="small" :disabled="busy" @click="toggle(server)">
            {{ server.enabled ? t('mcp.disable') : t('mcp.enable') }}
          </el-button>
          <el-button size="small" type="danger" plain :icon="Delete" :disabled="busy" @click="remove(server)">
            {{ t('mcp.remove') }}
          </el-button>
        </div>
      </div>
      <div v-if="server.tools.length" class="mcp-tools">
        <button class="mcp-tools-toggle" @click="expanded[server.id] = !expanded[server.id]">
          {{ expanded[server.id] ? t('mcp.hideTools') : t('mcp.showTools') }}
        </button>
        <ul v-if="expanded[server.id]">
          <li v-for="tool in server.tools" :key="tool.name">
            <code>{{ server.name }} / {{ tool.name }}</code>
            <span>{{ tool.description }}</span>
          </li>
        </ul>
      </div>
    </div>
  </div>

  <div class="install-band">
    <div>
      <h2>{{ t('mcp.addTitle') }}</h2>
      <p>{{ t('mcp.addHint') }}</p>
    </div>
    <div class="mcp-form">
      <el-input v-model="draft.name" :placeholder="t('mcp.form.name')" maxlength="40" />
      <el-input v-model="draft.command" :placeholder="t('mcp.form.command')" />
      <el-input v-model="draft.argsText" :placeholder="t('mcp.form.args')" />
      <el-input v-model="draft.envText" type="textarea" :rows="2" :placeholder="t('mcp.form.env')" />
      <div class="mcp-form-actions">
        <el-checkbox v-model="draft.enabled">{{ t('mcp.form.enabled') }}</el-checkbox>
        <el-button type="primary" :loading="adding" :disabled="!draft.name.trim() || !draft.command.trim()" @click="add">
          {{ t('mcp.form.submit') }}
        </el-button>
      </div>
    </div>
  </div>

  <div class="section-toolbar">
    <div><strong>{{ t('mcp.exposedTitle') }}</strong><span>{{ sharedTools.length }}</span></div>
  </div>
  <p class="management-note">{{ t('mcp.exposedHint') }}</p>
  <ul class="exposed-list">
    <li v-for="tool in sharedTools" :key="tool.function">
      <code>{{ tool.function }}</code>
      <span>{{ tool.description }}</span>
    </li>
  </ul>
  <el-empty v-if="sharedTools.length === 0" :description="t('mcp.exposedEmpty')" :image-size="72" />

</template>

<style scoped>
.mcp-list { display: flex; flex-direction: column; gap: 12px; }
.mcp-row { border: 1px solid var(--el-border-color-light); border-radius: 12px; padding: 14px 16px; background: var(--el-bg-color); }
.mcp-head { display: flex; align-items: flex-start; gap: 12px; }
.mcp-icon { color: var(--el-color-primary); margin-top: 2px; }
.mcp-meta { flex: 1; min-width: 0; }
.mcp-name { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.mcp-command { display: block; margin: 6px 0; color: var(--el-text-color-secondary); word-break: break-all; }
.mcp-stats { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12px; color: var(--el-text-color-secondary); }
.mcp-error { margin-top: 6px; font-size: 12px; color: var(--el-color-danger); word-break: break-all; }
.mcp-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.mcp-tools { margin-top: 10px; }
.mcp-tools-toggle { border: none; background: none; color: var(--el-color-primary); cursor: pointer; padding: 0; }
.mcp-tools ul, .exposed-list { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.mcp-tools li, .exposed-list li { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.mcp-tools li span, .exposed-list li span { color: var(--el-text-color-secondary); }
.mcp-form { display: flex; flex-direction: column; gap: 8px; min-width: 320px; }
.mcp-form-actions { display: flex; align-items: center; justify-content: space-between; }
</style>
