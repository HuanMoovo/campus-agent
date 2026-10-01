<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowRight, ChatLineRound, Check, CircleClose, Clock, Connection, Delete, Document, FolderOpened,
  Grid, Link, Plus, Refresh, Search, Setting, Upload, Download,
} from '@element-plus/icons-vue'
import { api, ChatStreamError, chatStream, type CampusSource, type ConversationSummary, type CuratedPlugin, type Health, type KnowledgeDocument, type LocalModels, type ModelConfig, type ModelDownload, type Plugin, type RepairRecord, type Source, type WebStatus } from './api'
import { useWorkspaceStore, type Model, type View } from './store'
import { desktop, type DesktopInfo } from './desktop'
import mensLogo from './assets/mens.png'
import AppearanceSettings from './components/AppearanceSettings.vue'
import { applyAppearance } from './appearance'
import { version as frontendVersion } from '../package.json'

type Message = { role: 'user' | 'assistant'; text: string; sources?: Source[]; tools?: string[]; demo?: boolean; error?: boolean; streaming?: boolean; stopped?: boolean; note?: string }
type ServiceKey = 'grades' | 'schedule' | 'credits' | 'classrooms' | 'repair' | 'notices' | 'library' | 'dining' | 'shuttle'

const workspace = useWorkspaceStore()
const desktopInfo = ref<DesktopInfo | null>(null)
const desktopError = ref('')
const desktopAction = ref('')
const nav: { key: View; label: string; icon: typeof ChatLineRound; section: string }[] = [
  { key: 'chat', label: '智能问答', icon: ChatLineRound, section: '工作区' },
  { key: 'services', label: '校园服务', icon: Grid, section: '工作区' },
  { key: 'knowledge', label: '知识库', icon: FolderOpened, section: '管理' },
  { key: 'plugins', label: '插件', icon: Connection, section: '管理' },
  { key: 'settings', label: '设置', icon: Setting, section: '管理' },
]
const viewLabel = computed(() => nav.find(item => item.key === workspace.view)?.label || '')
const modelLabel = computed(() => workspace.model === 'ollama' ? currentLocalModel.value || '本地模型' : ({ auto: '自动路由', qwen3: 'Qwen3', deepseek: 'DeepSeek' })[workspace.model])
const mobileNavOpen = ref(false)
const adminToken = ref(desktop ? '' : sessionStorage.getItem('campus-agent-admin-token') || '')
const health = ref<Health | null>(null)
const healthBusy = ref(false)
const healthError = ref('')
const historyError = ref('')
const historyBusy = ref(false)
const healthLabel = computed(() => healthBusy.value ? '检查中' : health.value?.status === 'ok' ? '后端已连接' : '后端未连接')

const messages = ref<Message[]>([])
const prompt = ref('')
const chatBusy = ref(false)
const chatAbort = ref<AbortController | null>(null)
const conversations = ref<ConversationSummary[]>([])
const conversationsBusy = ref(false)
const conversationsError = ref('')
const historyOpen = ref(typeof window !== 'undefined' && window.matchMedia('(min-width: 900px)').matches)
const streamingMessage = computed(() => {
  const last = messages.value[messages.value.length - 1]
  return last && last.role === 'assistant' && last.streaming ? last : null
})
const chatEnd = ref<HTMLElement | null>(null)
const chatSuggestions = ['补办校园一卡通需要什么材料？', '查询我的本周课表', '学校的报修流程是什么？']

const activeService = ref<ServiceKey>('grades')
const serviceBusy = ref(false)
const serviceResult = ref<unknown>(null)
const serviceError = ref('')
const classroom = ref({ building: '', minSeats: 0 })
const repair = ref({ location: '', description: '', contact: '' })
const repairList = ref<RepairRecord[]>([])
const repairListBusy = ref(false)
const repairListError = ref('')
const repairListDemo = ref(true)
const serviceNames: Record<ServiceKey, string> = {
  grades: '成绩查询', schedule: '课表查询', credits: '学分统计', classrooms: '空教室查询', repair: '报修申请',
  notices: '校园公告', library: '图书馆', dining: '餐饮', shuttle: '校车',
}

const documents = ref<KnowledgeDocument[]>([])
const docsBusy = ref(false)
const docsError = ref('')
const docAction = ref('')
const uploadInput = ref<HTMLInputElement | null>(null)

const plugins = ref<Plugin[]>([])
const pluginsBusy = ref(false)
const pluginsError = ref('')
const pluginAction = ref('')
const pluginSource = ref('')
const testPlugin = ref<Plugin | null>(null)
const testParameters = ref('{}')
const testResult = ref<unknown>(null)
const baikeUrl = ref('')
const testError = ref('')
const testBusy = ref(false)
const curatedPlugins = ref<CuratedPlugin[]>([])
const catalogError = ref('')
const modelConfig = ref<ModelConfig | null>(null)
const provider = ref<'qwen' | 'deepseek'>('qwen')
const modelForm = ref({ api_key: '', base_url: '', model: '' })
const modelError = ref('')
const modelAction = ref('')
const localModels = ref<LocalModels | null>(null)
const localError = ref('')
const localBusy = ref(false)
const currentLocalModel = computed(() => workspace.localModel || modelConfig.value?.ollama.model || '')
const installedLocalModel = computed(() => localModels.value?.installed.some(item => item.name === currentLocalModel.value))
const chatModel = computed(() => workspace.model === 'ollama' ? `local:${currentLocalModel.value}` : workspace.model)
const localChatProblem = computed(() => {
  if (workspace.model !== 'ollama') return ''
  if (localBusy.value) return '正在检测本地模型…'
  if (localError.value) return localError.value
  if (!localModels.value?.running) return 'Ollama 未启动或无法连接'
  if (!currentLocalModel.value) return '尚未选择本地模型'
  if (!installedLocalModel.value) return `本地模型 ${currentLocalModel.value} 未安装`
  return ''
})
const selectedLocalModel = ref('')
const selectedMirror = ref('ollama')
const download = ref<ModelDownload | null>(null)
const downloadStarting = ref(false)
const downloadActive = computed(() => downloadStarting.value || Boolean(download.value && !['completed', 'failed', 'cancelled'].includes(download.value.status)))
const downloadProgress = computed(() => Math.min(100, Math.max(0, Math.round((download.value?.progress || 0) * 100))))
const campusSources = ref<CampusSource[]>([])
const campusKind = ref('grades')
const campusForm = ref({ url: '', result_path: '', token: '' })
const campusError = ref('')
const campusAction = ref('')
const activeCampusSource = computed(() => campusSources.value.find(item => item.kind === campusKind.value))
const backupAction = ref('')
const backupError = ref('')
const backupInfo = ref('')
const backupInput = ref<HTMLInputElement | null>(null)
const logText = ref('')
const logBusy = ref(false)
const logError = ref('')
const updateBusy = ref(false)
const updateInfo = ref('')
const updateError = ref('')
const updateUrl = ref('')
const webStatus = ref<WebStatus | null>(null)
const webError = ref('')
const webSaved = ref('')
const webSaving = ref(false)
const webForm = ref({ enabled: false, provider: 'auto', apiKey: '', maxResults: 5, fetchPages: 2 })
const webAvailable = computed(() => Boolean(webStatus.value?.enabled && webStatus.value?.available))
const webSwitch = computed({
  get: () => workspace.webSearch,
  set: value => workspace.setWebSearch(Boolean(value)),
})
const webToggleHint = computed(() => webAvailable.value
  ? `开启后会把问题发送到${webStatus.value?.resolved_provider === 'bing' ? ' Bing 网页搜索' : webStatus.value?.resolved_provider === 'tavily' ? ' Tavily' : ' 博查'}并引用网页结果`
  : '管理员尚未启用联网搜索（可在设置中开启）')
let downloadTimer: ReturnType<typeof setTimeout> | undefined

function fileSize(bytes?: number) {
  if (!bytes) return ''
  return `${(bytes / 1_073_741_824).toFixed(1)} GB`
}

watch(provider, () => copyProviderConfig())
watch(campusKind, () => copyCampusSource())

function copyCampusSource() {
  const item = activeCampusSource.value
  campusForm.value = { url: item?.url || '', result_path: item?.result_path || '', token: '' }
}

async function loadCampusSources() {
  campusError.value = ''
  try { campusSources.value = await api.campusSources(); copyCampusSource() }
  catch (error) { campusError.value = friendlyError(error) }
}

async function saveCampusSource() {
  if (campusAction.value) return
  campusAction.value = 'save'
  campusError.value = ''
  try {
    await api.saveCampusSource(campusKind.value, {
      url: campusForm.value.url.trim(), result_path: campusForm.value.result_path.trim(),
      ...(campusForm.value.token.trim() ? { token: campusForm.value.token.trim() } : {}),
    })
    await loadCampusSources()
    await loadHealth()
    ElMessage.success('校园数据接口已保存')
  } catch (error) { campusError.value = friendlyError(error) }
  finally { campusAction.value = '' }
}

