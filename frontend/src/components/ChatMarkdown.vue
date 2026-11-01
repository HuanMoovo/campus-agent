<script setup lang="ts">
import { onUnmounted, shallowRef, watch } from 'vue'
import { createChatMarkdown } from '../chat-markdown'

const props = defineProps<{ text: string; streaming?: boolean; messageKey: object }>()
const emit = defineEmits<{ (event: 'rendered'): void }>()
const html = shallowRef('')
const renderer = createChatMarkdown(value => {
  if (html.value === value) return
  html.value = value
  emit('rendered')
})
watch(() => [props.text, props.streaming, props.messageKey] as const,
  ([text, streaming, identity]) => renderer.update(text, Boolean(streaming), identity),
  { immediate: true })
onUnmounted(renderer.dispose)
</script>

<template>
  <div class="markdown-body" v-html="html" />
</template>
