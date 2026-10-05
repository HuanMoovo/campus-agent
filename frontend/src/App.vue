<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown, ArrowRight, Bottom, ChatLineRound, Check, CircleClose, Clock, Connection, Delete, Document, EditPen, FolderOpened,
  Grid, Link, MoreFilled, Paperclip, Plus, Refresh, Search, Setting, Top, Upload, Download,
} from '@element-plus/icons-vue'
import { api, ChatStreamError, chatStream, type CampusSource, type ConversationSearchResult, type ConversationSummary, type Health, type KnowledgeDocument, type LocalModels, type ModelConfig, type ModelDownload, type Plugin, type RepairRecord, type Source, type WebStatus } from './api'
import { useWorkspaceStore, type Model, type View } from './store'
import { applyLocale, t } from './i18n'
import { desktop, type DesktopInfo } from './desktop'
import mensLogo from './assets/mens.png'
import AppearanceSettings from './components/AppearanceSettings.vue'
import McpSettings from './components/McpSettings.vue'
import LoginView from './components/LoginView.vue'
import AccountSettings from './components/AccountSettings.vue'
import CommandPalette from './components/CommandPalette.vue'
import QuickAsk from './components/QuickAsk.vue'
import OnboardingModal from './components/OnboardingModal.vue'
import { matchSlashCommands, SLASH_COMMANDS } from './commands'
import { attachmentAccept, attachmentKind, attachmentSuffix, attachmentTextProblem, ATTACHMENT_MAX_COUNT, type ChatAttachment } from './attachments'
import { User as UserIcon } from '@element-plus/icons-vue'
import { authLogout, authMe, healthInfo, type AuthUser } from './api'
import { applyAppearance } from './appearance'
import { renderMarkdown } from './markdown'
import { version as frontendVersion } from '../package.json'

type Message = { role: 'user' | 'assistant'; text: string; sources?: Source[]; tools?: string[]; demo?: boolean; error?: boolean; streaming?: boolean; stopped?: boolean; note?: string; thinking?: string; thinkingOpen?: boolean; id?: number; feedback?: 'up' | 'down' }
type ServiceKey = 'grades' | 'schedule' | 'credits' | 'classrooms' | 'repair' | 'notices' | 'library' | 'dining' | 'shuttle'

const workspace = useWorkspaceStore()
const desktopInfo = ref<DesktopInfo | null>(null)
// 网站部署的登录状态：checking → authenticated / anonymous（桌面版与未开启登录时直接放行）
const authState = ref<'checking' | 'authenticated' | 'anonymous'>('checking')
const authUser = ref<AuthUser | null>(null)

async function checkAuth() {
  try {
    const health = await healthInfo().catch(() => ({}) as Record<string, unknown>)
    if (!(health as { auth_required?: boolean }).auth_required) {
      authState.value = 'authenticated'
      return
    }
    const user = await authMe()
    if (user) {
      authUser.value = user
      authState.value = 'authenticated'
    } else {
      authState.value = 'anonymous'
    }
  } catch {
    // 取不到状态时不阻塞使用：桌面版与离线开发本来就关闭登录
    authState.value = 'authenticated'
  }
}

function onAuthenticated(user: AuthUser) {
  authUser.value = user
  authState.value = 'authenticated'
  window.location.reload()
}

async function signOut() {
  await authLogout().catch(() => undefined)
  window.location.reload()
}
const desktopError = ref('')
const desktopAction = ref('')
const nav: { key: View; labelKey: string; icon: typeof ChatLineRound; section: string }[] = [
  { key: 'chat', labelKey: 'nav.chat', icon: ChatLineRound, section: 'workspace' },
  { key: 'services', labelKey: 'nav.services', icon: Grid, section: 'workspace' },
  { key: 'knowledge', labelKey: 'nav.knowledge', icon: FolderOpened, section: 'admin' },
  { key: 'plugins', labelKey: 'nav.plugins', icon: Connection, section: 'admin' },
  { key: 'mcp', labelKey: 'nav.mcp', icon: Connection, section: 'admin' },
  { key: 'account', labelKey: 'nav.account', icon: UserIcon, section: 'admin' },
  { key: 'settings', labelKey: 'nav.settings', icon: Setting, section: 'admin' },
]
const navSections = ['workspace', 'admin']
const viewLabel = computed(() => t(nav.find(item => item.key === workspace.view)?.labelKey || ''))
const modelLabel = computed(() => workspace.model === 'ollama' ? currentLocalModel.value || t('app.model.local') : ({ auto: t('app.model.auto'), qwen3: 'Qwen3', deepseek: 'DeepSeek' })[workspace.model])
const mobileNavOpen = ref(false)
const adminToken = ref(desktop ? '' : sessionStorage.getItem('campus-agent-admin-token') || '')
const health = ref<Health | null>(null)
const healthBusy = ref(false)
const healthError = ref('')
const historyError = ref('')
const historyBusy = ref(false)
const healthLabel = computed(() => healthBusy.value ? t('app.backend.checking') : health.value?.status === 'ok' ? t('app.backend.connected') : t('app.backend.disconnected'))

const messages = ref<Message[]>([])
const prompt = ref('')
const chatBusy = ref(false)
const chatAbort = ref<AbortController | null>(null)
const conversations = ref<ConversationSummary[]>([])
const conversationsBusy = ref(false)
const conversationsError = ref('')
const historyQuery = ref('')
const historyResults = ref<ConversationSearchResult[]>([])
const historySearchBusy = ref(false)
const historySearchError = ref('')
const historySelectMode = ref(false)
const historySelected = ref<string[]>([])
let historySearchTimer: ReturnType<typeof setTimeout> | undefined
let historySearchToken = 0
const historyOpen = ref(typeof window !== 'undefined' && window.matchMedia('(min-width: 900px)').matches)
const streamingMessage = computed(() => {
  const last = messages.value[messages.value.length - 1]
  return last && last.role === 'assistant' && last.streaming ? last : null
})
const chatEnd = ref<HTMLElement | null>(null)
const chatSuggestions = computed(() => [t('chat.suggestion.card'), t('chat.suggestion.schedule'), t('chat.suggestion.repair')])

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
const reasoningLabel = computed(() => t(workspace.reasoning === 'deep' ? 'chat.reasoningDeep' : 'chat.reasoningFast'))
const reasoningHint = computed(() => t('chat.reasoningTip', { level: reasoningLabel.value, desc: t(workspace.reasoning === 'deep' ? 'chat.reasoningDeepDesc' : 'chat.reasoningFastDesc') }))
function setReasoning(value: unknown) {
  workspace.setReasoning(value === 'deep' ? 'deep' : 'fast')
}
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