async function removeCampusSource() {
  if (campusAction.value) return
  campusAction.value = 'remove'
  campusError.value = ''
  try {
    await api.removeCampusSource(campusKind.value)
    await loadCampusSources()
    await loadHealth()
    ElMessage.success('已恢复演示数据')
  } catch (error) { campusError.value = friendlyError(error) }
  finally { campusAction.value = '' }
}

function copyProviderConfig() {
  const current = modelConfig.value?.providers[provider.value]
  modelForm.value = { api_key: '', base_url: current?.base_url || '', model: current?.model || '' }
}

async function loadModelConfig() {
  modelError.value = ''
  try { modelConfig.value = await api.modelConfig(); copyProviderConfig() }
  catch (error) { modelError.value = friendlyError(error) }
}

async function saveModelConfig(clear = false) {
  if (modelAction.value) return
  modelAction.value = 'save'
  modelError.value = ''
  try {
    const values = {
      api_key: clear ? undefined : modelForm.value.api_key.trim() || undefined,
      clear_api_key: clear,
      base_url: modelForm.value.base_url.trim(),
      model: modelForm.value.model.trim(),
    }
    modelConfig.value = await api.saveModelConfig(provider.value, values)
    modelForm.value.api_key = ''
    copyProviderConfig()
    await loadHealth()
    ElMessage.success(clear ? 'API Key 已清除' : '模型配置已保存')
  } catch (error) { modelError.value = friendlyError(error) }
  finally { modelAction.value = '' }
}

async function testModel() {
  if (modelAction.value) return
  modelAction.value = 'test'
  modelError.value = ''
  try {
    const result = await api.testModel(provider.value)
    if (!result.ok) throw new Error(result.error || '连接测试失败')
    ElMessage.success('模型连接成功')
  } catch (error) { modelError.value = friendlyError(error) }
  finally { modelAction.value = '' }
}

async function loadLocalModels() {
  if (localBusy.value) return
  localBusy.value = true
  localError.value = ''
  try {
    localModels.value = await api.localModels()
    if (!selectedLocalModel.value) selectedLocalModel.value = localModels.value.catalog[0]?.id || ''
    if (!localModels.value.sources.some(item => item.id === selectedMirror.value)) selectedMirror.value = localModels.value.sources[0]?.id || 'ollama'
  } catch (error) { localError.value = friendlyError(error) }
  finally { localBusy.value = false }
}

async function pollDownload() {
  if (!download.value) return
  try {
    download.value = await api.localModelDownload(download.value.id)
    if (download.value.status === 'completed' || download.value.status === 'success') {
      ElMessage.success('模型下载完成')
      await loadLocalModels()
      return
    }
    if (download.value.status === 'cancelled') return
    if (download.value.status === 'failed' || download.value.status === 'error') {
      localError.value = download.value.error || '模型下载失败'
      return
    }
    downloadTimer = setTimeout(pollDownload, 1000)
  } catch (error) { localError.value = friendlyError(error) }
}

async function downloadLocalModel() {
  if (!selectedLocalModel.value || !localModels.value?.running || downloadActive.value) return
  downloadStarting.value = true
  localError.value = ''
  try {
    const result = await api.pullLocalModel(selectedLocalModel.value, selectedMirror.value)
    download.value = result
    if (downloadTimer) clearTimeout(downloadTimer)
    downloadTimer = setTimeout(pollDownload, 500)
  } catch (error) { localError.value = friendlyError(error) }
  finally { downloadStarting.value = false }
}

async function cancelDownload() {
  if (!download.value) return
  try { download.value = await api.cancelLocalModelDownload(download.value.id) }
  catch (error) { localError.value = friendlyError(error) }
}

async function testCampusSource() {
  if (campusAction.value) return
  campusAction.value = 'test'
  campusError.value = ''
  try {
    if (campusKind.value === 'repairs') throw new Error('报修接口属于提交操作，请保存后在校园服务页提交真实工单验证。')
    await api.campusData(campusKind.value)
    ElMessage.success('校园数据接口连接成功')
  } catch (error) { campusError.value = friendlyError(error) }
  finally { campusAction.value = '' }
}

async function selectInstalledModel(name: string) {
  if (chatBusy.value) return
  workspace.setLocalModel(name)
  ElMessage.success(`已选择 ${name}`)
}

function selectChatModel(value: string) {
  if (chatBusy.value) return
  if (value.startsWith('local:')) workspace.setLocalModel(value.slice(6))
  else if (value === 'auto' || value === 'qwen3' || value === 'deepseek') workspace.setModel(value)
}

function scrollChat() {
  nextTick(() => chatEnd.value?.scrollIntoView({ behavior: 'smooth', block: 'end' }))
}

function friendlyError(error: unknown) {
  return error instanceof Error ? error.message : '操作失败，请稍后重试。'
}

function selectView(view: View) {
  workspace.view = view
  mobileNavOpen.value = false
  if (view === 'knowledge') void loadDocuments()
  if (view === 'plugins') { void loadPlugins(); void loadCuratedPlugins() }
  if (view === 'chat') { void loadLocalModels(); void loadConversations() }
  if (view === 'settings') { void loadModelConfig(); void loadLocalModels(); void loadCampusSources() }
}

function newConversation() {
  if (!workspace.ready || chatBusy.value || historyBusy.value) return
  messages.value = []
  workspace.setConversationId('')
  prompt.value = ''
  historyError.value = ''
}

function chatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const time = `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  return date.toDateString() === new Date().toDateString() ? time : `${date.getMonth() + 1}/${date.getDate()} ${time}`
}

async function loadConversations() {
  if (!workspace.ready) return
  conversationsBusy.value = true
  conversationsError.value = ''
  try {
    conversations.value = await api.conversations(workspace.clientId)
  } catch (error) {
    conversationsError.value = `无法读取历史对话：${friendlyError(error)}`
  } finally {
    conversationsBusy.value = false
  }
}

async function openConversation(id: string) {
  if (chatBusy.value || historyBusy.value || id === workspace.conversationId) return
  workspace.setConversationId(id)
  messages.value = []
  historyError.value = ''
  await restoreConversation()
}

async function deleteConversation(item: ConversationSummary) {
  if (chatBusy.value) return
  try {
    await ElMessageBox.confirm(`删除“${item.title}”后无法恢复，确定删除？`, '删除历史对话', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
  } catch { return }
  try {
    await api.deleteConversation(item.id, workspace.clientId)
    if (item.id === workspace.conversationId) newConversation()
    await loadConversations()
  } catch (error) {
    ElMessage.error(friendlyError(error))
  }
}

async function clearConversations() {
  if (chatBusy.value || !conversations.value.length) return
  try {
    await ElMessageBox.confirm(`将删除全部 ${conversations.value.length} 条历史对话，且无法恢复。确定清空？`, '清空历史对话', { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' })
  } catch { return }
  try {
    await api.clearConversations(workspace.clientId)
    newConversation()
    await loadConversations()
  } catch (error) {
    ElMessage.error(friendlyError(error))
  }
}

async function stopChat() {
  chatAbort.value?.abort()
}

async function exportBackup() {
  if (backupAction.value) return
  backupAction.value = 'export'
  backupError.value = ''
  backupInfo.value = ''
  try {
    const blob = await api.exportBackup()
    const name = `mens-backup-${new Date().toISOString().slice(0, 10)}.zip`
    if (desktop) {
      const bytes = new Uint8Array(await blob.arrayBuffer())
      const result = await desktop.saveBackup(name, bytes)
      backupInfo.value = result.saved ? `备份已保存：${result.path || name}` : '已取消导出。'
    } else {
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = name
      link.click()
      URL.revokeObjectURL(url)
      backupInfo.value = `已开始下载 ${name}。`
    }
  } catch (error) {
    backupError.value = `导出失败：${friendlyError(error)}`
  } finally {
    backupAction.value = ''
  }
}

async function importBackup() {
  if (backupAction.value) return
  try {
    await ElMessageBox.confirm('导入会覆盖当前知识库、对话记录和接口配置，且无法撤销。确定继续？', '导入备份', { type: 'warning', confirmButtonText: '导入', cancelButtonText: '取消' })
  } catch { return }
  if (!desktop) { backupInput.value?.click(); return }
  backupAction.value = 'import'
  backupError.value = ''
  backupInfo.value = ''
  try {
    const picked = await desktop.pickBackup()
    if (!picked.picked || !picked.bytes) return
    await finishImport(picked.name || 'mens-backup.zip', picked.bytes)
  } catch (error) {
    backupError.value = `导入失败：${friendlyError(error)}`
  } finally {
    backupAction.value = ''
  }
}

async function onBackupFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  backupAction.value = 'import'
  backupError.value = ''
  backupInfo.value = ''
  try {
    await finishImport(file.name, new Uint8Array(await file.arrayBuffer()))
  } catch (error) {
    backupError.value = `导入失败：${friendlyError(error)}`
  } finally {
    backupAction.value = ''
  }
}

async function finishImport(name: string, bytes: Uint8Array) {
  const result = await api.importBackup(bytes, name)
  backupInfo.value = `已恢复：${result.restored.join('、') || '无'}${result.failed?.length ? `；${result.failed.join('、')} 未能写入` : ''}。`
  if (!result.restart_required) return
  backupInfo.value += '重启应用后完全生效。'
  if (!desktop) return
  try {
    await ElMessageBox.confirm('备份已导入，重启应用后完全生效。现在重启？', '导入完成', { type: 'info', confirmButtonText: '重启应用', cancelButtonText: '稍后' })
    await restartDesktop()
  } catch { /* 用户选择稍后重启 */ }
}

async function loadLog() {
  if (!desktop || logBusy.value) return
  logBusy.value = true
  logError.value = ''
  try {
    const result = await desktop.readLog()
    logText.value = result.available ? (result.text || '日志文件为空。') : ''
    if (!result.available) logError.value = '尚未生成日志文件，运行一段时间后再试。'
  } catch (error) {
    logError.value = `无法读取日志：${friendlyError(error)}`
  } finally {
    logBusy.value = false
  }
}

async function checkUpdates() {
  if (updateBusy.value) return
  updateBusy.value = true
  updateError.value = ''
  updateInfo.value = ''
  updateUrl.value = ''
  try {
    const result = await api.checkUpdate()
    updateInfo.value = [result.message, result.notes ? `更新说明：${result.notes}` : ''].filter(Boolean).join(' ')
    if (result.error) updateError.value = result.error
    if (result.update_available && result.url) updateUrl.value = result.url
  } catch (error) {
    updateError.value = `检查更新失败：${friendlyError(error)}`
  } finally {
    updateBusy.value = false
  }
}

async function openUpdateUrl() {
  if (!updateUrl.value) return
  if (desktop) {
    try { await desktop.openExternal(updateUrl.value) }
    catch (error) { updateError.value = `无法打开下载页：${friendlyError(error)}` }
    return
  }
  window.open(updateUrl.value, '_blank', 'noopener,noreferrer')
}

function sourceHost(url?: string) {
  try { return new URL(url || '').host } catch { return url || '' }
}

async function openSourceUrl(url?: string) {
  if (!url) return
  if (desktop) {
    try { await desktop.openExternal(url) }
    catch (error) { ElMessage.warning(`无法打开链接：${friendlyError(error)}`) }
    return
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}

async function loadWebStatus() {
  try {
    const status = await api.webStatus()
    webStatus.value = status
    webForm.value = {
      enabled: status.enabled,
      provider: status.provider,
      apiKey: '',
      maxResults: status.max_results,
      fetchPages: status.fetch_pages,
    }
  } catch (error) {
    webStatus.value = null
  }
}

async function saveWebConfig() {
  if (webSaving.value) return
  webSaving.value = true
  webError.value = ''
  webSaved.value = ''
  try {
    const payload: { enabled: boolean; provider: string; max_results: number; fetch_pages: number; api_key?: string } = {
      enabled: webForm.value.enabled,
      provider: webForm.value.provider,
      max_results: webForm.value.maxResults,
      fetch_pages: webForm.value.fetchPages,
    }
    if (webForm.value.apiKey.trim()) payload.api_key = webForm.value.apiKey.trim()
    const status = await api.saveWebConfig(payload)
    webStatus.value = status
    webForm.value.apiKey = ''
    webSaved.value = status.enabled
      ? `已保存：${status.providers.find(item => item.id === status.provider)?.label || status.provider}${status.available ? '' : '（缺少 API Key，暂不可用）'}。`
      : '已关闭联网搜索。'
    if (!status.enabled || !status.available) workspace.setWebSearch(false)
  } catch (error) {
    webError.value = `保存失败：${friendlyError(error)}`
  } finally {
    webSaving.value = false
  }
}

async function loadHealth() {
  healthBusy.value = true
  healthError.value = ''
  try { health.value = await api.health() }
  catch (error) { health.value = null; healthError.value = friendlyError(error) }
  finally { healthBusy.value = false }
}

async function restoreConversation() {
  if (!workspace.conversationId || historyBusy.value) return
  historyBusy.value = true
  historyError.value = ''
  try {
    const result = await api.conversation(workspace.conversationId)
    messages.value = result.messages.map(message => ({ role: message.role, text: message.content, sources: message.sources, tools: message.tool_calls?.map(call => call.name), demo: message.mode === 'demo', stopped: Boolean(message.partial) }))
    scrollChat()
  } catch (error) { historyError.value = `${friendlyError(error)} 可以重试恢复或开始新对话。` }
  finally { historyBusy.value = false }
}

async function sendChat(value = prompt.value) {
  const text = value.trim()
  if (!workspace.ready || !text || chatBusy.value || historyBusy.value || historyError.value) return
  if (localChatProblem.value) { ElMessage.warning(localChatProblem.value); return }
  const useWeb = workspace.webSearch && webAvailable.value
  messages.value.push({ role: 'user', text })
  prompt.value = ''
  const index = messages.value.push({ role: 'assistant', text: '', streaming: true }) - 1
  const assistant = messages.value[index]
  chatBusy.value = true
  const controller = new AbortController()
  chatAbort.value = controller
  scrollChat()
  try {
    const answer = await chatStream(
      { message: text, conversationId: workspace.conversationId, model: workspace.model, localModel: currentLocalModel.value, clientId: workspace.clientId, web: useWeb },
      {
        onMeta: id => { if (id) workspace.setConversationId(id) },
        onDelta: chunk => { assistant.text += chunk; scrollChat() },
      },
      controller.signal,
    )
    if (answer.conversation_id) workspace.setConversationId(answer.conversation_id)
    if (answer.answer) assistant.text = answer.answer
    assistant.sources = answer.sources || []
    assistant.tools = answer.tool_calls?.map(call => call.name)
    assistant.demo = answer.mode === 'demo'
    const web = answer.web || {}
    if (useWeb && web.error) assistant.note = `联网检索未完成：${web.error}`
    else if (assistant.sources.some(source => source.kind === 'web')) assistant.note = `已联网检索（${web.fetched_at || '刚刚'}）`
  } catch (error) {
    if (controller.signal.aborted) {
      assistant.stopped = true
      if (!assistant.text.trim()) {
        assistant.text = '已停止生成。'
        if (!prompt.value.trim()) prompt.value = text
      }
    } else if (error instanceof ChatStreamError) {
      assistant.error = true
      assistant.note = error.message
      if (error.partial) assistant.text = error.partial
      if (!assistant.text.trim() && !prompt.value.trim()) prompt.value = text
    } else {
      const message = friendlyError(error)
      assistant.error = true
      if (assistant.text.trim()) assistant.note = message
      else {
        assistant.text = message
        if (!prompt.value.trim()) prompt.value = text
      }
    }
  } finally {
    messages.value[index].streaming = false
    chatBusy.value = false
    chatAbort.value = null
    scrollChat()
    void loadConversations()
  }
}

function onChatKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void sendChat()
  }
}

function selectService(key: ServiceKey) {
  if (serviceBusy.value) return
  activeService.value = key
  serviceResult.value = null
  serviceError.value = ''
  if (key === 'repair') void loadRepairs()
}

async function loadRepairs() {
  if (repairListBusy.value) return
  repairListBusy.value = true
  repairListError.value = ''
  try {
    const result = await api.repairs()
    repairList.value = result.items
    repairListDemo.value = result.demo
  } catch (error) {
    repairList.value = []
    repairListError.value = friendlyError(error)
  } finally {
    repairListBusy.value = false
  }
}

async function runService() {
  if (serviceBusy.value) return
  serviceError.value = ''
  serviceResult.value = null
  if (activeService.value === 'repair' && (repair.value.location.trim().length < 2 || repair.value.description.trim().length < 5 || repair.value.contact.trim().length < 2)) {
    serviceError.value = '地点和联系方式至少 2 个字符，问题描述至少 5 个字符。'
    return
  }
  serviceBusy.value = true
  try {
    if (activeService.value === 'grades') serviceResult.value = await api.grades()
    else if (activeService.value === 'schedule') serviceResult.value = await api.schedule()
    else if (activeService.value === 'credits') serviceResult.value = await api.credits()
    else if (activeService.value === 'classrooms') serviceResult.value = await api.classrooms(classroom.value.building.trim(), classroom.value.minSeats || 0)
    else if (activeService.value === 'repair') serviceResult.value = await api.repair(repair.value)
    else serviceResult.value = await api.campusData(activeService.value)
    if (activeService.value === 'repair') {
      ElMessage.success(serviceIsDemo.value ? '演示报修单已保存在后端' : '报修申请已提交')
      void loadRepairs()
    }
  } catch (error) {
    serviceError.value = friendlyError(error)
  } finally {
    serviceBusy.value = false
  }
}

const resultRows = computed<Record<string, unknown>[]>(() => {
  const value = serviceResult.value as Record<string, unknown> | unknown[] | null
  if (!value) return []
  if (Array.isArray(value)) return value.map(item => typeof item === 'object' && item !== null ? item as Record<string, unknown> : { 结果: item })
  const list = value.items || value.results || value.data || value.grades || value.schedule || value.classrooms
  if (Array.isArray(list)) return list as Record<string, unknown>[]
  return [Object.fromEntries(Object.entries(value).filter(([key]) => key !== 'demo'))]
})
const serviceIsDemo = computed(() => Boolean((serviceResult.value as { demo?: boolean } | null)?.demo))
const resultColumns = computed(() => [...new Set(resultRows.value.flatMap(row => Object.keys(row)))])
const columnLabels: Record<string, string> = { course: '课程', semester: '学期', credits: '学分', score: '成绩', weekday: '星期', time: '时间', room: '教室', building: '教学楼', seats: '座位数', available: '空闲', required: '要求学分', earned: '已获学分', id: '单号', status: '状态' }
function cellText(value: unknown) {
  if (value == null) return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

async function loadDocuments() {
  docsBusy.value = true
  docsError.value = ''
  try { documents.value = await api.documents() }
  catch (error) { docsError.value = friendlyError(error) }
  finally { docsBusy.value = false }
}

function validDocument(file: File) {
  if (file.size > 5_000_000) {
    ElMessage.error('文件超过 5 MB。')
    return false
  }
  if (!/\.(pdf|md|txt|docx)$/i.test(file.name)) {
    ElMessage.error('仅支持 PDF、Markdown、TXT 和 Word (.docx) 文件。')
    return false
  }
  return true
}

async function onUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || docAction.value) { input.value = ''; return }
  if (!validDocument(file)) { input.value = ''; return }
  docAction.value = 'upload'
  try {
    const result = await api.uploadDocument(file)
    await loadDocuments()
    if (result.warning) ElMessage.warning(result.warning)
    else ElMessage.success('文档已上传')
  } catch (error) { ElMessage.error(friendlyError(error)) }
  finally { docAction.value = ''; input.value = '' }
}

async function onReplace(id: string, event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || docAction.value) { input.value = ''; return }
  if (!validDocument(file)) { input.value = ''; return }
  docAction.value = id
  try {
    const result = await api.updateDocument(id, file)
    await loadDocuments()
    if (result.warning) ElMessage.warning(result.warning)
    else ElMessage.success('文档已更新')
  } catch (error) { ElMessage.error(friendlyError(error)) }
  finally { docAction.value = ''; input.value = '' }
}

async function deleteDocument(item: KnowledgeDocument) {
  if (docAction.value) return
  try { await ElMessageBox.confirm(`确定删除「${item.filename}」？`, '删除文档', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }) }
  catch { return }
  docAction.value = item.id
  try {
    const result = await api.deleteDocument(item.id)
    documents.value = documents.value.filter(doc => doc.id !== item.id)
    if (result.warning) ElMessage.warning(result.warning)
    else ElMessage.success('文档已删除')
  } catch (error) { ElMessage.error(friendlyError(error)) }
  finally { docAction.value = '' }
}

async function reindex() {
  if (docAction.value) return
  docAction.value = 'reindex'
  try {
    const result = await api.reindex()
    await loadDocuments()
    ElMessage.success(health.value?.rag_enabled ? `向量索引已重建，共处理 ${result.indexed} 份文档` : `当前使用关键词检索，共 ${result.indexed} 份文档；向量检索未启用`)
  } catch (error) { ElMessage.error(friendlyError(error)) }
  finally { docAction.value = '' }
}

async function loadPlugins() {
  pluginsBusy.value = true
  pluginsError.value = ''
  try { plugins.value = await api.plugins() }
  catch (error) { pluginsError.value = friendlyError(error) }
  finally { pluginsBusy.value = false }
}

async function loadCuratedPlugins() {
  catalogError.value = ''
  try { curatedPlugins.value = await api.curatedPlugins() }
  catch (error) { catalogError.value = friendlyError(error) }
}

async function installCuratedPlugin(id: string) {
  if (pluginAction.value) return
  pluginAction.value = id
  try {
    await api.installCuratedPlugin(id)
    await loadPlugins()
    await loadCuratedPlugins()
    ElMessage.success('插件已安装')
  } catch (error) { ElMessage.error(friendlyError(error)) }
  finally { pluginAction.value = '' }
}

async function installPlugin() {
  const source = pluginSource.value.trim()
  if (!source || pluginAction.value) return
  pluginAction.value = 'install'
  try {
    await api.installPlugin(source)
    await loadPlugins()
    pluginSource.value = ''
    ElMessage.success('插件已安装')
  } catch (error) { ElMessage.error(friendlyError(error)) }
  finally { pluginAction.value = '' }
}

async function togglePlugin(item: Plugin, enabled: boolean) {
  if (pluginAction.value || testBusy.value) return
  pluginAction.value = item.id
  try {
    await api.togglePlugin(item.id, enabled)
    item.enabled = enabled
    ElMessage.success(enabled ? '插件已启用' : '插件已停用')
  } catch (error) { ElMessage.error(friendlyError(error)) }
  finally { pluginAction.value = '' }
}

async function removePlugin(item: Plugin) {
  if (pluginAction.value || testBusy.value) return
  try { await ElMessageBox.confirm(`确定卸载「${item.name}」？`, '卸载插件', { type: 'warning', confirmButtonText: '卸载', cancelButtonText: '取消' }) }
  catch { return }
  pluginAction.value = item.id
  try {
    await api.removePlugin(item.id)
    plugins.value = plugins.value.filter(plugin => plugin.id !== item.id)
    await loadCuratedPlugins()
    if (testPlugin.value?.id === item.id) testPlugin.value = null
    ElMessage.success('插件已卸载')
  } catch (error) { ElMessage.error(friendlyError(error)) }
  finally { pluginAction.value = '' }
}

function openPluginTest(plugin: Plugin) {
  if (testBusy.value) return
  testPlugin.value = plugin
  testParameters.value = plugin.name === 'baidu_baike_search' ? '{"bk_key":"人工智能"}' : '{}'
  testResult.value = null
  baikeUrl.value = ''
  testError.value = ''
}

async function invokePlugin() {
  if (!testPlugin.value || !testPlugin.value.enabled || testBusy.value) return
  testError.value = ''
  testResult.value = null
  baikeUrl.value = ''
  let parameters: unknown
  try { parameters = JSON.parse(testParameters.value) }
  catch { testError.value = '参数必须是有效的 JSON 对象。'; return }
  if (!parameters || Array.isArray(parameters) || typeof parameters !== 'object') {
    testError.value = '参数必须是 JSON 对象，例如 {"query":"图书馆"}。'
    return
  }
  testBusy.value = true
  try {
    const result = await api.invokePlugin(testPlugin.value.name, parameters as Record<string, unknown>)
    const external = testPlugin.value.name === 'baidu_baike_search'
      && typeof result === 'object' && result !== null && 'result' in result
      && typeof result.result === 'object' && result.result !== null
      && 'external' in result.result && result.result.external === true
    if (external) {
      const query = String((parameters as Record<string, unknown>).bk_key).trim()
      baikeUrl.value = `https://baike.baidu.com/search/word?word=${encodeURIComponent(query)}`
      if (desktop) {
        await desktop.openBaike(query)
        testResult.value = { message: '已在系统浏览器打开百度百科搜索' }
      }
    } else testResult.value = result
  }
  catch (error) { testError.value = friendlyError(error) }
  finally { testBusy.value = false }
}

