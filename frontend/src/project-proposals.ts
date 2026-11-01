import { t } from './i18n'
import type { ReasoningPreference } from './reasoning'

export interface ProjectProposalLine {
  kind: 'header' | 'hunk' | 'context' | 'add' | 'remove' | 'no_newline'
  text: string
  old_line: number | null
  new_line: number | null
}

export interface ProjectProposal {
  id: string
  project_id: string
  path: string
  state: 'ready' | 'conflict'
  summary: string
  before_text: string
  after_text: string
  diff: string
  diff_lines: ProjectProposalLine[]
  added_lines: number
  removed_lines: number
  base_sha256: string
  proposed_sha256: string
  created_at: string
  model: string
  model_name: string
  bom: boolean
  newline: 'none' | 'lf' | 'crlf' | 'cr' | 'mixed'
  after_newline?: ProjectProposal['newline']
}

export interface ProjectProposalRequest {
  path: string
  instruction: string
  model: string
  localModel?: string
  reasoning?: ReasoningPreference | 'fast'
}

/** Proposal errors deliberately do not retain raw filesystem or provider details. */
export class ProjectProposalError extends Error {
  constructor(public readonly code: string, public readonly status: number) {
    super(t('project.proposal.generateFailed'))
    this.name = 'ProjectProposalError'
  }
}

export function proposalErrorMessage(error: unknown, checking = false): string {
  if (error instanceof ProjectProposalError) {
    switch (error.code) {
      case 'project_proposal_conflict': return t('project.proposal.conflict')
      case 'project_proposal_expired':
      case 'project_proposal_not_found':
      case 'project_not_found': return t('project.proposal.expired')
      case 'project_proposal_limit': return t('project.proposal.quota')
      case 'project_proposal_too_large': return t('project.proposal.oversize')
      case 'project_proposal_no_change': return t('project.proposal.noChange')
      case 'project_proposal_model_unavailable': return t('project.proposal.modelUnavailable')
      case 'project_proposal_invalid_result': return t('project.proposal.invalidResult')
      case 'project_proposal_reasoning': return t('project.proposal.reasoningUnavailable')
      case 'project_service_unavailable': return t('project.proposal.disconnected')
    }
    if (error.status === 409) return t('project.proposal.conflict')
    if (error.status === 410 || error.status === 404) return t('project.proposal.expired')
    if (error.status === 429) return t('project.proposal.quota')
    if (error.status === 503) return t('project.proposal.modelUnavailable')
    if (error.status === 502) return t('project.proposal.invalidResult')
  }
  return t(checking ? 'project.proposal.checkFailed' : 'project.proposal.generateFailed')
}
