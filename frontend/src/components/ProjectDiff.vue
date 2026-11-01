<script setup lang="ts">
import { t } from '../i18n'
import type { ProjectProposalLine } from '../project-proposals'

defineProps<{ lines: ProjectProposalLine[] }>()
</script>

<template>
  <div class="proposal-diff" tabindex="0" role="region" :aria-label="t('project.proposal.diff')">
    <table>
      <thead><tr><th scope="col">{{ t('project.proposal.oldLine') }}</th><th scope="col">{{ t('project.proposal.newLine') }}</th><th scope="col" aria-label="+ / −"></th><th scope="col">{{ t('project.proposal.lineContent') }}</th></tr></thead>
      <tbody>
        <tr v-for="(line, index) in lines" :key="index" :class="`diff-${line.kind}`">
          <td class="diff-old-line">{{ line.old_line ?? '' }}</td>
          <td class="diff-new-line">{{ line.new_line ?? '' }}</td>
          <td class="diff-marker">{{ line.kind === 'add' ? '+' : line.kind === 'remove' ? '−' : '' }}</td>
          <td class="diff-text"><code>{{ line.text }}</code></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.proposal-diff { min-width: 0; overflow: auto; border: 1px solid var(--border, #ccc); border-radius: 5px; color: var(--text, #222); background: var(--surface, #fff); }
table { min-width: 100%; border-collapse: collapse; font-family: var(--font-code); font-size: 12px; line-height: 1.7; }
th { font-family: inherit; font-weight: 500; text-align: left; white-space: nowrap; color: var(--text-secondary, #666); background: var(--surface-hover, #eee); }
th, td { padding: 1px 7px; vertical-align: top; }
.diff-old-line, .diff-new-line { width: 1%; min-width: 3ch; text-align: right; color: var(--text-secondary, #777); user-select: none; font-variant-numeric: tabular-nums; border-right: 1px solid var(--border, #ddd); }
.diff-marker { width: 1%; min-width: 1ch; text-align: center; font-weight: 700; user-select: none; }
.diff-text { white-space: pre; }
.diff-text code { font: inherit; }
.diff-add { background: var(--surface-hover, #eee); }
.diff-remove .diff-text { text-decoration: line-through; text-decoration-color: var(--text-secondary, #888); }
.diff-header, .diff-hunk, .diff-no_newline { color: var(--text-secondary, #666); }
.diff-hunk { border-top: 1px solid var(--border, #ddd); }
</style>