function saveAdminToken(value: string) {
  adminToken.value = value
  sessionStorage.setItem('campus-agent-admin-token', value)
}

watch(() => workspace.persistenceError, message => {
  if (message) ElMessage.error(message)
})

const systemAppearance = window.matchMedia('(prefers-color-scheme: dark)')
function updateAppearance() {
  applyAppearance(workspace.appearance, workspace.accentColor, systemAppearance.matches)
}
watch(() => [workspace.appearance, workspace.accentColor], updateAppearance, { immediate: true })
systemAppearance.addEventListener('change', updateAppearance)

async function loadDesktopInfo() {
  if (!desktop) return
  desktopError.value = ''
  try { desktopInfo.value = await desktop.getInfo() }
  catch (error) { desktopError.value = `无法读取桌面应用信息：${friendlyError(error)}` }
}

async function openDataFolder() {
  if (!desktop || desktopAction.value) return
  desktopAction.value = 'folder'
  try { await desktop.openDataFolder() }
  catch (error) { desktopError.value = `无法打开数据文件夹：${friendlyError(error)}`; ElMessage.error(desktopError.value) }
  finally { desktopAction.value = '' }
}

async function openOllamaDownload() {
  if (!desktop) return
  try { await desktop.openOllamaDownload() }
  catch (error) { localError.value = `无法打开 Ollama 下载页：${friendlyError(error)}` }
}

