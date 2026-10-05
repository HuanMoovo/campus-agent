<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import { filterCommands } from '../commands'
import { t } from '../i18n'

interface PaletteItem {
  id: string
  label: string
  hint?: string
}

const props = defineProps<{ open: boolean; items: PaletteItem[] }>()
const emit = defineEmits<{ (event: 'update:open', value: boolean): void; (event: 'select', id: string): void }>()

const query = ref('')
const active = ref(0)
const inputRef = ref<HTMLInputElement | null>(null)

const filtered = computed(() => filterCommands(props.items, query.value))

watch(() => props.open, async open => {
  if (!open) return
  query.value = ''
  active.value = 0
  await nextTick()
  inputRef.value?.focus()
})

watch(filtered, () => { active.value = 0 })

function run(id?: string) {
  const target = id ?? filtered.value[active.value]?.id
  if (!target) return
  emit('update:open', false)
  emit('select', target)
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    active.value = Math.min(active.value + 1, Math.max(filtered.value.length - 1, 0))
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    active.value = Math.max(active.value - 1, 0)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    run()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    emit('update:open', false)
  }
}
</script>

<template>
  <div v-if="open" class="command-palette" role="dialog" :aria-label="t('palette.title')" @click.self="emit('update:open', false)">
    <div class="palette-panel">
      <input ref="inputRef" v-model="query" class="palette-input" :placeholder="t('palette.placeholder')" :aria-label="t('palette.placeholder')" @keydown="onKeydown" />
      <div v-if="filtered.length" class="palette-list" role="listbox">
        <button v-for="(item, index) in filtered" :key="item.id" type="button" class="palette-item" :class="{ active: index === active }" role="option" :aria-selected="index === active" @click="run(item.id)" @mousemove="active = index">
          <span class="palette-label">{{ item.label }}</span>
          <small v-if="item.hint">{{ item.hint }}</small>
        </button>
      </div>
      <p v-else class="palette-empty">{{ t('palette.empty') }}</p>
    </div>
  </div>
</template>

<style scoped>
.command-palette { position: fixed; inset: 0; z-index: 60; background: rgba(18, 31, 34, .38); display: flex; justify-content: center; align-items: flex-start; padding: 14vh 16px 16px; }
.palette-panel { width: min(560px, 100%); background: var(--surface); border: 1px solid var(--border); border-radius: 6px; box-shadow: 0 18px 50px #00000033; overflow: hidden; }
.palette-input { width: 100%; border: 0; outline: 0; padding: 14px 16px; font-size: 14px; background: transparent; color: var(--text); border-bottom: 1px solid var(--border-subtle); font-family: inherit; }
.palette-list { max-height: 320px; overflow-y: auto; padding: 6px; }
.palette-item { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 12px; border: 0; background: transparent; padding: 9px 12px; border-radius: 5px; color: var(--text); font-size: 13px; text-align: left; cursor: pointer; font-family: inherit; }
.palette-item small { color: var(--text-muted); font-size: 11px; flex-shrink: 0; }
.palette-item.active { background: var(--accent-soft); color: var(--accent-text); }
.palette-item.active small { color: var(--accent-text); }
.palette-empty { margin: 0; padding: 22px 16px; color: var(--text-muted); font-size: 12px; text-align: center; }
</style>
