import type { AgentRun, CampusReadTask, ChatPhase, ChatResponse, ContextReport, ConversationHistory, Source } from './api'
import { t } from './i18n'
import { attachmentSuffix, type ChatAttachment } from './attachments'
import { projectSuffix, type ProjectSelection } from './project-files'

export type ConversationMessage = {
  role: 'user' | 'assistant'; text: string; sources?: Source[]; tools?: string[]; demo?: boolean;
  error?: boolean; streaming?: boolean; stopped?: boolean; partial?: boolean; note?: string;
  thinking?: string; thinkingOpen?: boolean; id?: number; feedback?: 'up' | 'down';
  context?: ContextReport; run?: AgentRun; phase?: ChatPhase;
  requestText?: string; attachments?: ChatAttachment[]; project?: ProjectSelection;
}

export function createUserMessage(text: string, attachments: ChatAttachment[] = [], project?: ProjectSelection): ConversationMessage {
  return {
    role: 'user', requestText: text,
    text: [text, ...(attachments.length ? [attachmentSuffix(attachments.map(item => item.name))] : []), ...(project?.files.length ? [projectSuffix(project.files)] : [])].join('\n\n'),
    attachments: attachments.map(item => ({ ...item })),
    ...(project?.files.length ? { project: { id: project.id, files: [...project.files] } } : {}),
  }
}

export function regenerationRequest(user: ConversationMessage, assistant: ConversationMessage, replacements: ChatAttachment[] = []) {
  const attachments = (replacements.length ? replacements : user.attachments || []).map(item => ({ ...item }))
  const hadAttachments = Boolean(assistant.context?.attachments_used || assistant.context?.attachments_truncated)
  return { text: user.requestText ?? user.text.replace(/\n\n\[项目文件\] [^\n]+\s*$/, ''), attachments, missingAttachments: hadAttachments && attachments.length === 0 }
}

export function toConversationMessage(message: ConversationHistory['messages'][number]): ConversationMessage {
  const metadata = readAgentMetadata(message)
  return {
    role: message.role, text: message.content, sources: metadata.sources,
    tools: metadata.tool_calls?.map(call => call.name), demo: message.mode === 'demo',
    partial: Boolean(message.partial) || metadata.run?.status === 'partial', error: metadata.run?.status === 'failed',
    thinking: message.thinking || undefined, id: typeof message.id === 'number' ? message.id : undefined,
    feedback: message.feedback === 'up' || message.feedback === 'down' ? message.feedback : undefined,
    context: metadata.context, run: metadata.run,
  }
}

export function contextNotice(context?: ContextReport): string {
  if (!context?.trimmed) return ''
  const parts: string[] = []
  if (context.history_omitted) parts.push(t('chat.context.history', { count: context.history_omitted }))
  if (context.sources_omitted) parts.push(t('chat.context.sources', { count: context.sources_omitted }))
  if (context.sources_truncated) parts.push(t('chat.context.sourceTrim', { count: context.sources_truncated }))
  if (context.attachments_truncated) parts.push(t('chat.context.attachmentTrim', { count: context.attachments_truncated }))
  return t('chat.context.notice', { details: parts.join(t('chat.context.separator')) || t('chat.context.generic') })
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function duration(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
}

function readCampusTask(value: unknown): CampusReadTask | undefined {
  if (!record(value) || value.kind !== 'campus_reads' || value.limit_steps !== 3 || value.limit_ms !== 20000) return undefined
  const { planned_steps, attempted_steps, completed_steps, truncated_results, stop_reason } = value
  if (![planned_steps, attempted_steps, completed_steps, truncated_results].every(item => duration(item) && Number.isInteger(item))) return undefined
  const planned = planned_steps as number
  const attempted = attempted_steps as number
  const completed = completed_steps as number
  const truncated = truncated_results as number
  if (planned > 4 || attempted > 3 || attempted > planned || completed > attempted || truncated > completed) return undefined
  if (typeof stop_reason !== 'string' || !['completed', 'step_limit', 'deadline', 'cancelled', 'tool_error', 'invalid_request'].includes(stop_reason)) return undefined
  return {
    kind: 'campus_reads', limit_steps: 3, planned_steps: planned, attempted_steps: attempted,
    completed_steps: completed, limit_ms: 20000, stop_reason: stop_reason as CampusReadTask['stop_reason'],
    truncated_results: truncated,
  }
}

/** Optional diagnostics are additive: malformed data must not prevent an answer. */
export function readAgentMetadata(value: unknown): Partial<ChatResponse> {
  if (!record(value)) return {}
  const result: Partial<ChatResponse> = {}
  if (typeof value.conversation_id === 'string') result.conversation_id = value.conversation_id
  if (Array.isArray(value.sources)) result.sources = value.sources.filter(row => record(row) && typeof row.title === 'string')
  if (Array.isArray(value.tool_calls)) result.tool_calls = value.tool_calls.filter(row => record(row) && typeof row.name === 'string')
  if (record(value.web)) {
    result.web = Object.fromEntries(Object.entries(value.web).filter(([key, item]) => ['provider', 'error', 'fetched_at'].includes(key) && typeof item === 'string'))
  }
  const context = value.context
  const countKeys = ['limit_chars', 'input_chars', 'history_available', 'history_used', 'history_omitted', 'sources_used', 'sources_omitted', 'sources_truncated', 'attachments_used', 'attachments_truncated'] as const
  if (record(context) && typeof context.trimmed === 'boolean' && countKeys.every(key => duration(context[key]) && Number.isInteger(context[key]))) {
    result.context = { ...Object.fromEntries(countKeys.map(key => [key, context[key]])), trimmed: context.trimmed } as ContextReport
  }
  const run = value.run
  if (record(run) && typeof run.id === 'string' && typeof run.status === 'string' && ['running', 'completed', 'partial', 'failed'].includes(run.status) && duration(run.duration_ms) && Array.isArray(run.steps)) {
    const steps = run.steps.filter(step => record(step) && typeof step.phase === 'string' && ['plan', 'retrieve', 'tool', 'answer'].includes(step.phase) && typeof step.status === 'string' && ['completed', 'failed'].includes(step.status) && duration(step.duration_ms))
    result.run = {
      id: run.id, status: run.status as AgentRun['status'], duration_ms: run.duration_ms,
      steps: steps.map(step => ({ phase: step.phase, status: step.status, duration_ms: step.duration_ms })),
    }
    const task = readCampusTask(run.task)
    if (task) result.run.task = task
  }
  return result
}