const markdownCache = new WeakMap<Message, { text: string; html: string }>()

function markdownHtml(message: Message) {
  const cached = markdownCache.get(message)
  if (cached && cached.text === message.text) return cached.html
  const html = renderMarkdown(message.text)
  markdownCache.set(message, { text: message.text, html })
  return html
}

function onMarkdownClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  const anchor = target?.closest ? target.closest('a') : null
  if (!anchor) return
  event.preventDefault()
  const href = anchor.getAttribute('href') || ''
  if (/^https?:\/\//i.test(href)) void openSourceUrl(href)
}

const lastAssistantIndex = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].role === 'assistant') return i
  }
  return -1
})

async function copyAnswer(message: Message) {
  const text = message.text || ''
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(t('chat.copied'))
  } catch {
    const area = document.createElement('textarea')
    area.value = text
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(area)
    if (ok) ElMessage.success(t('chat.copied'))
    else ElMessage.warning(t('chat.copyFailed'))
  }
}

async function syncMessageIds() {
  if (!workspace.conversationId) return
  try {
    const result = await api.conversation(workspace.conversationId)
    if (result.messages.length !== messages.value.length) return
    result.messages.forEach((row, index) => {
      const local = messages.value[index]
      if (!local) return
      if (typeof row.id === 'number') local.id = row.id
      if (row.feedback === 'up' || row.feedback === 'down') local.feedback = row.feedback
    })
  } catch { /* 同步消息 ID 是尽力而为 */ }
}

async function submitFeedback(message: Message, value: 'up' | 'down') {
  if (chatBusy.value) return
  if (message.id === undefined) await syncMessageIds()
  if (message.id === undefined || !workspace.conversationId) { ElMessage.warning(t('chat.feedbackFailed')); return }
  const next = message.feedback === value ? null : value
  const previous = message.feedback
  message.feedback = next || undefined
  try {
    await api.setFeedback(workspace.conversationId, message.id, next)
  } catch {
    message.feedback = previous
    ElMessage.warning(t('chat.feedbackFailed'))
  }
}

function notifyAnswerReady() {
  // 桌面端：窗口不在前台时用系统通知提醒回答完成；网页端需浏览器授权，未授权时静默跳过。
  if (!desktop || !document.hidden || typeof Notification === 'undefined') return
  try {
    new Notification('Mens', { body: t('chat.notifyDone') })
  } catch { /* 系统通知不可用时静默忽略 */ }
}

const paletteOpen = ref(false)
const composerRef = ref<HTMLTextAreaElement | null>(null)
const slashDismissed = ref(false)
const slashActive = ref(0)

const currentConversation = computed(() => conversations.value.find(item => item.id === workspace.conversationId))

const paletteCommands = computed(() => {
  const items: { id: string; label: string; hint?: string }[] = [
    { id: 'new', label: t('cmd.new'), hint: t('cmd.newHint') },
    { id: 'history', label: t('cmd.history'), hint: t('cmd.historyHint') },
    { id: 'focus', label: t('cmd.focus'), hint: t('cmd.focusHint') },
    { id: 'quick', label: t('cmd.quick'), hint: t('cmd.quickHint') },
    { id: 'onboarding', label: t('cmd.onboarding'), hint: t('cmd.onboardingHint') },
    { id: 'theme', label: t('cmd.themeToggle'), hint: t('cmd.themeToggleHint') },
  ]
  if (currentConversation.value) {
    items.push({ id: 'export-md', label: t('cmd.exportMd'), hint: t('cmd.exportMdHint') })
    items.push({ id: 'export-json', label: t('cmd.exportJson'), hint: t('cmd.exportJsonHint') })
  }
  for (const item of nav) items.push({ id: `view:${item.key}`, label: t(item.labelKey), hint: t('palette.viewHint') })
  return items
})

function toggleTheme() {
  workspace.setAppearance(workspace.appearance === 'dark' ? 'light' : 'dark')
}

function runPaletteCommand(id: string) {
  if (id === 'new') { newConversation(); return }
  if (id === 'history') { historyOpen.value = true; return }
  if (id === 'focus') { void nextTick(() => composerRef.value?.focus()); return }
  if (id === 'quick') { quickOpen.value = true; return }
  if (id === 'onboarding') { onboardingOpen.value = true; return }
  if (id === 'theme') { toggleTheme(); return }
  if (id === 'export-md' || id === 'export-json') {
    if (currentConversation.value) void exportConversation(currentConversation.value, id === 'export-md' ? 'md' : 'json')
    return
  }
  if (id.startsWith('view:')) selectView(id.slice(5) as View)
}

function onGlobalKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    quickOpen.value = true
    return
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    paletteOpen.value = !paletteOpen.value
  }
}

const slashOptions = computed(() => (slashDismissed.value ? [] : matchSlashCommands(SLASH_COMMANDS, prompt.value)))

function onPromptInput() {
  slashDismissed.value = false
  slashActive.value = 0
}

function runSlashCommand(id: string) {
  prompt.value = ''
  slashDismissed.value = false
  slashActive.value = 0
  if (id === 'new') newConversation()
  else if (id === 'history') historyOpen.value = true
  else if (id === 'export') { if (currentConversation.value) void exportConversation(currentConversation.value, 'md') }
  else if (id === 'theme') toggleTheme()
}

const attachments = ref<ChatAttachment[]>([])
const dragActive = ref(false)
const attachInput = ref<HTMLInputElement | null>(null)
const quickOpen = ref(false)
const onboardingOpen = ref(false)
const attachAccept = attachmentAccept()

function attachmentWarn(key: string, params?: Record<string, string>) {
  ElMessage.warning(t(key, params))
}

async function addAttachments(files: FileList | File[]) {
  for (const file of Array.from(files)) {
    if (attachments.value.length >= ATTACHMENT_MAX_COUNT) {
      attachmentWarn('chat.attachTooMany', { count: String(ATTACHMENT_MAX_COUNT) })
      return
    }
    const kind = attachmentKind(file.name)
    if (kind === 'reject') { attachmentWarn('chat.attachType', { name: file.name }); continue }
    try {
      if (kind === 'text') {
        const text = await file.text()
        const problem = attachmentTextProblem(text)
        if (problem) { attachmentWarn(problem, { name: file.name }); continue }
        attachments.value.push({ name: file.name, text })
      } else {
        const result = await api.extractAttachment(file)
        if (!result.text.trim()) { attachmentWarn('chat.attachEmpty', { name: file.name }); continue }
        attachments.value.push({ name: result.name || file.name, text: result.text })
      }
    } catch (error) {
      attachmentWarn('chat.attachFailed', { name: file.name, error: friendlyError(error) })
    }
  }
}

