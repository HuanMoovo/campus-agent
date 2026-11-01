<script setup lang="ts">
import { computed } from 'vue'
import type { AgentRun, ChatPhase, ContextReport } from '../api'
import { contextNotice } from '../agent-diagnostics'
import { t } from '../i18n'

const props = defineProps<{ phase?: ChatPhase; context?: ContextReport; run?: AgentRun }>()
const notice = computed(() => contextNotice(props.context))
function elapsed(milliseconds: number) {
  return milliseconds < 1000 ? `${Math.round(milliseconds)} ms` : `${(milliseconds / 1000).toFixed(2)} s`
}
</script>

<template>
  <div v-if="phase || notice || run" class="agent-diagnostics">
    <p v-if="phase" class="agent-waiting" role="status" aria-live="polite">{{ t(`chat.phase.${phase}`) }}</p>
    <p v-if="notice" class="context-notice">{{ notice }}</p>
    <details v-if="run" class="run-details">
      <summary>{{ t('chat.run.summary') }} · {{ t(`chat.run.${run.status}`) }} · {{ elapsed(run.duration_ms) }}</summary>
      <div v-if="run.task" class="run-task">
        <p>{{ t('chat.task.budget', { attempted: run.task.attempted_steps, limit: run.task.limit_steps }) }} · {{ t(`chat.task.stop.${run.task.stop_reason}`) }}</p>
        <p v-if="run.task.truncated_results">{{ t('chat.task.truncated', { count: run.task.truncated_results }) }}</p>
      </div>
      <ol v-if="run.steps.length" class="run-steps">
        <li v-for="(step, index) in run.steps" :key="index">
          <span>{{ t(`chat.step.${step.phase}`) }}</span>
          <span>{{ t(`chat.run.${step.status}`) }} · {{ elapsed(step.duration_ms) }}</span>
        </li>
      </ol>
    </details>
  </div>
</template>

<style scoped>
.agent-diagnostics { margin-top: 10px; color: var(--text-muted); font-size: 12px; line-height: 1.65; overflow-wrap: anywhere; }
.agent-waiting, .context-notice { margin: 0 0 5px; }
.agent-waiting { color: var(--text-secondary); }
.run-details summary { width: fit-content; max-width: 100%; cursor: pointer; border-radius: 3px; }
.run-details summary:focus-visible { outline: 2px solid var(--text-muted); outline-offset: 3px; }
.run-task { margin-top: 7px; font-variant-numeric: tabular-nums; }
.run-task p { margin: 0; }
.run-steps { max-width: 360px; margin: 7px 0 0; padding: 0 0 0 15px; border-left: 1px solid var(--border-subtle); list-style: none; }
.run-steps li { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 2px 14px; padding: 2px 0; }
.run-steps li span:last-child { font-variant-numeric: tabular-nums; }
</style>
