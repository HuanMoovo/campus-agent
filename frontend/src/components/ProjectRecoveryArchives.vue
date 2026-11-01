<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { desktop, type ProjectRecoveryArchive } from '../desktop'
import { t } from '../i18n'

const props = withDefaults(defineProps<{ projectId: string; archives: ProjectRecoveryArchive[]; connected?: boolean; disabled?: boolean }>(), { connected: true, disabled: false })
const emit = defineEmits<{ busy: [value: boolean] }>()
const copying = ref('')
const copied = ref('')
const error = ref('')
const busy = computed(() => Boolean(copying.value))
let alive = true; let epoch = 0
watch(busy, value => emit('busy', value), { flush: 'sync' })
watch(() => [props.projectId, props.connected] as const, () => {
  epoch++; copying.value = ''; copied.value = ''; error.value = ''
}, { flush: 'sync' })
onUnmounted(() => { alive = false; epoch++; emit('busy', false) })

async function copy(archiveId: string) {
  if (!desktop?.projectRecoveryOriginal || busy.value || props.disabled || !props.connected) return
  const projectId = props.projectId; const token = epoch
  const current = () => alive && token === epoch && projectId === props.projectId && props.connected
    && props.archives.some(row => row.archive_id === archiveId)
  copying.value = archiveId; copied.value = ''; error.value = ''
  try {
    const original = await desktop.projectRecoveryOriginal(projectId, archiveId)
    if (!current()) return
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable')
    await navigator.clipboard.writeText(original.text)
    if (current()) copied.value = archiveId
  } catch { if (current()) error.value = t('project.proposal.copyFailed') }
  finally { if (alive && token === epoch) copying.value = '' }
}
</script>

<template>
  <section v-if="archives.length" class="project-recovery-archives" :aria-busy="busy">
    <h4>{{ t('project.archive.title') }}</h4>
    <p class="archive-note">{{ t('project.archive.help') }}</p>
    <ul>
      <li v-for="record in archives" :key="record.archive_id">
        <strong>{{ record.path }}</strong><small>{{ record.size_bytes }} B</small>
        <p v-if="record.summary">{{ record.summary }}</p>
        <button type="button" data-copy-archive :disabled="disabled || !connected || busy" @click="copy(record.archive_id)">{{ t(copying === record.archive_id ? 'project.archive.copying' : 'project.change.copyOriginal') }}</button>
        <span v-if="copied === record.archive_id" role="status">{{ t('project.change.originalCopied') }}</span>
      </li>
    </ul>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.project-recovery-archives { border-top: 1px solid var(--border); margin-top: 10px; padding-top: 8px; }
h4 { margin: 0; font-size: 12px; }
p { margin: 6px 0; line-height: 1.6; overflow-wrap: anywhere; }
.archive-note, small { color: var(--text-secondary); }
ul { list-style: none; margin: 0; padding: 0; }
li { padding: 8px 0; border-top: 1px solid var(--border-subtle); }
strong { overflow-wrap: anywhere; margin-right: 8px; }
button { font: inherit; padding: 4px 7px; border: 1px solid var(--border); border-radius: 5px; background: var(--surface); color: var(--text); cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
[role='status'] { display: block; margin-top: 5px; }
</style>
