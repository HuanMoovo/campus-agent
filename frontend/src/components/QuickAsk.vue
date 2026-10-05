<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import { t } from '../i18n'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (event: 'update:open', value: boolean): void; (event: 'submit', question: string): void }>()

const question = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)

watch(() => props.open, async open => {
  if (!open) return
  question.value = ''
  await nextTick()
  inputRef.value?.focus()
})

function submit() {
  if (!question.value.trim()) return
  emit('update:open', false)
  emit('submit', question.value)
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submit()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    emit('update:open', false)
  }
}
</script>

<template>
  <div v-if="open" class="quick-ask" role="dialog" :aria-label="t('quick.title')" @click.self="emit('update:open', false)">
    <div class="quick-panel">
      <p class="quick-title">{{ t('quick.title') }}</p>
      <textarea ref="inputRef" v-model="question" rows="2" maxlength="4000" :placeholder="t('quick.placeholder')" :aria-label="t('quick.placeholder')" @keydown="onKeydown" />
      <div class="quick-hint">
        <span>{{ t('quick.hint') }}</span>
        <el-button type="primary" size="small" :disabled="!question.trim()" @click="submit">{{ t('quick.submit') }}</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.quick-ask { position: fixed; inset: 0; z-index: 65; background: rgba(18, 31, 34, .38); display: flex; justify-content: center; align-items: flex-start; padding: 12vh 16px 16px; }
.quick-panel { width: min(560px, 100%); background: var(--surface); border: 1px solid var(--border); border-radius: 6px; box-shadow: 0 18px 50px #00000033; padding: 14px 16px 12px; }
.quick-title { margin: 0 0 8px; font-size: 12px; font-weight: 700; color: var(--text); }
.quick-panel textarea { resize: none; border: 0; outline: 0; width: 100%; min-height: 52px; background: transparent; color: var(--text); font-size: 13px; line-height: 1.6; font-family: inherit; }
.quick-panel textarea::placeholder { color: var(--text-muted); }
.quick-hint { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 6px; }
.quick-hint span { color: var(--text-muted); font-size: 11px; }
</style>