function removeAttachment(index: number) {
  attachments.value.splice(index, 1)
}

function onComposerDragOver() {
  dragActive.value = true
}

function onComposerDragLeave(event: DragEvent) {
  const next = event.relatedTarget as Node | null
  if (next && (event.currentTarget as HTMLElement).contains(next)) return
  dragActive.value = false
}

function onComposerDrop(event: DragEvent) {
  dragActive.value = false
  const files = event.dataTransfer?.files
  if (files?.length) void addAttachments(files)
}

function onComposerPaste(event: ClipboardEvent) {
  const files = event.clipboardData?.files
  if (files?.length) {
    event.preventDefault()
    void addAttachments(files)
  }
}

function onAttachPick(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files?.length) void addAttachments(input.files)
  input.value = ''
}

async function submitQuickAsk(question: string) {
  if (chatBusy.value) { ElMessage.warning(t('quick.busy')); return }
  selectView('chat')
  await nextTick()
  await sendChat(question)
}

function completeOnboarding() {
  onboardingOpen.value = false
  try { localStorage.setItem('mens-onboarding-done', '1') } catch { /* 隐私模式忽略 */ }
}

function selectView(view: View) {
  workspace.view = view
  mobileNavOpen.value = false
  if (view === 'knowledge') void loadDocuments()
  if (view === 'plugins') void loadPlugins()
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
    conversationsError.value = t('history.loadError', { error: friendlyError(error) })
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
    await ElMessageBox.confirm(t('history.confirmDelete', { title: item.title }), t('history.confirmDeleteTitle'), { type: 'warning', confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel') })
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
    await ElMessageBox.confirm(t('history.confirmClear', { count: conversations.value.length }), t('history.confirmClearTitle'), { type: 'warning', confirmButtonText: t('history.clear'), cancelButtonText: t('common.cancel') })
  } catch { return }
  try {
    await api.clearConversations(workspace.clientId)
    newConversation()
    await loadConversations()
  } catch (error) {
    ElMessage.error(friendlyError(error))
  }
}

const historySearchActive = computed(() => historyQuery.value.trim().length > 0)

function onHistorySearchInput() {
  clearTimeout(historySearchTimer)
  historySearchTimer = setTimeout(() => { void runHistorySearch() }, 300)
}

async function runHistorySearch() {
  const query = historyQuery.value.trim()
  if (!query) { historyResults.value = []; historySearchError.value = ''; return }
  const token = ++historySearchToken
  historySearchBusy.value = true
  historySearchError.value = ''
  try {
    const results = await api.searchConversations(workspace.clientId, query)
    if (token === historySearchToken) historyResults.value = results
  } catch (error) {
    if (token === historySearchToken) historySearchError.value = t('history.searchFailed', { error: friendlyError(error) })
  } finally {
    if (token === historySearchToken) historySearchBusy.value = false
  }
}

function clearHistorySearch() {
  historyQuery.value = ''
  historyResults.value = []
  historySearchError.value = ''
}

function onHistoryItemClick(item: ConversationSummary) {
  if (historySelectMode.value) {
    const index = historySelected.value.indexOf(item.id)
    if (index >= 0) historySelected.value.splice(index, 1)
    else historySelected.value.push(item.id)
    return
  }
  void openConversation(item.id)
}

function openHistoryResult(result: ConversationSearchResult) {
  clearHistorySearch()
  void openConversation(result.conversation_id)
}

function toggleHistorySelect() {
  historySelectMode.value = !historySelectMode.value
  historySelected.value = []
}

async function renameConversation(item: ConversationSummary) {
  if (chatBusy.value) return
  let title = ''
  try {
    const result = await ElMessageBox.prompt(t('history.renamePrompt'), t('history.renameTitle'), {
      inputValue: item.title,
      inputValidator: (value: string) => (value ?? '').length <= 120 || t('history.renameTooLong'),
    })
    title = (result.value || '').trim()
  } catch { return }
  try {
    await api.updateConversation(item.id, workspace.clientId, { title })
    ElMessage.success(t('history.renamed'))
    await loadConversations()
  } catch (error) {
    ElMessage.error(friendlyError(error))
  }
}

async function togglePinConversation(item: ConversationSummary) {
  if (chatBusy.value) return
  try {
    await api.updateConversation(item.id, workspace.clientId, { pinned: !item.pinned })
    await loadConversations()
  } catch (error) {
    ElMessage.error(friendlyError(error))
  }
}

async function batchDeleteConversations() {
  if (chatBusy.value || !historySelected.value.length) return
  const count = historySelected.value.length
  try {
    await ElMessageBox.confirm(t('history.confirmBatchDelete', { count }), t('history.confirmBatchDeleteTitle'), { type: 'warning', confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel') })
  } catch { return }
  try {
    await api.batchDeleteConversations(historySelected.value, workspace.clientId)
    if (workspace.conversationId && historySelected.value.includes(workspace.conversationId)) newConversation()
    ElMessage.success(t('history.deletedSelected', { count }))
    historySelectMode.value = false
    historySelected.value = []
    await loadConversations()
  } catch (error) {
    ElMessage.error(friendlyError(error))
  }
}

function onHistoryCommand(item: ConversationSummary, command: string) {
  if (command === 'rename') void renameConversation(item)
  else if (command === 'pin') void togglePinConversation(item)
  else if (command === 'md' || command === 'json') void exportConversation(item, command)
  else if (command === 'delete') void deleteConversation(item)
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
    messages.value = result.messages.map(message => ({ role: message.role, text: message.content, sources: message.sources, tools: message.tool_calls?.map(call => call.name), demo: message.mode === 'demo', stopped: Boolean(message.partial), thinking: message.thinking || undefined, id: typeof message.id === 'number' ? message.id : undefined, feedback: message.feedback === 'up' || message.feedback === 'down' ? message.feedback : undefined }))
    scrollChat()
  } catch (error) { historyError.value = t('history.loadErrorHint', { error: friendlyError(error) }) }
  finally { historyBusy.value = false }
}

async function streamAnswer(text: string, options: { pushUser: boolean; reasoning: 'fast' | 'deep'; regenerate?: boolean; attachments?: ChatAttachment[] }) {
  const useWeb = workspace.webSearch && webAvailable.value
  // 带附件时，正文（含 [附件] 后缀）一并作为消息内容发送，保证落库、刷新与气泡展示一致。
  const display = options.attachments?.length ? `${text}\n\n${attachmentSuffix(options.attachments.map(item => item.name))}` : text
  if (options.pushUser) {
    messages.value.push({ role: 'user', text: display })
    prompt.value = ''
  }
  const index = messages.value.push({ role: 'assistant', text: '', streaming: true }) - 1
  const assistant = messages.value[index]
  chatBusy.value = true
  const controller = new AbortController()
  chatAbort.value = controller
  scrollChat()
  try {
    const answer = await chatStream(
      { message: display, conversationId: workspace.conversationId, model: workspace.model, localModel: currentLocalModel.value, clientId: workspace.clientId, web: useWeb, reasoning: options.reasoning, regenerate: options.regenerate, attachments: options.attachments },
      {
        onMeta: id => { if (id) workspace.setConversationId(id) },
        onThinking: chunk => {
          assistant.thinking = (assistant.thinking || '') + chunk
          if (!assistant.text) assistant.thinkingOpen = true
          scrollChat()
        },
        onDelta: chunk => {
          if (!assistant.text) assistant.thinkingOpen = false
          assistant.text += chunk
          scrollChat()
        },
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
    notifyAnswerReady()
  } catch (error) {
    if (controller.signal.aborted) {
      assistant.stopped = true
      if (!assistant.text.trim()) {
        assistant.text = t('chat.stopped')
        if (options.pushUser && !prompt.value.trim()) prompt.value = text
      }
    } else if (error instanceof ChatStreamError) {
      assistant.error = true
      assistant.note = error.message
      if (error.partial) assistant.text = error.partial
      if (options.pushUser && !assistant.text.trim() && !prompt.value.trim()) prompt.value = text
    } else {
      const message = friendlyError(error)
      assistant.error = true
      if (assistant.text.trim()) assistant.note = message
      else {
        assistant.text = message
        if (options.pushUser && !prompt.value.trim()) prompt.value = text
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

async function sendChat(value = prompt.value) {
  const text = value.trim()
  if (!workspace.ready || !text || chatBusy.value || historyBusy.value || historyError.value) return
  if (localChatProblem.value) { ElMessage.warning(localChatProblem.value); return }
  const pending = attachments.value.slice()
  attachments.value = []
  await streamAnswer(text, { pushUser: true, reasoning: workspace.reasoning, attachments: pending })
}

async function regenerateMessage(forceDeep = false) {
  if (!workspace.ready || chatBusy.value || historyBusy.value || historyError.value) return
  if (localChatProblem.value) { ElMessage.warning(localChatProblem.value); return }
  let assistantIndex = -1
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].role === 'assistant') { assistantIndex = i; break }
  }
  if (assistantIndex < 0) return
  let userIndex = -1
  for (let i = assistantIndex - 1; i >= 0; i--) {
    if (messages.value[i].role === 'user') { userIndex = i; break }
  }
  if (userIndex < 0 || !messages.value[userIndex].text.trim()) return
  const text = messages.value[userIndex].text
  messages.value.splice(userIndex + 1)
  await streamAnswer(text, { pushUser: false, reasoning: forceDeep ? 'deep' : workspace.reasoning, regenerate: true })
}

function onChatKeydown(event: KeyboardEvent) {
  if (slashOptions.value.length) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      slashActive.value = (slashActive.value + 1) % slashOptions.value.length
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      slashActive.value = (slashActive.value - 1 + slashOptions.value.length) % slashOptions.value.length
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      slashDismissed.value = true
      return
    }
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault()
      const option = slashOptions.value[slashActive.value]
      if (option) runSlashCommand(option.id)
      return
    }
  }
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
  const files = Array.from(input.files || [])
  if (!files.length || docAction.value) { input.value = ''; return }
  const accepted = files.filter(file => validDocument(file))
  if (!accepted.length) { input.value = ''; return }
  docAction.value = 'upload'
  let uploaded = 0
  const problems: string[] = []
  try {
    for (const file of accepted) {
      try {
        const result = await api.uploadDocument(file)
        uploaded += 1
        if (result.warning) problems.push(`${file.name}：${result.warning}`)
      } catch (error) {
        problems.push(`${file.name}：${friendlyError(error)}`)
      }
    }
    await loadDocuments()
    if (uploaded && !problems.length) ElMessage.success(accepted.length > 1 ? `已上传 ${uploaded} 份文档` : '文档已上传')
    else if (uploaded) ElMessage.warning(`已上传 ${uploaded} 份；其余失败——${problems.join('；')}`)
    else ElMessage.error(`上传失败——${problems.join('；')}`)
  } finally { docAction.value = ''; input.value = '' }
}

async function importDocumentUrl() {
  if (docAction.value) return
  let value = ''
  try {
    const answer = await ElMessageBox.prompt(
      '填写要导入知识库的公开网页地址（https://）。导入后正文会保存为本机文档，可离线检索。',
      '导入网页',
      { confirmButtonText: '导入', cancelButtonText: '取消', inputPlaceholder: 'https://www.example.edu/notice/123',
        inputPattern: /^https:\/\/\S+$/, inputErrorMessage: '地址必须以 https:// 开头' })
    value = String(answer.value || '').trim()
  } catch { return }
  docAction.value = 'import-url'
  try {
    const imported = await api.importDocumentUrl(value)
    await loadDocuments()
    ElMessage.success(`已导入：${imported.filename}`)
  } catch (error) { ElMessage.error(`导入失败：${friendlyError(error)}`) }
  finally { docAction.value = '' }
}

async function exportConversation(item: ConversationSummary, format: string) {
  if (historyBusy.value) return
  const kind = format === 'json' ? 'json' : 'md'
  historyBusy.value = true
  historyError.value = ''
  try {
    const { blob, name } = await api.exportConversation(item.id, kind)
    if (desktop) {
      const bytes = new Uint8Array(await blob.arrayBuffer())
      const result = await desktop.saveExport(name, bytes)
      if (result.saved) ElMessage.success(t('history.exported', { path: result.path || name }))
      else ElMessage.info(t('history.exportCancelled'))
    } else {
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = name
      link.click()
      URL.revokeObjectURL(url)
      ElMessage.success(t('history.downloadStarted', { name }))
    }
  } catch (error) { ElMessage.error(t('history.exportFailed', { error: friendlyError(error) })) }
  finally { historyBusy.value = false }
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
  await checkAuth()
  applyLocale()
  window.addEventListener('keydown', onGlobalKeydown)
  void loadHealth()
  void loadWebStatus()
  void loadDesktopInfo()
  await workspace.initialize()
  try { if (!localStorage.getItem('mens-onboarding-done')) onboardingOpen.value = true } catch { /* 隐私模式忽略 */ }
  void loadModelConfig()
  void loadLocalModels()
  void restoreConversation()
  void loadConversations()
  if (workspace.view === 'knowledge') void loadDocuments()
  if (workspace.view === 'plugins') void loadPlugins()
  if (workspace.view === 'settings') { void loadModelConfig(); void loadLocalModels(); void loadCampusSources(); void loadWebStatus() }
})

onUnmounted(() => {
  if (downloadTimer) clearTimeout(downloadTimer)
  systemAppearance.removeEventListener('change', updateAppearance)
  window.removeEventListener('keydown', onGlobalKeydown)
})
</script>

<template>
  <LoginView v-if="authState === 'anonymous'" @authenticated="onAuthenticated" />
  <div v-else-if="authState === 'checking'" class="auth-checking">{{ t('auth.checking') }}</div>
  <div v-else class="app-shell" :class="{ 'desktop-app': desktop }">
    <CommandPalette v-model:open="paletteOpen" :items="paletteCommands" @select="runPaletteCommand" />
    <QuickAsk v-model:open="quickOpen" @submit="submitQuickAsk" />
    <OnboardingModal v-model:open="onboardingOpen" @done="completeOnboarding" />
    <div v-if="mobileNavOpen" class="mobile-scrim" @click="mobileNavOpen = false" />
    <aside class="sidebar" :class="{ 'sidebar-open': mobileNavOpen }">
      <div class="brand">
        <img class="brand-mark" :src="mensLogo" alt="" />
        <span><strong>Mens</strong><small>{{ desktop ? t('app.tagline.desktop') : t('app.tagline.web') }}</small></span>
      </div>
      <div class="side-content">
        <template v-for="section in navSections" :key="section">
          <div class="nav-section">{{ t('nav.' + section) }}</div>
          <button v-for="item in nav.filter(entry => entry.section === section)" :key="item.key" class="nav-item" :class="{ active: workspace.view === item.key }" @click="selectView(item.key)">
            <el-icon :size="18"><component :is="item.icon" /></el-icon><span>{{ t(item.labelKey) }}</span>
          </button>
        </template>
      </div>
      <div class="side-footer">
        <div class="connection-dot" :class="{ demo: !health }" />
        <span>{{ healthLabel }}</span>
        <button v-if="authUser && !desktop" class="side-logout" :title="t('auth.signedIn', { name: authUser.username })" @click="signOut">{{ t('auth.logout') }}</button>
        <span class="side-version">{{ desktop ? (desktopInfo ? `v${desktopInfo.version}` : t('app.version.desktop')) : `v${frontendVersion}` }}</span>
      </div>
    </aside>

    <div class="main-shell">
      <header class="topbar">
        <button class="mobile-menu icon-button" :aria-label="t('app.menu')" @click="mobileNavOpen = true"><el-icon :size="20"><Grid /></el-icon></button>
        <div class="breadcrumb"><span>Mens</span><el-icon><ArrowRight /></el-icon><strong>{{ viewLabel }}</strong></div>
        <div class="top-actions"><el-tooltip :content="t('palette.hint')" placement="bottom"><el-button class="palette-button" text :icon="Search" :aria-label="t('palette.title')" @click="paletteOpen = true" /></el-tooltip><span class="mode-chip" :class="{ demo: !health }">{{ healthLabel }}</span><span class="model-chip" :title="modelLabel">{{ modelLabel }}</span></div>
      </header>

      <main class="main-content" :class="{ 'chat-main': workspace.view === 'chat' }">
        <section v-if="workspace.view === 'chat'" class="chat-view" :class="{ 'history-open': historyOpen }">
          <div class="page-heading chat-heading"><div><div class="eyebrow">MENS ASSISTANT</div><h1>{{ t('nav.chat') }}</h1></div><div class="chat-actions"><div class="chat-model-picker"><el-select :model-value="chatModel" :aria-label="t('chat.modelPicker')" :disabled="!workspace.ready || chatBusy" @update:model-value="selectChatModel" @visible-change="($event: boolean) => { if ($event) loadLocalModels() }"><el-option-group :label="t('chat.modelCloud')"><el-option value="auto" :label="t('app.model.auto')" /><el-option value="qwen3" label="Qwen3" /><el-option value="deepseek" label="DeepSeek" /></el-option-group><el-option-group :label="t('chat.modelLocal')"><el-option v-if="workspace.model === 'ollama' && !installedLocalModel" :value="`local:${currentLocalModel}`" :label="currentLocalModel || t('app.model.local')" disabled /><el-option v-for="item in localModels?.installed || []" :key="item.name" :value="`local:${item.name}`" :label="item.name" :disabled="!localModels?.running" /><el-option v-if="!localModels?.installed.length && workspace.model !== 'ollama'" value="unavailable" :label="localBusy ? t('chat.localChecking') : localModels?.running ? t('chat.localNone') : t('chat.ollamaOffline')" disabled /></el-option-group></el-select><el-tooltip :content="t('chat.refreshLocal')"><el-button :icon="Refresh" plain :loading="localBusy" :disabled="chatBusy" :aria-label="t('chat.refreshLocal')" @click="loadLocalModels" /></el-tooltip></div><el-button :icon="Clock" :type="historyOpen ? 'primary' : 'default'" plain :aria-pressed="historyOpen" @click="historyOpen = !historyOpen">{{ t('chat.history') }}</el-button><el-button :icon="Plus" :disabled="!workspace.ready || chatBusy || historyBusy" @click="newConversation">{{ t('chat.new') }}</el-button></div></div>
          <div class="chat-body">
            <aside v-show="historyOpen" class="history-panel" :aria-label="t('history.title')">
              <div class="history-head"><strong>{{ t('history.title') }}</strong><span class="history-count">{{ conversations.length }}</span><el-button text :icon="Refresh" :loading="conversationsBusy" :aria-label="t('history.refresh')" @click="loadConversations" /><el-button text :disabled="!conversations.length || chatBusy" @click="clearConversations">{{ t('history.clear') }}</el-button></div>
              <div class="history-tools"><el-input v-model="historyQuery" size="small" clearable :prefix-icon="Search" :placeholder="t('history.searchPlaceholder')" :aria-label="t('history.searchPlaceholder')" @input="onHistorySearchInput" @keydown.enter="runHistorySearch" @clear="clearHistorySearch" /><el-button text size="small" :type="historySelectMode ? 'primary' : ''" :disabled="chatBusy" @click="toggleHistorySelect">{{ historySelectMode ? t('history.selectExit') : t('history.select') }}</el-button></div>
              <div v-if="historySelectMode" class="history-select-bar"><span>{{ t('history.selected', { count: historySelected.length }) }}</span><el-button text type="danger" size="small" :disabled="!historySelected.length || chatBusy" @click="batchDeleteConversations">{{ t('history.deleteSelected') }}</el-button></div>
              <p v-if="conversationsError && !historySearchActive" class="history-error">{{ conversationsError }}</p>
              <div class="history-list" v-loading="conversationsBusy || historySearchBusy">
                <p v-if="historySearchError" class="history-error">{{ historySearchError }}</p>
                <p v-if="historySearchActive && !historySearchBusy && !historySearchError && !historyResults.length" class="history-empty">{{ t('history.searchEmpty') }}</p>
                <template v-if="historySearchActive">
                  <div v-for="result in historyResults" :key="result.conversation_id" class="history-item search-item" role="button" tabindex="0" @click="openHistoryResult(result)" @keydown.enter="openHistoryResult(result)">
                    <div class="history-item-main"><strong>{{ result.title }}</strong><small>{{ result.snippet }}</small></div>
                  </div>
                </template>
                <template v-else>
                <p v-if="!conversationsBusy && !conversationsError && conversations.length === 0" class="history-empty">{{ t('history.empty') }}<br />{{ t('history.emptyHint') }}</p>
                <div v-for="item in conversations" :key="item.id" class="history-item" :class="{ active: item.id === workspace.conversationId, disabled: chatBusy, selected: historySelected.includes(item.id) }" role="button" tabindex="0" :aria-disabled="chatBusy" @click="onHistoryItemClick(item)" @keydown.enter="onHistoryItemClick(item)">
                  <el-checkbox v-if="historySelectMode" class="history-check" :model-value="historySelected.includes(item.id)" :disabled="chatBusy" @click.stop @change="onHistoryItemClick(item)" />
                  <div class="history-item-main"><strong><span v-if="item.pinned" class="pin-badge">{{ t('history.pinned') }}</span>{{ item.title }}</strong><small>{{ t('history.count', { count: item.message_count }) }} · {{ chatTime(item.updated_at) }}</small></div>
                  <el-dropdown v-if="!historySelectMode" class="history-menu" trigger="click" @command="(command: string) => onHistoryCommand(item, command)" @click.stop>
                    <el-button class="history-more" text :icon="MoreFilled" :disabled="chatBusy" :aria-label="t('history.more', { title: item.title })" />
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="rename" :icon="EditPen">{{ t('history.rename') }}</el-dropdown-item>
                        <el-dropdown-item command="pin" :icon="item.pinned ? Bottom : Top">{{ item.pinned ? t('history.unpin') : t('history.pin') }}</el-dropdown-item>
                        <el-dropdown-item command="md" :icon="Download" divided>{{ t('history.exportMarkdown') }}</el-dropdown-item>
                        <el-dropdown-item command="json" :icon="Download">{{ t('history.exportJson') }}</el-dropdown-item>
                        <el-dropdown-item command="delete" :icon="Delete" divided>{{ t('common.delete') }}</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
                </template>
              </div>
            </aside>
            <div class="chat-column">
          <div class="conversation" aria-live="polite">
            <el-alert v-if="historyError" :title="historyError" type="error" show-icon :closable="false"><el-button text @click="restoreConversation">{{ t('chat.retry') }}</el-button></el-alert>
            <el-alert v-if="localChatProblem" :title="localChatProblem" type="warning" show-icon :closable="false"><el-button text @click="selectView('settings')">{{ t('chat.modelSettings') }}</el-button></el-alert>
            <div v-if="!workspace.ready || historyBusy" class="history-loading">{{ t('chat.restoring') }}</div>
            <div v-if="workspace.ready && messages.length === 0 && !historyBusy && !historyError" class="chat-empty">
              <div class="empty-symbol"><img :src="mensLogo" alt="Mens" /></div>
              <h2>{{ t('chat.title') }}</h2>
              <div class="suggestions"><button v-for="suggestion in chatSuggestions" :key="suggestion" @click="sendChat(suggestion)">{{ suggestion }}<el-icon><ArrowRight /></el-icon></button></div>
            </div>
            <div v-for="(message, index) in messages" :key="index" class="message-row" :class="message.role">
              <div class="message-avatar"><template v-if="message.role === 'user'">我</template><img v-else :src="mensLogo" alt="" /></div>
              <div class="message-body"><div class="message-author">{{ message.role === 'user' ? '你' : 'Mens' }}<span v-if="message.demo" class="inline-demo">演示回答</span><span v-if="message.error" class="inline-demo">请求失败</span><span v-if="message.stopped" class="inline-demo">已停止</span></div><div class="message-text"><template v-if="message.role === 'assistant'"><div v-if="message.thinking" class="thinking-block"><button type="button" class="thinking-toggle" :aria-expanded="Boolean(message.thinkingOpen)" @click="message.thinkingOpen = !message.thinkingOpen"><el-icon :size="10"><ArrowDown v-if="message.thinkingOpen" /><ArrowRight v-else /></el-icon>{{ message.thinkingOpen ? t('chat.hideThinking') : t('chat.showThinking') }}</button><pre v-if="message.thinkingOpen" class="thinking-text">{{ message.thinking }}<span v-if="message.streaming && !message.text" class="stream-caret" /></pre></div><div class="markdown-body" @click="onMarkdownClick" v-html="markdownHtml(message)"></div></template><template v-else>{{ message.text }}</template><span v-if="message.streaming && message.text" class="stream-caret" /></div><p v-if="message.note" class="message-note">{{ message.note }}</p>
                <div v-if="message.tools?.length" class="tool-note"><el-icon><Connection /></el-icon> 已调用 {{ message.tools.join('、') }}</div>
                <div v-if="message.sources?.length" class="source-list"><div class="source-label">{{ message.sources.some(source => source.kind === 'web') ? t('chat.sourceLabelWeb') : t('chat.sourceLabel') }}</div><div v-for="(source, sourceIndex) in message.sources" :key="sourceIndex" class="source-item"><el-icon><Link v-if="source.kind === 'web'" /><Document v-else /></el-icon><div><strong>{{ source.title || source.source }}</strong><small v-if="source.snippet">{{ source.snippet }}</small><small v-if="source.url" class="source-url"><a v-if="!desktop" :href="source.url" target="_blank" rel="noopener noreferrer">{{ sourceHost(source.url) }} ↗</a><button v-else type="button" class="link-button" @click="openSourceUrl(source.url)">{{ sourceHost(source.url) }} ↗</button></small></div></div></div>
                <div v-if="message.role === 'assistant' && message.text && !message.streaming" class="message-actions"><button type="button" class="message-action" @click="copyAnswer(message)">{{ t('chat.copy') }}</button><button v-if="index === lastAssistantIndex && !chatBusy" type="button" class="message-action" @click="regenerateMessage()">{{ t('chat.regenerate') }}</button><button v-if="index === lastAssistantIndex && !chatBusy && workspace.reasoning !== 'deep'" type="button" class="message-action" @click="regenerateMessage(true)">{{ t('chat.deepRetry') }}</button><button type="button" class="message-action" :class="{ active: message.feedback === 'up' }" :disabled="chatBusy" @click="submitFeedback(message, 'up')">{{ t('chat.helpful') }}</button><button type="button" class="message-action" :class="{ active: message.feedback === 'down' }" :disabled="chatBusy" @click="submitFeedback(message, 'down')">{{ t('chat.notHelpful') }}</button></div>
              </div>
            </div>
            <div v-if="chatBusy && !streamingMessage?.text && !streamingMessage?.thinking" class="message-row assistant"><div class="message-avatar"><img :src="mensLogo" alt="" /></div><div class="message-body"><div class="message-author">Mens</div><div class="typing"><span /><span /><span /></div></div></div>
            <div ref="chatEnd" />
          </div>
          <div class="composer-wrap" :class="{ 'drag-active': dragActive }" @dragover.prevent="onComposerDragOver" @dragleave="onComposerDragLeave" @drop.prevent="onComposerDrop"><div class="composer"><textarea v-model="prompt" ref="composerRef" rows="2" maxlength="4000" :disabled="!workspace.ready || historyBusy" :placeholder="t('chat.placeholder')" :aria-label="t('chat.placeholder')" @input="onPromptInput" @paste="onComposerPaste" @keydown="onChatKeydown" /><div v-if="slashOptions.length" class="slash-menu" role="listbox" :aria-label="t('palette.slashTitle')"><button v-for="(option, index) in slashOptions" :key="option.id" type="button" class="slash-item" :class="{ active: index === slashActive }" @mousedown.prevent="runSlashCommand(option.id)" @mousemove="slashActive = index"><strong>{{ option.slash }}</strong><small>{{ t(option.labelKey) }}</small></button></div><div v-if="attachments.length" class="attach-chips"><span v-for="(item, index) in attachments" :key="`${item.name}-${index}`" class="attach-chip"><el-icon :size="12"><Paperclip /></el-icon><span class="attach-name">{{ item.name }}</span><button type="button" class="attach-remove" :aria-label="t('chat.attachRemove', { name: item.name })" @click="removeAttachment(index)">×</button></span></div><div class="composer-bottom"><el-tooltip :content="webToggleHint" placement="top"><label class="web-toggle"><el-switch v-model="webSwitch" :disabled="!webAvailable || chatBusy" size="small" /><span>{{ t('chat.webToggle') }}</span></label></el-tooltip><span>{{ t('chat.disclaimer') }}</span><div class="composer-actions"><input ref="attachInput" type="file" class="hidden-input attach-input" multiple :accept="attachAccept" @change="onAttachPick" /><el-tooltip :content="t('chat.attachHint')" placement="top"><el-button class="attach-button" text :icon="Paperclip" :disabled="!workspace.ready || chatBusy" :aria-label="t('chat.attach')" @click="attachInput?.click()" /></el-tooltip><el-tooltip :content="reasoningHint" placement="top"><el-dropdown trigger="click" placement="top-end" :disabled="!workspace.ready || chatBusy" @command="setReasoning"><button type="button" class="reasoning-pill" :disabled="!workspace.ready || chatBusy" :aria-label="reasoningHint"><span>{{ reasoningLabel }}</span><el-icon class="reasoning-caret" :size="10"><ArrowDown /></el-icon></button><template #dropdown><el-dropdown-menu><el-dropdown-item command="fast"><div class="reasoning-option"><div class="reasoning-option-text"><strong>{{ t('chat.reasoningFast') }}</strong><small>{{ t('chat.reasoningFastDesc') }}</small></div><el-icon v-if="workspace.reasoning === 'fast'"><Check /></el-icon></div></el-dropdown-item><el-dropdown-item command="deep"><div class="reasoning-option"><div class="reasoning-option-text"><strong>{{ t('chat.reasoningDeep') }}</strong><small>{{ t('chat.reasoningDeepDesc') }}</small></div><el-icon v-if="workspace.reasoning === 'deep'"><Check /></el-icon></div></el-dropdown-item></el-dropdown-menu></template></el-dropdown></el-tooltip><el-button v-if="chatBusy" type="danger" plain :icon="CircleClose" @click="stopChat">{{ t('chat.stop') }}</el-button><el-button v-else type="primary" :icon="ArrowRight" :disabled="!workspace.ready || !prompt.trim() || historyBusy || Boolean(historyError) || Boolean(localChatProblem)" @click="sendChat()">{{ t('chat.send') }}</el-button></div></div></div></div>
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
              <el-empty v-if="!serviceBusy && serviceResult === null && activeService !== 'repair' && !serviceError" description="尚未查询，点击上方按钮获取数据" :image-size="72" />
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
          <div class="page-heading"><div><div class="eyebrow">KNOWLEDGE BASE</div><h1>知识库</h1><p>维护政策文件与办事指南，更新后可重建检索索引。</p></div><div class="heading-actions"><el-button :icon="Refresh" :loading="docAction === 'reindex'" @click="reindex">重建索引</el-button><el-button :icon="Link" :loading="docAction === 'import-url'" :disabled="Boolean(docAction)" @click="importDocumentUrl">导入网页</el-button><el-button type="primary" :icon="Upload" :loading="docAction === 'upload'" @click="uploadInput?.click()">上传文档</el-button><input ref="uploadInput" class="hidden-input" type="file" accept=".pdf,.md,.txt,.docx" multiple @change="onUpload" /></div></div>
          <div class="section-toolbar"><div><strong>文档列表</strong><span>{{ documents.length }} 份文档</span></div><el-button text :icon="Refresh" :loading="docsBusy" @click="loadDocuments">刷新</el-button></div>
          <el-alert v-if="docsError" class="alert" :title="docsError" type="error" show-icon :closable="false" />
          <p class="management-note">支持 PDF、Markdown、TXT、Word (.docx)，最大 5 MB。<template v-if="!desktop">管理操作需在「设置」填写管理员令牌。</template><template v-else>文档保存在本机应用数据目录。</template></p>
          <div class="data-panel"><el-empty v-if="!docsBusy && !docsError && documents.length === 0" description="暂无文档，上传政策文件开始使用" :image-size="96" /><el-table v-else v-loading="docsBusy" :data="documents" stripe><el-table-column label="文件" min-width="220"><template #default="scope"><div class="file-cell"><el-icon :size="18"><Document /></el-icon><span>{{ scope.row.filename }}</span></div></template></el-table-column><el-table-column label="文本长度" width="110"><template #default="scope">{{ scope.row.content?.length ?? '—' }}</template></el-table-column><el-table-column prop="updated_at" label="更新时间" min-width="170"><template #default="scope">{{ scope.row.updated_at ? String(scope.row.updated_at).slice(0, 16).replace('T', ' ') : '—' }}</template></el-table-column><el-table-column label="操作" width="165" fixed="right"><template #default="scope"><label class="table-action">更新<input type="file" accept=".pdf,.md,.txt" :disabled="Boolean(docAction)" @change="onReplace(scope.row.id, $event)" /></label><el-button link type="danger" :loading="docAction === scope.row.id" :disabled="Boolean(docAction)" @click="deleteDocument(scope.row)">删除</el-button></template></el-table-column></el-table></div>
        </section>

        <section v-else-if="workspace.view === 'plugins'" class="content-view">
          <div class="page-heading"><div><div class="eyebrow">MENS EXTENSIONS</div><h1>插件</h1><p>按需安装和管理可用工具。</p></div></div>
          <div class="install-band"><div><h2>GitHub 自定义安装</h2><p>输入 GitHub 仓库地址，将读取仓库根目录的插件清单 plugin.json；也支持 /tree/&lt;分支&gt; 链接与 HTTPS 清单地址。</p></div><div class="install-controls"><el-input v-model="pluginSource" placeholder="https://github.com/owner/repo" clearable @keyup.enter="installPlugin" /><el-button type="primary" :icon="Plus" :loading="pluginAction === 'install'" :disabled="!pluginSource.trim()" @click="installPlugin">安装</el-button></div></div>
          <details class="install-manifest"><summary>插件清单示例（仓库根目录 plugin.json）</summary><pre>{
  "name": "demo_search",
  "description": "示例插件：调用公开数据接口",
  "url": "https://api.example.com/search",
  "parameters": {
    "type": "object",
    "properties": { "query": { "type": "string", "minLength": 1, "maxLength": 200 } },
    "required": ["query"],
    "additionalProperties": false
  }
}</pre></details>
          <div class="section-toolbar"><div><strong>已安装插件</strong><span>{{ plugins.length }} 个</span></div><el-button text :icon="Refresh" :loading="pluginsBusy" @click="loadPlugins">刷新</el-button></div>
          <el-alert v-if="pluginsError" class="alert" :title="pluginsError" type="error" show-icon :closable="false" />
          <p v-if="!desktop" class="management-note">安装、启停和测试调用需在「设置」填写管理员令牌。</p>
          <div class="plugin-list" v-loading="pluginsBusy"><el-empty v-if="!pluginsBusy && !pluginsError && plugins.length === 0" description="尚未安装插件" :image-size="96" /><div v-for="plugin in plugins" :key="plugin.id" class="plugin-row"><div class="plugin-icon"><el-icon :size="20"><Connection /></el-icon></div><div class="plugin-info"><div><strong>{{ plugin.name }}</strong></div><p>{{ plugin.description || plugin.url || '自定义插件' }}</p></div><el-switch :model-value="plugin.enabled" :loading="pluginAction === plugin.id" :disabled="Boolean(pluginAction)" :aria-label="`${plugin.name} 启用状态`" @change="togglePlugin(plugin, Boolean($event))" /><el-button link type="primary" :disabled="!plugin.enabled || Boolean(pluginAction)" @click="openPluginTest(plugin)">测试调用</el-button><el-button link type="danger" :loading="pluginAction === plugin.id" :disabled="Boolean(pluginAction)" @click="removePlugin(plugin)">卸载</el-button></div></div>
          <div v-if="testPlugin" class="plugin-test"><div class="result-title"><h3>测试插件：{{ testPlugin.name }}</h3></div><p v-if="testPlugin.name === 'baidu_baike_search'">{{ desktop ? '输入词条关键词，搜索结果将在系统浏览器中打开。' : '输入词条关键词，生成链接后点击打开百度百科搜索结果。' }}</p><p v-else>参数将由后端发送至已注册服务 {{ testPlugin.url }}。</p><details v-if="testPlugin.parameters"><summary>查看参数定义</summary><pre>{{ JSON.stringify(testPlugin.parameters, null, 2) }}</pre></details><label class="field"><span>JSON 参数</span><el-input v-model="testParameters" type="textarea" :rows="5" :disabled="testBusy" /></label><div class="form-action"><el-button type="primary" :loading="testBusy" @click="invokePlugin">{{ testPlugin.name === 'baidu_baike_search' ? '搜索词条' : '发送测试请求' }}</el-button><el-button :disabled="testBusy" @click="testPlugin = null">关闭</el-button></div><el-alert v-if="testError" class="alert" :title="testError" type="error" show-icon :closable="false" /><a v-if="baikeUrl && !desktop" :href="baikeUrl" target="_blank" rel="noopener noreferrer">打开百度百科搜索结果</a><pre v-if="testResult !== null" class="plugin-result">{{ JSON.stringify(testResult, null, 2) }}</pre></div>
        </section>

        <section v-else-if="workspace.view === 'mcp'" class="content-view">
          <McpSettings :desktop="Boolean(desktop)" />
        </section>

        <section v-else-if="workspace.view === 'account'" class="content-view">
          <AccountSettings />
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
          <div class="settings-section"><div class="settings-copy"><h2>服务状态</h2><p>{{ healthLabel }}<template v-if="health"> · {{ health.rag_degraded ? t('chat.retrieval.degraded') : health.rag_enabled ? t('chat.retrieval.vector') : t('chat.retrieval.keyword') }} · {{ health.demo_services ? '校务服务为演示数据' : '已配置部分校务接口' }}</template></p></div><el-button :icon="Refresh" :loading="healthBusy" @click="loadHealth">刷新状态</el-button></div>
          <el-alert v-if="healthError" :title="healthError" type="error" show-icon :closable="false" />
        </section>
      </main>
    </div>
  </div>
</template>