async function restartDesktop() {
  if (!desktop || desktopAction.value) return
  const busy = chatBusy.value || historyBusy.value || serviceBusy.value || Boolean(docAction.value) || Boolean(pluginAction.value) || testBusy.value
  const hasDraft = prompt.value.trim() || pluginSource.value.trim() || repair.value.location || repair.value.description || repair.value.contact
  if (busy || hasDraft) {
    try {
      await ElMessageBox.confirm(
        busy ? '仍有操作正在进行，重启会中断操作。确定现在重启？' : '尚未提交的输入将在重启后清空。确定现在重启？',
        '重启 Mens',
        { type: 'warning', confirmButtonText: '重启', cancelButtonText: '取消' },
      )
    } catch { return }
  }
  desktopAction.value = 'restart'
  try {
    if (!await workspace.flushWorkspace()) throw new Error('本地偏好未保存成功，请先重试保存后再重启。')
    await desktop.restart()
  } catch (error) { ElMessage.error(friendlyError(error)) }
  finally { desktopAction.value = '' }
}

onMounted(async () => {
  void loadHealth()
  void loadWebStatus()
  void loadDesktopInfo()
  await workspace.initialize()
  void loadModelConfig()
  void loadLocalModels()
  void restoreConversation()
  void loadConversations()
  if (workspace.view === 'knowledge') void loadDocuments()
  if (workspace.view === 'plugins') void loadPlugins()
  if (workspace.view === 'plugins') void loadCuratedPlugins()
  if (workspace.view === 'settings') { void loadModelConfig(); void loadLocalModels(); void loadCampusSources(); void loadWebStatus() }
})

onUnmounted(() => {
  if (downloadTimer) clearTimeout(downloadTimer)
  systemAppearance.removeEventListener('change', updateAppearance)
})
</script>

