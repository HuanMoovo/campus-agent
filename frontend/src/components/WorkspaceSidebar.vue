<script setup lang="ts">
import { ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, ChatLineRound, Close, Connection, FolderOpened, Grid, Plus, Search, Setting, Tools, User } from '@element-plus/icons-vue'
import type { View } from '../store'
import { t } from '../i18n'

const props = withDefaults(defineProps<{
  view: View
  mobileOpen: boolean
  collapsed?: boolean
  ready: boolean
  busy: boolean
  connectedLabel: string
  connected?: boolean
  logo: string
  username?: string
  version?: string
}>(), { collapsed: false, connected: false, username: '', version: '' })

const emit = defineEmits<{
  (event: 'navigate', view: View): void
  (event: 'new-chat'): void
  (event: 'open-palette'): void
  (event: 'close'): void
  (event: 'sign-out'): void
  (event: 'toggle-collapse'): void
}>()

const mainNavigation = [
  { key: 'chat', labelKey: 'nav.chat', icon: ChatLineRound },
  { key: 'services', labelKey: 'nav.services', icon: Grid },
  { key: 'knowledge', labelKey: 'nav.knowledge', icon: FolderOpened },
] as const
const toolNavigation = [
  { key: 'plugins', labelKey: 'nav.plugins', icon: Connection },
  { key: 'mcp', labelKey: 'nav.mcp', icon: Connection },
] as const
const toolsOpen = ref(props.view === 'plugins' || props.view === 'mcp')

watch(() => props.view, view => {
  if (view === 'plugins' || view === 'mcp') toolsOpen.value = true
})
</script>

<template>
  <aside
    class="sidebar"
    :class="{ 'sidebar-open': mobileOpen, 'sidebar-collapsed': collapsed }"
    :aria-label="t('nav.workspace')"
    @keydown.esc="mobileOpen && emit('close')"
  >
    <div class="brand">
      <img class="brand-mark" :src="logo" alt="" />
      <strong class="brand-name">Mens</strong>
      <button
        type="button"
        class="icon-button sidebar-toggle"
        :aria-label="t(collapsed ? 'app.expandNav' : 'app.collapseNav')"
        :title="t(collapsed ? 'app.expandNav' : 'app.collapseNav')"
        :aria-expanded="!collapsed"
        @click="emit('toggle-collapse')"
      ><el-icon :size="16"><ArrowRight v-if="collapsed" /><ArrowLeft v-else /></el-icon></button>
      <button type="button" class="icon-button sidebar-close" :aria-label="t('app.closeNav')" @click="emit('close')">
        <el-icon :size="18"><Close /></el-icon>
      </button>
    </div>

    <div class="sidebar-body">
    <div class="side-content">
      <button type="button" class="nav-item sidebar-new-chat" :title="t('chat.new')" :disabled="!ready || busy" @click="emit('new-chat')">
        <el-icon :size="18"><Plus /></el-icon><span class="sidebar-label">{{ t('chat.new') }}</span>
      </button>
      <button type="button" class="nav-item sidebar-search" :title="t('palette.hint')" @click="emit('open-palette')">
        <el-icon :size="18"><Search /></el-icon><span class="sidebar-label">{{ t('palette.title') }}</span><kbd class="command-shortcut">Ctrl K</kbd>
      </button>

      <nav class="sidebar-nav" :aria-label="t('nav.workspace')">
        <button
          v-for="item in mainNavigation"
          :key="item.key"
          type="button"
          class="nav-item"
          :class="{ active: view === item.key }"
          :aria-current="view === item.key ? 'page' : undefined"
          :title="t(item.labelKey)"
          @click="emit('navigate', item.key)"
        ><el-icon :size="18"><component :is="item.icon" /></el-icon><span class="sidebar-label">{{ t(item.labelKey) }}</span></button>

        <details class="sidebar-tools" :open="toolsOpen" @toggle="toolsOpen = ($event.target as HTMLDetailsElement).open">
          <summary class="nav-item" :class="{ active: view === 'plugins' || view === 'mcp' }" :title="t('nav.tools')">
            <el-icon :size="18"><Tools /></el-icon><span class="sidebar-label">{{ t('nav.tools') }}</span><el-icon class="sidebar-tools-arrow" :size="12"><ArrowRight /></el-icon>
          </summary>
          <div class="sidebar-tool-list">
            <button
              v-for="item in toolNavigation"
              :key="item.key"
              type="button"
              class="nav-item"
              :class="{ active: view === item.key }"
              :aria-current="view === item.key ? 'page' : undefined"
              :title="t(item.labelKey)"
              @click="emit('navigate', item.key)"
            ><el-icon :size="16"><component :is="item.icon" /></el-icon><span class="sidebar-label">{{ t(item.labelKey) }}</span></button>
          </div>
        </details>
      </nav>
    </div>

    <div class="sidebar-history"><slot name="history" /></div>
    </div>

    <footer class="side-footer">
      <nav class="sidebar-footer-nav" :aria-label="t('nav.admin')">
        <button type="button" class="nav-item" :class="{ active: view === 'settings' }" :aria-current="view === 'settings' ? 'page' : undefined" :title="t('nav.settings')" @click="emit('navigate', 'settings')">
          <el-icon :size="18"><Setting /></el-icon><span class="sidebar-label">{{ t('nav.settings') }}</span>
        </button>
        <button type="button" class="nav-item" :class="{ active: view === 'account' }" :aria-current="view === 'account' ? 'page' : undefined" :title="username || t('nav.account')" @click="emit('navigate', 'account')">
          <el-icon :size="18"><User /></el-icon><span class="sidebar-label">{{ username || t('nav.account') }}</span>
        </button>
      </nav>
      <div class="sidebar-status" :title="connectedLabel">
        <span class="connection-dot" :class="{ demo: !connected }" aria-hidden="true" />
        <span class="sidebar-label">{{ connectedLabel }}</span>
        <span v-if="version" class="side-version">{{ version }}</span>
      </div>
      <button v-if="username" type="button" class="side-logout" :title="t('auth.signedIn', { name: username })" @click="emit('sign-out')">{{ t('auth.logout') }}</button>
    </footer>
  </aside>
</template>
