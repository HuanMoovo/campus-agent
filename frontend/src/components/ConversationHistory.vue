<script setup lang="ts">
import { Bottom, Delete, Download, EditPen, MoreFilled, Refresh, Search, Top } from '@element-plus/icons-vue'
import type { ConversationSearchResult, ConversationSummary } from '../api'
import { t } from '../i18n'

const props = defineProps<{
  conversations: ConversationSummary[]
  conversationsBusy: boolean
  conversationsError: string
  historyQuery: string
  historyResults: ConversationSearchResult[]
  historySearchActive: boolean
  historySearchBusy: boolean
  historySearchError: string
  historySelectMode: boolean
  historySelected: string[]
  conversationId: string
  ready: boolean
  chatBusy: boolean
}>()

const emit = defineEmits<{
  (event: 'update:historyQuery', value: string): void
  (event: 'search-input'): void
  (event: 'search'): void
  (event: 'clear-search'): void
  (event: 'refresh'): void
  (event: 'clear'): void
  (event: 'toggle-select'): void
  (event: 'batch-delete'): void
  (event: 'open-result', result: ConversationSearchResult): void
  (event: 'item-click', item: ConversationSummary): void
  (event: 'item-command', item: ConversationSummary, command: string): void
}>()

function chatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const time = `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  return date.toDateString() === new Date().toDateString() ? time : `${date.getMonth() + 1}/${date.getDate()} ${time}`
}

function openItem(item: ConversationSummary) {
  if (props.ready && !props.chatBusy) emit('item-click', item)
}

function openResult(result: ConversationSearchResult) {
  if (props.ready && !props.chatBusy) emit('open-result', result)
}
</script>

<template>
  <section class="history-panel" :aria-label="t('history.title')">
    <div class="history-head">
      <strong>{{ t('history.title') }}</strong><span class="history-count">{{ conversations.length }}</span>
      <el-button text :icon="Refresh" :loading="conversationsBusy" :disabled="!ready" :aria-label="t('history.refresh')" :title="t('history.refresh')" @click="emit('refresh')" />
      <el-button text :disabled="!ready || !conversations.length || chatBusy" @click="emit('clear')">{{ t('history.clear') }}</el-button>
    </div>
    <div class="history-tools">
      <el-input
        :model-value="historyQuery"
        size="small"
        clearable
        :disabled="!ready"
        :prefix-icon="Search"
        :placeholder="t('history.searchPlaceholder')"
        :aria-label="t('history.searchPlaceholder')"
        @update:model-value="emit('update:historyQuery', String($event))"
        @input="emit('search-input')"
        @keydown.enter="emit('search')"
        @clear="emit('clear-search')"
      />
      <el-button text size="small" :type="historySelectMode ? 'primary' : ''" :disabled="!ready || chatBusy" :aria-pressed="historySelectMode" @click="emit('toggle-select')">{{ historySelectMode ? t('history.selectExit') : t('history.select') }}</el-button>
    </div>
    <div v-if="historySelectMode" class="history-select-bar">
      <span>{{ t('history.selected', { count: historySelected.length }) }}</span>
      <el-button text type="danger" size="small" :disabled="!historySelected.length || chatBusy" @click="emit('batch-delete')">{{ t('history.deleteSelected') }}</el-button>
    </div>
    <p v-if="conversationsError && !historySearchActive" class="history-error">{{ conversationsError }}</p>
    <div class="history-list" v-loading="conversationsBusy || historySearchBusy" :aria-busy="conversationsBusy || historySearchBusy">
      <p v-if="historySearchError" class="history-error">{{ historySearchError }}</p>
      <p v-if="historySearchActive && !historySearchBusy && !historySearchError && !historyResults.length" class="history-empty">{{ t('history.searchEmpty') }}</p>
      <template v-if="historySearchActive">
        <div
          v-for="result in historyResults"
          :key="result.conversation_id"
          class="history-item search-item"
          :class="{ disabled: !ready || chatBusy }"
          role="button"
          :tabindex="!ready || chatBusy ? -1 : 0"
          :aria-disabled="!ready || chatBusy"
          @click="openResult(result)"
          @keydown.enter.self.prevent="openResult(result)"
          @keydown.space.self.prevent="openResult(result)"
        ><div class="history-item-main"><strong>{{ result.title }}</strong><small>{{ result.snippet }}</small></div></div>
      </template>
      <template v-else>
        <p v-if="!conversationsBusy && !conversationsError && conversations.length === 0" class="history-empty">{{ t('history.empty') }}<br />{{ t('history.emptyHint') }}</p>
        <div
          v-for="item in conversations"
          :key="item.id"
          class="history-item"
          :class="{ active: item.id === conversationId, disabled: !ready || chatBusy, selected: historySelected.includes(item.id) }"
          role="button"
          :tabindex="!ready || chatBusy ? -1 : 0"
          :aria-current="item.id === conversationId ? 'true' : undefined"
          :aria-disabled="!ready || chatBusy"
          @click="openItem(item)"
          @keydown.enter.self.prevent="openItem(item)"
          @keydown.space.self.prevent="openItem(item)"
        >
          <el-checkbox v-if="historySelectMode" class="history-check" :model-value="historySelected.includes(item.id)" :disabled="!ready || chatBusy" :aria-label="item.title" @click.stop @change="openItem(item)" />
          <div class="history-item-main">
            <strong><span v-if="item.pinned" class="pin-badge">{{ t('history.pinned') }}</span>{{ item.title }}</strong>
            <small>{{ t('history.count', { count: item.message_count }) }} · {{ chatTime(item.updated_at) }}</small>
          </div>
          <el-dropdown v-if="!historySelectMode" class="history-menu" trigger="click" @command="(command: string) => emit('item-command', item, command)" @click.stop>
            <el-button class="history-more" text :icon="MoreFilled" :disabled="!ready || chatBusy" :aria-label="t('history.more', { title: item.title })" />
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="rename" :icon="EditPen">{{ t('history.rename') }}</el-dropdown-item>
                <el-dropdown-item command="pin" :icon="item.pinned ? Bottom : Top">{{ item.pinned ? t('history.unpin') : t('history.pin') }}</el-dropdown-item>
                <el-dropdown-item command="md" :icon="Download" divided>{{ t('history.exportMarkdown') }}</el-dropdown-item>
                <el-dropdown-item command="json" :icon="Download">{{ t('history.exportJson') }}</el-dropdown-item>
                <el-dropdown-item command="delete" :icon="Delete" divided>{{ t('common.delete') }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </template>
    </div>
  </section>
</template>
