import type { WorkspaceModel } from './model-providers'
import type { ProjectInfo, ProjectStatus } from './project-files'
export type { WorkspaceModel } from './model-providers'
export type AppearanceMode = 'light' | 'dark' | 'system'
// Only app-native local project apply/revert/keep operations.
export type ProjectPermission = 'read_only' | 'confirm'

export interface DesktopWorkspace {
  model: WorkspaceModel
  conversationId: string
  clientId: string
  localModel: string
  appearance: AppearanceMode
  accentColor: string
  webSearch: boolean
  reasoning: import('./reasoning').ReasoningPreference | 'fast'
  projectPermission: ProjectPermission
  onboardingDone: boolean
}

export interface DesktopInfo {
  version: string
  dataPath: string
}

export type ProjectChangeAction = 'apply' | 'revert' | 'keep'
export type ProjectChangeState = 'pending' | 'applied' | 'reverted' | 'kept' | 'conflict' | 'failed' | 'uncertain' | 'cancelled'
export interface ProjectChangeReceipt {
  operation_id: string
  project_id: string
  subject_id: string
  proposal_id: string
  recovery_id: string
  action: ProjectChangeAction
  state: ProjectChangeState
  path: string
  summary: string
  created_at: string
  can_revert: boolean
  error_code?: string
  error_status?: number
}
export type ProjectChangeResult = ProjectChangeReceipt
export interface ProjectRecoveryArchive { archive_id: string; path: string; summary: string; created_at: string; size_bytes: number }
export interface ProjectChangeList { available: boolean; records: ProjectChangeReceipt[]; archives?: ProjectRecoveryArchive[] }
export interface ProjectRecoveryOriginal { text: string; bom: boolean; newline: 'none' | 'lf' | 'crlf' | 'cr' | 'mixed' }

export interface CampusDesktop {
  isDesktop: true
  getInfo(): Promise<DesktopInfo>
  loadWorkspace(): Promise<DesktopWorkspace>
  saveWorkspace(state: DesktopWorkspace): Promise<void>
  setProjectPermission(mode: ProjectPermission): Promise<{ projectPermission: ProjectPermission; persisted: boolean }>
  openDataFolder(): Promise<void>
  openBaike(query: string): Promise<void>
  openOllamaDownload(): Promise<void>
  restart(): Promise<void>
  saveBackup(name: string, bytes: Uint8Array): Promise<{ saved: boolean; path?: string }>
  saveExport(name: string, bytes: Uint8Array): Promise<{ saved: boolean; path?: string }>
  pickBackup(): Promise<{ picked: boolean; name?: string; bytes?: Uint8Array }>
  pickProject(): Promise<{ picked: boolean; available?: boolean; changes_available?: boolean; project?: ProjectInfo; limits?: ProjectStatus['limits'] }>
  changeProjectFile(projectId: string, subjectId: string, action: ProjectChangeAction): Promise<ProjectChangeResult>
  projectChangeStatus(projectId: string, operationId: string): Promise<ProjectChangeReceipt>
  projectChanges(projectId: string): Promise<ProjectChangeList>
  projectRecoveryOriginal(projectId: string, recoveryId: string): Promise<ProjectRecoveryOriginal>
  readLog(): Promise<{ available: boolean; path: string; text: string }>
  openExternal(url: string): Promise<void>
}

declare global {
  interface Window {
    campusDesktop?: CampusDesktop
  }
}

export const desktop = window.campusDesktop?.isDesktop ? window.campusDesktop : undefined
