import type { Source } from './api'
import type { ConversationMessage } from './agent-diagnostics'

export interface ProjectInfo { id: string; name: string }
export interface ProjectSelection { id: string; files: string[] }
export interface ProjectStatus { available: boolean; changes_available?: boolean; project: ProjectInfo | null; limits: { max_files: number; max_context_chars: number } }
export interface ProjectEntry { name: string; path: string; kind: 'file' | 'directory'; size_bytes?: number; readable?: boolean }
export interface ProjectListing { project: ProjectInfo; path: string; entries: ProjectEntry[]; truncated: boolean }
export interface ProjectExcerpt { path: string; text: string; start_line: number; end_line: number; size_bytes: number; truncated: boolean; excerpt_sha256: string }

export function canProposeProjectFile(excerpt: ProjectExcerpt | null): boolean {
  return Boolean(excerpt?.path && excerpt.truncated === false)
}

export function projectSuffix(files: string[]): string { return `[项目文件] ${files.join('、')}` }
export function projectSourceLabel(source: Source): string {
  const path = source.path || source.title || source.source || ''
  return source.start_line ? `${path}:${source.start_line}${source.end_line && source.end_line !== source.start_line ? `–${source.end_line}` : ''}` : path
}

/** Relative names alone cannot identify a root. Only the original live grant can be retried. */
export function projectRegeneration(user: ConversationMessage, assistant: ConversationMessage, current: ProjectSelection | null): { project?: ProjectSelection; missingProject: boolean } {
  if (user.project?.files.length) {
    return current?.id === user.project.id
      ? { project: { id: user.project.id, files: [...user.project.files] }, missingProject: false }
      : { missingProject: true }
  }
  const hasMarker = /(?:^|\n)\[项目文件\] /.test(user.text)
  return { missingProject: hasMarker || Boolean(assistant.sources?.some(source => source.kind === 'project')) }
}
