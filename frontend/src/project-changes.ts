import type { ProjectChangeReceipt } from './desktop'
import { ref } from 'vue'
import { t } from './i18n'

export function unresolvedChange(receipt: ProjectChangeReceipt | null): boolean {
  return receipt?.state === 'pending' || receipt?.state === 'uncertain'
}

// Keep ambiguous operations across panel remounts in this renderer session.
// Only opaque receipts are retained; file contents are never stored here.
const unresolved = new Map<string, Map<string, ProjectChangeReceipt>>()
export const changeSessionRevision = ref(0)
const receiptKey = (receipt: ProjectChangeReceipt) => `${receipt.action}/${receipt.subject_id}`

export function sameChangeOperation(left: ProjectChangeReceipt | null | undefined, right: ProjectChangeReceipt | null | undefined): boolean {
  return Boolean(left && right && left.operation_id && left.operation_id === right.operation_id
    && sameChangeTarget(left, right.project_id, right.subject_id, right.action))
}

export function rememberChangeResult(receipt: ProjectChangeReceipt, notify = true) {
  let records = unresolved.get(receipt.project_id)
  let changed = false
  if (unresolvedChange(receipt)) {
    if (!records) { records = new Map(); unresolved.set(receipt.project_id, records) }
    records.set(receiptKey(receipt), { ...receipt })
    changed = true
  } else if (records) {
    const prior = records.get(receiptKey(receipt))
    if (prior && (sameChangeOperation(prior, receipt) || !prior.operation_id)) { records.delete(receiptKey(receipt)); changed = true }
    if (!records.size) unresolved.delete(receipt.project_id)
  }
  if (changed && notify) changeSessionRevision.value++
}

export function mergeUnresolvedChanges(projectId: string, incoming: ProjectChangeReceipt[]): ProjectChangeReceipt[] {
  const result = [...incoming]
  for (const receipt of unresolved.get(projectId)?.values() || []) {
    const matching = result.find(row => sameChangeOperation(row, receipt))
    if (matching && !unresolvedChange(matching)) { rememberChangeResult(matching); continue }
    const index = result.findIndex(row => receipt.recovery_id ? row.recovery_id === receipt.recovery_id : row.proposal_id === receipt.proposal_id)
    if (index < 0) result.unshift(receipt)
    else result[index] = receipt
  }
  return result
}

export function changeErrorMessage(value: unknown): string {
  const code = typeof value === 'string' ? value : value instanceof Error ? /\[(project_change_[a-z_]+)\]/.exec(value.message)?.[1] : ''
  switch (code) {
    case 'project_change_read_only': return t('project.change.readOnly')
    case 'project_change_unsupported': return t('project.change.unsupported')
    case 'project_change_conflict': return t('project.change.conflict')
    case 'project_change_busy': return t('project.change.busy')
    case 'project_change_limit': return t('project.change.limit')
    case 'project_change_journal_unavailable': return t('project.change.journalUnavailable')
    case 'project_change_not_found': return t('project.change.notFound')
    case 'project_change_invalid': return t('project.change.invalid')
    default: return t('project.change.requestFailed')
  }
}

export function sameChangeTarget(result: ProjectChangeReceipt, projectId: string, subjectId: string, action: ProjectChangeReceipt['action']): boolean {
  return Boolean(result && result.project_id === projectId && result.subject_id === subjectId && result.action === action)
}