<template>
  <div class="app-shell" :class="{ 'desktop-app': desktop }">
    <div v-if="mobileNavOpen" class="mobile-scrim" @click="mobileNavOpen = false" />
    <aside class="sidebar" :class="{ 'sidebar-open': mobileNavOpen }">
      <div class="brand">
        <img class="brand-mark" :src="mensLogo" alt="" />
        <span><strong>Mens</strong><small>{{ desktop ? '桌面智能办事工作台' : '智能办事工作台' }}</small></span>
      </div>
      <div class="side-content">
        <template v-for="section in ['工作区', '管理']" :key="section">
          <div class="nav-section">{{ section }}</div>
          <button v-for="item in nav.filter(entry => entry.section === section)" :key="item.key" class="nav-item" :class="{ active: workspace.view === item.key }" @click="selectView(item.key)">
            <el-icon :size="18"><component :is="item.icon" /></el-icon><span>{{ item.label }}</span>
          </button>
        </template>
      </div>
      <div class="side-footer">
        <div class="connection-dot" :class="{ demo: !health }" />
        <span>{{ healthLabel }}</span>
        <span class="side-version">{{ desktop ? (desktopInfo ? `v${desktopInfo.version}` : '桌面版') : `v${frontendVersion}` }}</span>
      </div>
    </aside>

    <div class="main-shell">
      <header class="topbar">
        <button class="mobile-menu icon-button" aria-label="打开导航" @click="mobileNavOpen = true"><el-icon :size="20"><Grid /></el-icon></button>
        <div class="breadcrumb"><span>Mens</span><el-icon><ArrowRight /></el-icon><strong>{{ viewLabel }}</strong></div>
        <div class="top-actions"><span class="mode-chip" :class="{ demo: !health }">{{ healthLabel }}</span><span class="model-chip" :title="modelLabel">{{ modelLabel }}</span></div>
      </header>

      <main class="main-content" :class="{ 'chat-main': workspace.view === 'chat' }">
        <section v-if="workspace.view === 'chat'" class="chat-view">
          <div class="page-heading chat-heading"><div><div class="eyebrow">MENS ASSISTANT</div><h1>智能问答</h1></div><div class="chat-actions"><div class="chat-model-picker"><el-select :model-value="chatModel" aria-label="聊天模型" :disabled="!workspace.ready || chatBusy" @update:model-value="selectChatModel" @visible-change="($event: boolean) => { if ($event) loadLocalModels() }"><el-option-group label="云端与自动路由"><el-option value="auto" label="自动路由" /><el-option value="qwen3" label="Qwen3" /><el-option value="deepseek" label="DeepSeek" /></el-option-group><el-option-group label="本地 Ollama"><el-option v-if="workspace.model === 'ollama' && !installedLocalModel" :value="`local:${currentLocalModel}`" :label="currentLocalModel || '本地模型'" disabled /><el-option v-for="item in localModels?.installed || []" :key="item.name" :value="`local:${item.name}`" :label="item.name" :disabled="!localModels?.running" /><el-option v-if="!localModels?.installed.length && workspace.model !== 'ollama'" value="unavailable" :label="localBusy ? '正在检测…' : localModels?.running ? '暂无已安装模型' : 'Ollama 未连接'" disabled /></el-option-group></el-select><el-tooltip content="刷新本地模型"><el-button :icon="Refresh" :loading="localBusy" :disabled="chatBusy" aria-label="刷新本地模型" @click="loadLocalModels" /></el-tooltip></div><el-button :icon="Clock" :type="historyOpen ? 'primary' : 'default'" plain :aria-pressed="historyOpen" @click="historyOpen = !historyOpen">历史记录</el-button><el-button :icon="Plus" :disabled="!workspace.ready || chatBusy || historyBusy" @click="newConversation">新对话</el-button></div></div>
          <div class="chat-body">
            <aside v-show="historyOpen" class="history-panel" aria-label="历史对话">
              <div class="history-head"><strong>历史对话</strong><span class="history-count">{{ conversations.length }}</span><el-button text :icon="Refresh" :loading="conversationsBusy" aria-label="刷新历史对话" @click="loadConversations" /><el-button text :disabled="!conversations.length || chatBusy" @click="clearConversations">清空</el-button></div>
              <p v-if="conversationsError" class="history-error">{{ conversationsError }}</p>
              <div class="history-list" v-loading="conversationsBusy">
                <p v-if="!conversationsBusy && !conversationsError && conversations.length === 0" class="history-empty">暂无历史对话。<br />发送第一条消息后会自动保存。</p>
                <div v-for="item in conversations" :key="item.id" class="history-item" :class="{ active: item.id === workspace.conversationId, disabled: chatBusy }" role="button" tabindex="0" :aria-disabled="chatBusy" @click="openConversation(item.id)" @keydown.enter="openConversation(item.id)">
                  <div class="history-item-main"><strong>{{ item.title }}</strong><small>{{ item.message_count }} 条消息 · {{ chatTime(item.updated_at) }}</small></div>
                  <el-button class="history-delete" text type="danger" :icon="Delete" :disabled="chatBusy" :aria-label="`删除对话：${item.title}`" @click.stop="deleteConversation(item)" />
                </div>
              </div>
            </aside>
            <div class="chat-column">
          <div class="conversation" aria-live="polite">
            <el-alert v-if="historyError" :title="historyError" type="error" show-icon :closable="false"><el-button text @click="restoreConversation">重试恢复</el-button></el-alert>
            <el-alert v-if="localChatProblem" :title="localChatProblem" type="warning" show-icon :closable="false"><el-button text @click="selectView('settings')">模型设置</el-button></el-alert>
            <div v-if="!workspace.ready || historyBusy" class="history-loading">正在恢复对话…</div>
            <div v-if="workspace.ready && messages.length === 0 && !historyBusy && !historyError" class="chat-empty">
              <div class="empty-symbol"><img :src="mensLogo" alt="Mens" /></div>
              <h2>今天需要办理什么？</h2>
              <div class="suggestions"><button v-for="suggestion in chatSuggestions" :key="suggestion" @click="sendChat(suggestion)">{{ suggestion }}<el-icon><ArrowRight /></el-icon></button></div>
            </div>
            <div v-for="(message, index) in messages" :key="index" class="message-row" :class="message.role">
              <div class="message-avatar"><template v-if="message.role === 'user'">我</template><img v-else :src="mensLogo" alt="" /></div>
              <div class="message-body"><div class="message-author">{{ message.role === 'user' ? '你' : 'Mens' }}<span v-if="message.demo" class="inline-demo">演示回答</span><span v-if="message.error" class="inline-demo">请求失败</span><span v-if="message.stopped" class="inline-demo">已停止</span></div><div class="message-text">{{ message.text }}<span v-if="message.streaming && message.text" class="stream-caret" /></div><p v-if="message.note" class="message-note">{{ message.note }}</p>
                <div v-if="message.tools?.length" class="tool-note"><el-icon><Connection /></el-icon> 已调用 {{ message.tools.join('、') }}</div>
                <div v-if="message.sources?.length" class="source-list"><div class="source-label">{{ message.sources.some(source => source.kind === 'web') ? '参考来源（含联网检索）' : '参考来源' }}</div><div v-for="(source, sourceIndex) in message.sources" :key="sourceIndex" class="source-item"><el-icon><Link v-if="source.kind === 'web'" /><Document v-else /></el-icon><div><strong>{{ source.title || source.source }}</strong><small v-if="source.snippet">{{ source.snippet }}</small><small v-if="source.url" class="source-url"><a v-if="!desktop" :href="source.url" target="_blank" rel="noopener noreferrer">{{ sourceHost(source.url) }} ↗</a><button v-else type="button" class="link-button" @click="openSourceUrl(source.url)">{{ sourceHost(source.url) }} ↗</button></small></div></div></div>
              </div>
            </div>
            <div v-if="chatBusy && !streamingMessage?.text" class="message-row assistant"><div class="message-avatar"><img :src="mensLogo" alt="" /></div><div class="message-body"><div class="message-author">Mens</div><div class="typing"><span /><span /><span /></div></div></div>
            <div ref="chatEnd" />
          </div>
          <div class="composer-wrap"><div class="composer"><textarea v-model="prompt" rows="2" maxlength="4000" :disabled="!workspace.ready || historyBusy" placeholder="输入问题..." aria-label="输入问题" @keydown="onChatKeydown" /><div class="composer-bottom"><el-tooltip :content="webToggleHint" placement="top"><label class="web-toggle"><el-switch v-model="webSwitch" :disabled="!webAvailable || chatBusy" size="small" /><span>联网搜索</span></label></el-tooltip><span>回答仅供参考，请核对学校正式通知</span><el-button v-if="chatBusy" type="danger" plain :icon="CircleClose" @click="stopChat">停止生成</el-button><el-button v-else type="primary" :icon="ArrowRight" :disabled="!workspace.ready || !prompt.trim() || historyBusy || Boolean(historyError) || Boolean(localChatProblem)" @click="sendChat()">发送</el-button></div></div></div>
            </div>
          </div>
        </section>

        <section v-else-if="workspace.view === 'services'" class="content-view">
          <div class="page-heading"><div><div class="eyebrow">MENS SERVICES</div><h1>校园服务</h1><p>查询教务信息，查找教室，提交后勤报修。</p></div></div>
          <div class="service-layout"><nav class="service-nav" aria-label="校园服务"><button v-for="(label, key) in serviceNames" :key="key" :disabled="serviceBusy" :class="{ active: activeService === key }" @click="selectService(key as ServiceKey)"><span>{{ label }}</span><el-icon><ArrowRight /></el-icon></button></nav>
            <div class="service-panel"><div class="panel-heading"><h2>{{ serviceNames[activeService] }}</h2><p>{{ activeService === 'repair' ? '未接入学校报修接口时，工单仅保存在本机。' : '已配置的数据从学校接口读取；未配置的类型显示演示数据。' }}</p></div>
              <div class="form-grid">
                <template v-if="activeService === 'classrooms'"><label class="field"><span>教学楼</span><el-input v-model="classroom.building" placeholder="全部教学楼" clearable /></label><label class="field"><span>最少座位数</span><el-input-number v-model="classroom.minSeats" :min="0" :max="1000" :precision="0" /></label></template>
                <template v-if="activeService === 'repair'"><label class="field"><span>报修地点</span><el-input v-model="repair.location" :maxlength="120" placeholder="例如：3 号宿舍楼 205 室" /></label><label class="field"><span>联系方式</span><el-input v-model="repair.contact" :maxlength="120" placeholder="手机号码或校园邮箱" /></label><label class="field field-wide"><span>问题描述</span><el-input v-model="repair.description" type="textarea" :rows="4" :maxlength="2000" show-word-limit placeholder="请描述设施故障和需要处理的问题" /></label></template>
              </div><div class="form-action"><el-button type="primary" :icon="activeService === 'repair' ? Check : Search" :loading="serviceBusy" @click="runService">{{ activeService === 'repair' ? '提交报修' : '查询' }}</el-button></div>
              <el-alert v-if="serviceError" class="alert" :title="serviceError" type="error" show-icon :closable="false" />
              <div v-if="serviceResult !== null" class="result-section"><div class="result-title"><h3>{{ activeService === 'repair' ? '提交结果' : '查询结果' }}</h3><span v-if="serviceIsDemo" class="demo-label">后端演示数据</span></div><el-empty v-if="resultRows.length === 0" description="暂无结果" :image-size="84" /><div v-else class="table-scroll"><el-table :data="resultRows" stripe border><el-table-column v-for="column in resultColumns" :key="column" :prop="column" :label="columnLabels[column] || column" min-width="130"><template #default="scope">{{ cellText(scope.row[column]) }}</template></el-table-column></el-table></div></div>
              <div v-if="activeService === 'repair'" class="result-section">
                <div class="result-title"><h3>本机报修记录</h3><el-button text :icon="Refresh" :loading="repairListBusy" @click="loadRepairs">刷新记录</el-button></div>
                <el-alert v-if="repairListError" class="alert" :title="repairListError" type="warning" show-icon :closable="false"><el-button text @click="selectView('settings')">填写管理员令牌</el-button></el-alert>
                <el-empty v-else-if="!repairListBusy && repairList.length === 0" description="暂无本机报修记录" :image-size="84" />
                <template v-else><div class="table-scroll"><el-table v-loading="repairListBusy" :data="repairList" stripe border><el-table-column label="提交时间" min-width="160"><template #default="scope">{{ String(scope.row.created_at).slice(0, 16).replace('T', ' ') }}</template></el-table-column><el-table-column prop="location" label="地点" min-width="150" /><el-table-column prop="issue" label="问题" min-width="220" /><el-table-column prop="status" label="状态" width="140" /></el-table></div><p v-if="repairListDemo" class="management-note">未接入学校报修接口，以上记录仅保存在本机。</p></template>
              </div>
            </div></div>
        </section>

        <section v-else-if="workspace.view === 'knowledge'" class="content-view">
          <div class="page-heading"><div><div class="eyebrow">KNOWLEDGE BASE</div><h1>知识库</h1><p>维护政策文件与办事指南，更新后可重建检索索引。</p></div><div class="heading-actions"><el-button :icon="Refresh" :loading="docAction === 'reindex'" @click="reindex">重建索引</el-button><el-button type="primary" :icon="Upload" :loading="docAction === 'upload'" @click="uploadInput?.click()">上传文档</el-button><input ref="uploadInput" class="hidden-input" type="file" accept=".pdf,.md,.txt,.docx" @change="onUpload" /></div></div>
          <div class="section-toolbar"><div><strong>文档列表</strong><span>{{ documents.length }} 份文档</span></div><el-button text :icon="Refresh" :loading="docsBusy" @click="loadDocuments">刷新</el-button></div>
          <el-alert v-if="docsError" class="alert" :title="docsError" type="error" show-icon :closable="false" />
          <p class="management-note">支持 PDF、Markdown、TXT、Word (.docx)，最大 5 MB。<template v-if="!desktop">管理操作需在「设置」填写管理员令牌。</template><template v-else>文档保存在本机应用数据目录。</template></p>
          <div class="data-panel"><el-empty v-if="!docsBusy && !docsError && documents.length === 0" description="暂无文档，上传政策文件开始使用" :image-size="96" /><el-table v-else v-loading="docsBusy" :data="documents" stripe><el-table-column label="文件" min-width="220"><template #default="scope"><div class="file-cell"><el-icon :size="18"><Document /></el-icon><span>{{ scope.row.filename }}</span></div></template></el-table-column><el-table-column label="文本长度" width="110"><template #default="scope">{{ scope.row.content?.length ?? '—' }}</template></el-table-column><el-table-column prop="updated_at" label="更新时间" min-width="170"><template #default="scope">{{ scope.row.updated_at ? String(scope.row.updated_at).slice(0, 16).replace('T', ' ') : '—' }}</template></el-table-column><el-table-column label="操作" width="165" fixed="right"><template #default="scope"><label class="table-action">更新<input type="file" accept=".pdf,.md,.txt" :disabled="Boolean(docAction)" @change="onReplace(scope.row.id, $event)" /></label><el-button link type="danger" :loading="docAction === scope.row.id" :disabled="Boolean(docAction)" @click="deleteDocument(scope.row)">删除</el-button></template></el-table-column></el-table></div>
        </section>

        <section v-else-if="workspace.view === 'plugins'" class="content-view">
          <div class="page-heading"><div><div class="eyebrow">MENS EXTENSIONS</div><h1>插件</h1><p>按需安装和管理可用工具。</p></div></div>
          <div class="section-toolbar"><div><strong>推荐插件</strong><span>按需安装</span></div><el-button text :icon="Refresh" @click="loadCuratedPlugins">刷新</el-button></div>
          <el-alert v-if="catalogError" class="alert" :title="catalogError" type="error" show-icon :closable="false" />
          <div class="plugin-list curated-list"><div v-for="item in curatedPlugins" :key="item.id" class="plugin-row"><div class="plugin-icon"><el-icon :size="20"><Connection /></el-icon></div><div class="plugin-info"><strong>{{ item.name }}</strong><p>{{ item.description }}</p></div><span v-if="item.installed" class="status-text">已安装</span><el-button v-else type="primary" plain :icon="Download" :loading="pluginAction === item.id" :disabled="Boolean(pluginAction)" @click="installCuratedPlugin(item.id)">安装</el-button></div></div>
          <div class="install-band"><div><h2>安装插件</h2><p>输入 HTTPS 插件清单地址；主机需在后端白名单中。</p></div><div class="install-controls"><el-input v-model="pluginSource" placeholder="https://example.edu/plugin.json" clearable @keyup.enter="installPlugin" /><el-button type="primary" :icon="Plus" :loading="pluginAction === 'install'" :disabled="!pluginSource.trim()" @click="installPlugin">安装</el-button></div></div>
          <div class="section-toolbar"><div><strong>已安装插件</strong><span>{{ plugins.length }} 个</span></div><el-button text :icon="Refresh" :loading="pluginsBusy" @click="loadPlugins">刷新</el-button></div>
          <el-alert v-if="pluginsError" class="alert" :title="pluginsError" type="error" show-icon :closable="false" />
          <p v-if="!desktop" class="management-note">安装、启停和测试调用需在「设置」填写管理员令牌。</p>
          <div class="plugin-list" v-loading="pluginsBusy"><el-empty v-if="!pluginsBusy && !pluginsError && plugins.length === 0" description="尚未安装插件" :image-size="96" /><div v-for="plugin in plugins" :key="plugin.id" class="plugin-row"><div class="plugin-icon"><el-icon :size="20"><Connection /></el-icon></div><div class="plugin-info"><div><strong>{{ plugin.name }}</strong></div><p>{{ plugin.description || plugin.url || '自定义插件' }}</p></div><el-switch :model-value="plugin.enabled" :loading="pluginAction === plugin.id" :disabled="Boolean(pluginAction)" :aria-label="`${plugin.name} 启用状态`" @change="togglePlugin(plugin, Boolean($event))" /><el-button link type="primary" :disabled="!plugin.enabled || Boolean(pluginAction)" @click="openPluginTest(plugin)">测试调用</el-button><el-button link type="danger" :loading="pluginAction === plugin.id" :disabled="Boolean(pluginAction)" @click="removePlugin(plugin)">卸载</el-button></div></div>
          <div v-if="testPlugin" class="plugin-test"><div class="result-title"><h3>测试插件：{{ testPlugin.name }}</h3></div><p v-if="testPlugin.name === 'baidu_baike_search'">{{ desktop ? '输入词条关键词，搜索结果将在系统浏览器中打开。' : '输入词条关键词，生成链接后点击打开百度百科搜索结果。' }}</p><p v-else>参数将由后端发送至已注册服务 {{ testPlugin.url }}。</p><details v-if="testPlugin.parameters"><summary>查看参数定义</summary><pre>{{ JSON.stringify(testPlugin.parameters, null, 2) }}</pre></details><label class="field"><span>JSON 参数</span><el-input v-model="testParameters" type="textarea" :rows="5" :disabled="testBusy" /></label><div class="form-action"><el-button type="primary" :loading="testBusy" @click="invokePlugin">{{ testPlugin.name === 'baidu_baike_search' ? '搜索词条' : '发送测试请求' }}</el-button><el-button :disabled="testBusy" @click="testPlugin = null">关闭</el-button></div><el-alert v-if="testError" class="alert" :title="testError" type="error" show-icon :closable="false" /><a v-if="baikeUrl && !desktop" :href="baikeUrl" target="_blank" rel="noopener noreferrer">打开百度百科搜索结果</a><pre v-if="testResult !== null" class="plugin-result">{{ JSON.stringify(testResult, null, 2) }}</pre></div>
        </section>

        <section v-else class="content-view settings-view">
          <div class="page-heading"><div><div class="eyebrow">PREFERENCES</div><h1>设置</h1><p>{{ desktop ? '管理桌面应用与模型偏好，查看本机服务状态。' : '选择当前浏览器的模型偏好，查看后端服务状态。' }}</p></div></div>
          <AppearanceSettings :mode="workspace.appearance" :accent="workspace.accentColor" :disabled="!workspace.ready" @update:mode="workspace.setAppearance" @update:accent="workspace.setAccentColor" />
          <template v-if="desktop">
            <div class="settings-section"><div class="settings-copy"><h2>Mens 桌面版</h2><p>版本 {{ desktopInfo?.version || '读取中…' }} · 启动应用时自动运行本机服务。</p></div><el-button :icon="Refresh" :loading="desktopAction === 'restart'" :disabled="!workspace.ready || Boolean(desktopAction)" @click="restartDesktop">重启应用</el-button></div>
            <div class="settings-section desktop-storage"><div class="settings-copy"><h2>本机数据</h2><p>知识库、对话记录和应用配置保存在以下位置。</p><code v-if="desktopInfo" class="data-path">{{ desktopInfo.dataPath }}</code></div><el-button :icon="FolderOpened" :loading="desktopAction === 'folder'" :disabled="Boolean(desktopAction)" @click="openDataFolder">打开数据文件夹</el-button></div>
            <div class="settings-section log-section"><div class="settings-copy"><h2>后端日志</h2><p>最近的后端诊断输出（最多 200 KB），完整日志位于数据目录的 <code>logs/backend.log</code>。</p><el-alert v-if="logError" class="alert" :title="logError" type="warning" show-icon :closable="false" /><pre v-if="logText" class="log-view">{{ logText }}</pre></div><div class="backup-actions"><el-button :icon="Refresh" :loading="logBusy" @click="loadLog">读取日志</el-button><el-button :icon="FolderOpened" :loading="desktopAction === 'folder'" :disabled="Boolean(desktopAction)" @click="openDataFolder">打开文件夹</el-button></div></div>
            <el-alert v-if="desktopError" class="alert" :title="desktopError" type="error" show-icon :closable="false"><el-button text @click="loadDesktopInfo">重试</el-button></el-alert>
          </template>
          <el-alert v-if="workspace.persistenceError" class="alert" :title="workspace.persistenceError" type="error" show-icon :closable="false"><el-button text @click="workspace.persistWorkspace">重试保存</el-button></el-alert>
          <div class="settings-section"><div class="settings-copy"><h2>当前模型</h2><p>选择已配置的云端模型或本机运行的开源模型。</p></div><el-radio-group :model-value="workspace.model" :disabled="!workspace.ready" @update:model-value="workspace.setModel($event as Model)"><el-radio-button value="auto">自动路由</el-radio-button><el-radio-button value="qwen3">Qwen3</el-radio-button><el-radio-button value="deepseek">DeepSeek</el-radio-button><el-radio-button value="ollama">本地模型</el-radio-button></el-radio-group></div>
          <div class="settings-panel">
            <div class="panel-heading"><h2>云端模型 API</h2><p>填写提供商信息并保存后测试连接。留空 API Key 会保留现有密钥。</p></div>
            <div class="provider-tabs"><el-radio-group v-model="provider" :disabled="Boolean(modelAction)"><el-radio-button value="qwen">Qwen</el-radio-button><el-radio-button value="deepseek">DeepSeek</el-radio-button></el-radio-group><span class="status-text">{{ modelConfig?.providers[provider]?.configured ? 'API Key 已配置' : '未配置 API Key' }}</span></div>
            <div class="form-grid model-form"><label class="field field-wide"><span>API Key</span><el-input v-model="modelForm.api_key" type="password" autocomplete="off" placeholder="输入新密钥；留空保留已有密钥" :disabled="Boolean(modelAction)" /></label><label class="field field-wide"><span>API 地址</span><el-input v-model="modelForm.base_url" placeholder="https://…/v1" :disabled="Boolean(modelAction)" /></label><label class="field field-wide"><span>模型名称</span><el-input v-model="modelForm.model" placeholder="输入提供商支持的模型名称" :disabled="Boolean(modelAction)" /></label></div>
            <div class="form-action"><el-button type="primary" :loading="modelAction === 'save'" :disabled="Boolean(modelAction)" @click="saveModelConfig()">保存配置</el-button><el-button :loading="modelAction === 'test'" :disabled="Boolean(modelAction) || !modelConfig?.providers[provider]?.configured" @click="testModel">测试已保存配置</el-button><el-button text type="danger" :disabled="Boolean(modelAction) || !modelConfig?.providers[provider]?.configured" @click="saveModelConfig(true)">清除密钥</el-button></div>
            <el-alert v-if="modelError" class="alert" :title="modelError" type="error" show-icon :closable="false" />
          </div>
          <div class="settings-panel">
            <div class="panel-heading panel-title-row"><div><h2>开源本地模型</h2><p>通过本机 Ollama 运行。模型文件可能占用数 GB 空间。</p></div><el-button text :icon="Refresh" :loading="localBusy" @click="loadLocalModels">刷新</el-button></div>
            <el-alert v-if="localModels && !localModels.running" class="alert" title="未检测到 Ollama，请先安装并启动 Ollama，再点击刷新。" type="warning" show-icon :closable="false"><el-button v-if="desktop" text @click="openOllamaDownload">前往 Ollama 官方下载页</el-button><a v-else href="https://ollama.com/download/windows" target="_blank" rel="noopener noreferrer">前往 Ollama 官方下载页</a></el-alert>
            <div class="form-grid model-form"><label class="field"><span>下载模型</span><el-select v-model="selectedLocalModel" placeholder="选择开源模型" :disabled="!localModels?.running"><el-option v-for="item in localModels?.catalog || []" :key="item.id" :value="item.id" :label="`${item.label} ${fileSize(item.size_bytes)}`" /></el-select></label><label class="field"><span>下载源 / 镜像</span><el-select v-model="selectedMirror" placeholder="选择下载源"><el-option v-for="item in localModels?.sources || []" :key="item.id" :value="item.id" :label="item.label" /></el-select></label></div>
            <div class="form-action"><el-button type="primary" :icon="Download" :loading="downloadStarting" :disabled="!localModels?.running || !selectedLocalModel || downloadActive" @click="downloadLocalModel">下载模型</el-button></div>
            <div v-if="download" class="download-status" aria-live="polite"><div><span>{{ download.status === 'completed' ? '下载完成' : download.status === 'failed' ? '下载失败' : download.status === 'cancelled' ? '已取消' : download.detail || '正在下载模型…' }}</span></div><el-progress :percentage="downloadProgress" :status="download.status === 'failed' ? 'exception' : download.status === 'completed' ? 'success' : undefined" /><el-button v-if="!['completed', 'failed', 'cancelled'].includes(download.status)" text type="danger" @click="cancelDownload">取消下载</el-button></div>
            <el-alert v-if="localError || localModels?.error" class="alert" :title="localError || localModels?.error" type="error" show-icon :closable="false" />
            <div class="local-models"><h3>已安装模型</h3><p v-if="!localModels?.installed.length" class="management-note">暂无可用的本地模型。</p><div v-for="item in localModels?.installed || []" :key="item.name" class="local-model-row"><div><strong>{{ item.name }}</strong><small>{{ fileSize(item.size_bytes || item.size) }}</small></div><el-button :type="workspace.model === 'ollama' && currentLocalModel === item.name ? 'primary' : 'default'" plain :disabled="!workspace.ready || chatBusy" @click="selectInstalledModel(item.name)">{{ workspace.model === 'ollama' && currentLocalModel === item.name ? '已选择' : '使用模型' }}</el-button></div></div>
          </div>
          <div class="settings-panel">
            <div class="panel-heading"><h2>校园数据接口</h2><p>按数据类型连接学校的 HTTPS JSON 接口。令牌仅保存在本机，不会显示在页面上。</p></div>
            <div class="form-grid model-form"><label class="field"><span>数据类型</span><el-select v-model="campusKind" :disabled="Boolean(campusAction)"><el-option v-for="item in campusSources" :key="item.kind" :value="item.kind" :label="item.label" /></el-select></label><label class="field"><span>接入状态</span><span class="status-text">{{ activeCampusSource?.configured ? '已配置' : '演示数据' }}</span></label>
              <label class="field field-wide"><span>接口地址</span><el-input v-model="campusForm.url" placeholder="https://school.edu/api/grades" :disabled="Boolean(campusAction)" /></label>
              <label class="field field-wide"><span>JSON 结果路径</span><el-input v-model="campusForm.result_path" placeholder="例如 data.items；根级数据留空" :disabled="Boolean(campusAction)" /></label>
              <label class="field field-wide"><span>Bearer 令牌</span><el-input v-model="campusForm.token" type="password" autocomplete="off" :placeholder="activeCampusSource?.has_token ? '已配置，留空保留原令牌' : '可选'" :disabled="Boolean(campusAction)" /></label></div>
            <div class="form-action"><el-button type="primary" :loading="campusAction === 'save'" :disabled="Boolean(campusAction) || !campusForm.url.trim()" @click="saveCampusSource">保存接口</el-button><el-button :disabled="Boolean(campusAction) || !activeCampusSource?.configured" @click="testCampusSource">测试读取</el-button><el-button text type="danger" :loading="campusAction === 'remove'" :disabled="Boolean(campusAction) || !activeCampusSource?.configured" @click="removeCampusSource">移除接口</el-button></div>
            <el-alert v-if="campusError" class="alert" :title="campusError" type="error" show-icon :closable="false" />
          </div>
          <div class="settings-section"><div class="settings-copy"><h2>备份与恢复</h2><p>导出包含知识库、对话记录、模型与校园接口配置的 zip 备份；其中的密钥和令牌属于敏感数据，请妥善保管。导入会覆盖当前数据<template v-if="desktop">，重启应用后完全生效</template>。</p><p v-if="backupInfo" class="backup-info" aria-live="polite">{{ backupInfo }}</p><el-alert v-if="backupError" class="alert" :title="backupError" type="error" show-icon :closable="false" /></div><div class="backup-actions"><el-button :icon="Download" :loading="backupAction === 'export'" :disabled="Boolean(backupAction) || !workspace.ready" @click="exportBackup">导出备份</el-button><el-button :icon="Upload" :loading="backupAction === 'import'" :disabled="Boolean(backupAction) || !workspace.ready" @click="importBackup">导入备份</el-button><input v-if="!desktop" ref="backupInput" class="hidden-input" type="file" accept=".zip" @change="onBackupFile" /></div></div>
          <div v-if="!desktop" class="settings-section"><div class="settings-copy"><h2>管理员令牌</h2><p>用于文档与插件管理，仅保存在当前浏览器会话。</p></div><el-input :model-value="adminToken" type="password" show-password placeholder="输入后端 ADMIN_TOKEN" style="max-width: 280px" @update:model-value="saveAdminToken(String($event))" /></div>
          <div class="settings-section"><div class="settings-copy"><h2>联网搜索</h2><p>开启后聊天窗口可逐条选择是否联网检索，回答会引用网页链接。默认使用免密钥的 Bing 网页搜索（中国大陆可直连），也可配置 Tavily 或博查 API Key。<template v-if="webStatus"> 当前生效：{{ webStatus.providers.find(item => item.id === webStatus?.provider)?.label || webStatus.provider }}<template v-if="webStatus.available">（{{ webStatus.resolved_provider }}）</template><template v-else>（缺少 API Key）</template>。</template></p><p v-if="webSaved" class="backup-info" aria-live="polite">{{ webSaved }}</p><el-alert v-if="webError" class="alert" :title="webError" type="warning" show-icon :closable="false" /></div><div class="web-form"><div class="web-form-row"><label class="field field-inline"><el-switch v-model="webForm.enabled" /><span>启用联网搜索</span></label><label class="field"><span>搜索服务</span><el-select v-model="webForm.provider"><el-option v-for="item in webStatus?.providers || []" :key="item.id" :value="item.id" :label="item.label" /></el-select></label></div><div class="web-form-row"><label class="field"><span>API Key</span><el-input v-model="webForm.apiKey" type="password" autocomplete="off" placeholder="Bing 免密钥；Tavily/博查需填写" /></label><label class="field field-narrow"><span>返回结果数</span><el-input-number v-model="webForm.maxResults" :min="1" :max="webStatus?.max_results_limit || 8" :precision="0" /></label><label class="field field-narrow"><span>读取网页数</span><el-input-number v-model="webForm.fetchPages" :min="0" :max="webStatus?.max_fetch_pages || 3" :precision="0" /></label></div></div><div class="backup-actions"><el-button type="primary" :loading="webSaving" @click="saveWebConfig">保存联网设置</el-button></div></div>
          <div class="settings-section"><div class="settings-copy"><h2>版本与更新</h2><p>当前版本 {{ desktop ? (desktopInfo?.version ? `v${desktopInfo.version}` : '读取中…') : `v${frontendVersion}` }}。<template v-if="updateInfo"> {{ updateInfo }}</template><template v-else>更新清单地址由管理员在 .env（UPDATE_MANIFEST_URL）中配置，未配置时不联网检查。</template></p><el-alert v-if="updateError" class="alert" :title="updateError" type="warning" show-icon :closable="false" /></div><div class="backup-actions"><el-button :icon="Refresh" :loading="updateBusy" @click="checkUpdates">检查更新</el-button><el-button v-if="updateUrl" type="primary" :icon="Download" @click="openUpdateUrl">打开下载页</el-button></div></div>
          <div class="settings-section"><div class="settings-copy"><h2>服务状态</h2><p>{{ healthLabel }}<template v-if="health"> · {{ health.rag_degraded ? '向量检索故障，已降级关键词检索' : health.rag_enabled ? '向量检索已启用' : '本地关键词检索' }} · {{ health.demo_services ? '校务服务为演示数据' : '已配置部分校务接口' }}</template></p></div><el-button :icon="Refresh" :loading="healthBusy" @click="loadHealth">刷新状态</el-button></div>
          <el-alert v-if="healthError" :title="healthError" type="error" show-icon :closable="false" />
        </section>
      </main>
    </div>
  </div>
</template>
