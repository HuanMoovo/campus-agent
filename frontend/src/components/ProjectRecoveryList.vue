<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { desktop, type ProjectChangeReceipt, type ProjectRecoveryArchive } from '../desktop'
import { changeErrorMessage, changeSessionRevision, mergeUnresolvedChanges } from '../project-changes'
import { t } from '../i18n'
import ProjectChangeActions from './ProjectChangeActions.vue'
import ProjectRecoveryArchives from './ProjectRecoveryArchives.vue'

const props = withDefaults(defineProps<{ projectId: string; writeAllowed?: boolean; connected?: boolean; disabled?: boolean; revision?: number }>(), { connected: true, disabled: false, revision: 0, writeAllowed: true })
const emit = defineEmits<{ busy: [value: boolean]; changed: [receipt: ProjectChangeReceipt] }>()
const records = ref<ProjectChangeReceipt[]>([])
const archives = ref<ProjectRecoveryArchive[]>([])
const archiveBusy = ref(false)
const available = ref(false)
const loading = ref(false)
const active = ref(new Set<string>())
const error = ref('')
const busy = computed(() => loading.value || active.value.size > 0 || archiveBusy.value)
let alive = true; let generation = 0; let request = 0
let scheduled = false
watch(busy, value => emit('busy', value), { flush: 'sync' })

function queueRead() {
  if (!alive || scheduled || loading.value || !desktop?.projectChanges || !props.projectId || !props.connected) return
  const token = generation
  scheduled = true
  queueMicrotask(() => {
    if (!alive || token !== generation) return
    scheduled = false
    void load()
  })
}
function refresh() {
  request++
  queueRead()
}
async function load() {
  if (!desktop?.projectChanges || !props.projectId || !props.connected || loading.value) return
  const token = generation; const id = props.projectId; const currentRequest = request
  loading.value = true; error.value = ''
  try {
    const result = await desktop.projectChanges(id)
    if (!alive || token !== generation || id !== props.projectId || currentRequest !== request) return
    available.value = result.available; records.value = mergeUnresolvedChanges(id, result.records)
    archives.value = result.archives || []
  } catch (failure) {
    if (alive && token === generation && currentRequest === request) error.value = changeErrorMessage(failure)
  } finally {
    if (alive && token === generation && id === props.projectId) {
      loading.value = false
      if (currentRequest !== request) queueRead()
    }
  }
}
function rowBusy(id: string, value: boolean) {
  const next = new Set(active.value); if (value) next.add(id); else next.delete(id); active.value = next
}
function changed(receipt: ProjectChangeReceipt) {
  records.value = mergeUnresolvedChanges(props.projectId, records.value)
  emit('changed', receipt); refresh()
}
watch(() => [props.projectId, props.connected] as const, () => {
  generation++; request++; scheduled = false; loading.value = false; active.value = new Set(); error.value = ''; records.value = []; archives.value = []; archiveBusy.value = false; available.value = false
  queueRead()
}, { immediate: true, flush: 'sync' })
watch([() => props.revision, changeSessionRevision], refresh)
onUnmounted(() => { alive = false; generation++; request++; emit('busy', false) })
</script>

<template>
  <details v-if="desktop?.projectChanges" class="project-recoveries">
    <summary>{{ t('project.change.recoveries') }} <span v-if="records.length + archives.length">{{ records.length + archives.length }}</span></summary>
    <div class="recovery-content">
      <p class="recovery-note">{{ t('project.change.recoveryHelp') }}</p>
      <p class="recovery-note">{{ t('project.change.backupNote') }}</p>
      <button type="button" :disabled="busy || disabled || !connected" data-recovery-refresh @click="refresh">{{ t('project.change.refresh') }}</button>
      <p v-if="loading" role="status">{{ t('project.loading') }}</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="!error && !loading && !records.length && !archives.length">{{ t('project.change.empty') }}</p>
      <ol v-if="records.length">
        <li v-for="record in records" :key="`${record.recovery_id || record.proposal_id}:${record.operation_id || `${record.action}/${record.subject_id}`}`">
          <strong class="recovery-path">{{ record.path }}</strong>
          <small>{{ record.summary }}</small>
          <ProjectChangeActions :write-allowed="writeAllowed" :project-id="projectId" :receipt="record" :available="available" :connected="connected" :disabled="disabled || loading || archiveBusy || (active.size > 0 && !active.has(record.recovery_id))" @busy="rowBusy(record.recovery_id, $event)" @changed="changed" />
        </li>
      </ol>
      <ProjectRecoveryArchives :project-id="projectId" :archives="archives" :connected="connected" :disabled="disabled || loading || active.size > 0" @busy="archiveBusy = $event" />
    </div>
  </details>
</template>

<style scoped>
.project-recoveries { margin: 10px 0; border-top: 1px solid var(--border); }
summary { cursor: pointer; padding: 8px 0; }
.recovery-content { max-height: 340px; overflow: auto; }
p { margin: 6px 0; line-height: 1.6; }
.recovery-note, small { color: var(--text-secondary); }
ol { list-style: none; padding: 0; margin: 8px 0; }
li { border-top: 1px solid var(--border-subtle); padding: 9px 0; }
.recovery-path, small { display: block; overflow-wrap: anywhere; }
button { padding: 4px 7px; border: 1px solid var(--border); border-radius: 5px; color: var(--text); background: var(--surface); font: inherit; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
</style>
