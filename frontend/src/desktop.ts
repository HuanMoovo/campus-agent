export type WorkspaceModel = 'auto' | 'qwen3' | 'deepseek' | 'ollama'
export type AppearanceMode = 'light' | 'dark' | 'system'

export interface DesktopWorkspace {
  model: WorkspaceModel
  conversationId: string
  clientId: string
  localModel: string
  appearance: AppearanceMode
  accentColor: string
  webSearch: boolean
}

export interface DesktopInfo {
  version: string
  dataPath: string
}

export interface CampusDesktop {
  isDesktop: true
  getInfo(): Promise<DesktopInfo>
  loadWorkspace(): Promise<DesktopWorkspace>
  saveWorkspace(state: DesktopWorkspace): Promise<void>
  openDataFolder(): Promise<void>
  openBaike(query: string): Promise<void>
  openOllamaDownload(): Promise<void>
  restart(): Promise<void>
  saveBackup(name: string, bytes: Uint8Array): Promise<{ saved: boolean; path?: string }>
  saveExport(name: string, bytes: Uint8Array): Promise<{ saved: boolean; path?: string }>
  pickBackup(): Promise<{ picked: boolean; name?: string; bytes?: Uint8Array }>
  readLog(): Promise<{ available: boolean; path: string; text: string }>
  openExternal(url: string): Promise<void>
}

declare global {
  interface Window {
    campusDesktop?: CampusDesktop
  }
}

export const desktop = window.campusDesktop?.isDesktop ? window.campusDesktop : undefined
