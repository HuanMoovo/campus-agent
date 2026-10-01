import { computed, ref } from 'vue'

/**
 * Interface language for the app itself.
 *
 * Chinese is the source language, so every key must exist in all three catalogues (a unit test
 * enforces that). Missing keys fall back to Chinese rather than showing a raw key, and the choice
 * is remembered per machine; the desktop shell and the web build share this module.
 */
export type Locale = 'zh' | 'en' | 'ja'
export type LocaleChoice = Locale | 'system'

const STORAGE_KEY = 'campus-agent-locale'

export const LOCALES: { value: LocaleChoice; label: string }[] = [
  { value: 'system', label: 'system' },
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
  { value: 'ja', label: '日本語' },
]

const zh = {
  'app.tagline.desktop': '桌面智能办事工作台',
  'app.tagline.web': '智能办事工作台',
  'app.menu': '打开导航',
  'app.backend.connected': '后端已连接',
  'app.backend.disconnected': '后端未连接',
  'app.backend.checking': '检查中',
  'app.version.desktop': '桌面版',
  'app.model.auto': '自动路由',
  'app.model.local': '本地模型',

  'nav.workspace': '工作区',
  'nav.admin': '管理',
  'nav.chat': '智能问答',
  'nav.services': '校园服务',
  'nav.knowledge': '知识库',
  'nav.plugins': '插件',
  'nav.settings': '设置',

  'chat.title': '今天需要办理什么？',
  'chat.suggestion.card': '补办校园一卡通需要什么材料？',
  'chat.suggestion.schedule': '查询我的本周课表',
  'chat.suggestion.repair': '学校的报修流程是什么？',
  'chat.placeholder': '输入问题…',
  'chat.send': '发送',
  'chat.stop': '停止生成',
  'chat.webToggle': '联网搜索',
  'chat.disclaimer': '回答仅供参考，请核对学校正式通知',
  'chat.restoring': '正在恢复对话…',
  'chat.retry': '重试恢复',
  'chat.modelSettings': '模型设置',
  'chat.retrieval.keyword': '本地关键词检索',
  'chat.retrieval.vector': '向量检索已启用',
  'chat.retrieval.degraded': '向量检索故障，已降级关键词检索',
  'chat.stopped': '已停止生成',
  'chat.history': '历史记录',
  'chat.new': '新对话',
  'chat.modelPicker': '聊天模型',
  'chat.modelCloud': '云端与自动路由',
  'chat.modelLocal': '本地 Ollama',
  'chat.localChecking': '正在检测…',
  'chat.localNone': '暂无已安装模型',
  'chat.ollamaOffline': 'Ollama 未连接',
  'chat.refreshLocal': '刷新本地模型',
  'chat.sourceLabel': '参考来源',
  'chat.sourceLabelWeb': '参考来源（含联网检索）',
  'chat.hero.lead': '一个基于本地知识库的校园办事助手：资料、会话与检索都在本机完成。',
  'chat.hero.hint': '拖动旋转 · 滚轮缩放',
  'chat.suggestions.title': '试试这样问',
  'chat.webUnavailableHint': '联网搜索当前不可用，请让管理员在设置中启用。',
  'chat.demo': '演示数据',

  'history.title': '历史对话',
  'history.empty': '暂无历史对话。',
  'history.emptyHint': '发送第一条消息后会自动保存。',
  'history.count': '{count} 条消息',
  'history.clear': '清空',
  'history.refresh': '刷新历史对话',
  'history.delete': '删除对话：{title}',
  'history.export': '导出对话：{title}',
  'history.exportMarkdown': '导出 Markdown',
  'history.exportJson': '导出 JSON',
  'history.loadError': '无法读取历史对话：{error}',
  'history.loadErrorHint': '{error} 可以重试恢复或开始新对话。',
  'history.exported': '对话已导出：{path}',
  'history.exportCancelled': '已取消导出。',
  'history.downloadStarted': '已开始下载 {name}',
  'history.exportFailed': '导出失败：{error}',
  'history.confirmDelete': '删除“{title}”后无法恢复，确定删除？',
  'history.confirmDeleteTitle': '删除历史对话',
  'history.confirmClear': '将删除全部 {count} 条历史对话，且无法恢复。确定清空？',
  'history.confirmClearTitle': '清空历史对话',

  'appearance.title': '外观',
  'appearance.reset': '恢复默认外观',
  'appearance.mode': '显示模式',
  'appearance.light': '浅色',
  'appearance.dark': '深色',
  'appearance.system': '跟随系统',
  'appearance.accent': '主题色',
  'appearance.presets': '预设主题色',
  'appearance.custom': '自定义主题色',
  'appearance.hex': '主题色十六进制值',
  'appearance.invalid': '请输入 #RRGGBB 格式的颜色值',
  'appearance.preset.green': '松绿',
  'appearance.preset.blue': '湖蓝',
  'appearance.preset.violet': '紫罗兰',
  'appearance.preset.rose': '玫红',
  'appearance.preset.amber': '琥珀',
  'appearance.preset.graphite': '石墨',
  'appearance.language': '语言',
  'appearance.languageHint': '界面语言；README 与项目介绍页同样提供三种语言。',

  'common.cancel': '取消',
  'common.delete': '删除',
  'common.confirm': '确定',
}

const en: Record<keyof typeof zh, string> = {
  'app.tagline.desktop': 'Desktop campus workbench',
  'app.tagline.web': 'Campus workbench',
  'app.menu': 'Open navigation',
  'app.backend.connected': 'Backend connected',
  'app.backend.disconnected': 'Backend unavailable',
  'app.backend.checking': 'Checking',
  'app.version.desktop': 'Desktop',
  'app.model.auto': 'Auto routing',
  'app.model.local': 'Local model',

  'nav.workspace': 'Workspace',
  'nav.admin': 'Manage',
  'nav.chat': 'Chat',
  'nav.services': 'Campus services',
  'nav.knowledge': 'Knowledge base',
  'nav.plugins': 'Plugins',
  'nav.settings': 'Settings',

  'chat.title': 'What can I help you with today?',
  'chat.suggestion.card': 'What do I need to replace a campus card?',
  'chat.suggestion.schedule': 'Show my timetable for this week',
  'chat.suggestion.repair': 'What is the campus repair request process?',
  'chat.placeholder': 'Type a question…',
  'chat.send': 'Send',
  'chat.stop': 'Stop generating',
  'chat.webToggle': 'Web search',
  'chat.disclaimer': 'Answers are for reference only — check the school’s official notices',
  'chat.restoring': 'Restoring the conversation…',
  'chat.retry': 'Retry',
  'chat.modelSettings': 'Model settings',
  'chat.retrieval.keyword': 'Local keyword search',
  'chat.retrieval.vector': 'Vector retrieval enabled',
  'chat.retrieval.degraded': 'Vector retrieval failed, using keyword search',
  'chat.stopped': 'Generation stopped',
  'chat.history': 'History',
  'chat.new': 'New chat',
  'chat.modelPicker': 'Chat model',
  'chat.modelCloud': 'Cloud and auto routing',
  'chat.modelLocal': 'Local Ollama',
  'chat.localChecking': 'Checking…',
  'chat.localNone': 'No installed models',
  'chat.ollamaOffline': 'Ollama offline',
  'chat.refreshLocal': 'Refresh local models',
  'chat.sourceLabel': 'Sources',
  'chat.sourceLabelWeb': 'Sources (including web search)',
  'chat.hero.lead': 'A campus assistant grounded in your local knowledge base: documents, conversations and retrieval all stay on this machine.',
  'chat.hero.hint': 'Drag to rotate · scroll to zoom',
  'chat.suggestions.title': 'Try asking',
  'chat.webUnavailableHint': 'Web search is unavailable right now; ask an administrator to enable it in Settings.',
  'chat.demo': 'Demo data',

  'history.title': 'Conversations',
  'history.empty': 'No conversations yet.',
  'history.emptyHint': 'Your first message is saved automatically.',
  'history.count': '{count} messages',
  'history.clear': 'Clear',
  'history.refresh': 'Refresh conversations',
  'history.delete': 'Delete conversation: {title}',
  'history.export': 'Export conversation: {title}',
  'history.exportMarkdown': 'Export Markdown',
  'history.exportJson': 'Export JSON',
  'history.loadError': 'Could not load conversations: {error}',
  'history.loadErrorHint': '{error} You can retry or start a new conversation.',
  'history.exported': 'Conversation exported: {path}',
  'history.exportCancelled': 'Export cancelled.',
  'history.downloadStarted': 'Downloading {name}',
  'history.exportFailed': 'Export failed: {error}',
  'history.confirmDelete': 'Delete “{title}”? This cannot be undone.',
  'history.confirmDeleteTitle': 'Delete conversation',
  'history.confirmClear': 'This deletes all {count} conversations and cannot be undone. Clear them?',
  'history.confirmClearTitle': 'Clear conversations',

  'appearance.title': 'Appearance',
  'appearance.reset': 'Reset appearance',
  'appearance.mode': 'Display mode',
  'appearance.light': 'Light',
  'appearance.dark': 'Dark',
  'appearance.system': 'System',
  'appearance.accent': 'Accent colour',
  'appearance.presets': 'Preset colours',
  'appearance.custom': 'Custom accent colour',
  'appearance.hex': 'Accent colour hex value',
  'appearance.invalid': 'Enter a colour as #RRGGBB',
  'appearance.preset.green': 'Pine',
  'appearance.preset.blue': 'Lake blue',
  'appearance.preset.violet': 'Violet',
  'appearance.preset.rose': 'Rose',
  'appearance.preset.amber': 'Amber',
  'appearance.preset.graphite': 'Graphite',
  'appearance.language': 'Language',
  'appearance.languageHint': 'Interface language; the README and project page are also available in three languages.',

  'common.cancel': 'Cancel',
  'common.delete': 'Delete',
  'common.confirm': 'OK',
}

const ja: Record<keyof typeof zh, string> = {
  'app.tagline.desktop': 'デスクトップ版キャンパスワークベンチ',
  'app.tagline.web': 'キャンパスワークベンチ',
  'app.menu': 'ナビゲーションを開く',
  'app.backend.connected': 'バックエンド接続済み',
  'app.backend.disconnected': 'バックエンド未接続',
  'app.backend.checking': '確認中',
  'app.version.desktop': 'デスクトップ版',
  'app.model.auto': '自動ルーティング',
  'app.model.local': 'ローカルモデル',

  'nav.workspace': 'ワークスペース',
  'nav.admin': '管理',
  'nav.chat': '質問応答',
  'nav.services': '学内サービス',
  'nav.knowledge': 'ナレッジベース',
  'nav.plugins': 'プラグイン',
  'nav.settings': '設定',

  'chat.title': '今日は何をお手伝いしましょうか？',
  'chat.suggestion.card': 'キャンパスカードの再発行に必要なものは？',
  'chat.suggestion.schedule': '今週の時間割を表示',
  'chat.suggestion.repair': '学内の修理申請の流れは？',
  'chat.placeholder': '質問を入力…',
  'chat.send': '送信',
  'chat.stop': '生成を停止',
  'chat.webToggle': 'ウェブ検索',
  'chat.disclaimer': '回答は参考情報です。学校の公式通知を必ず確認してください',
  'chat.restoring': '会話を復元しています…',
  'chat.retry': '再試行',
  'chat.modelSettings': 'モデル設定',
  'chat.retrieval.keyword': 'ローカルキーワード検索',
  'chat.retrieval.vector': 'ベクトル検索が有効',
  'chat.retrieval.degraded': 'ベクトル検索が失敗し、キーワード検索に切り替えました',
  'chat.stopped': '生成を停止しました',
  'chat.history': '履歴',
  'chat.new': '新しい会話',
  'chat.modelPicker': 'チャットモデル',
  'chat.modelCloud': 'クラウドと自動ルーティング',
  'chat.modelLocal': 'ローカル Ollama',
  'chat.localChecking': '確認中…',
  'chat.localNone': 'インストール済みモデルなし',
  'chat.ollamaOffline': 'Ollama 未接続',
  'chat.refreshLocal': 'ローカルモデルを更新',
  'chat.sourceLabel': '参照元',
  'chat.sourceLabelWeb': '参照元（ウェブ検索を含む）',
  'chat.hero.lead': 'ローカルのナレッジベースに基づくキャンパスアシスタント。資料・会話・検索はすべてこの端末で完結します。',
  'chat.hero.hint': 'ドラッグで回転・スクロールでズーム',
  'chat.suggestions.title': 'こんな質問はいかがですか',
  'chat.webUnavailableHint': '現在ウェブ検索を利用できません。管理者が設定で有効にしてください。',
  'chat.demo': 'デモデータ',

  'history.title': '会話履歴',
  'history.empty': '会話履歴はまだありません。',
  'history.emptyHint': '最初のメッセージを送信すると自動で保存されます。',
  'history.count': '{count} 件のメッセージ',
  'history.clear': '全削除',
  'history.refresh': '会話履歴を更新',
  'history.delete': '会話を削除：{title}',
  'history.export': '会話を書き出す：{title}',
  'history.exportMarkdown': 'Markdown で書き出し',
  'history.exportJson': 'JSON で書き出し',
  'history.loadError': '会話履歴を読み込めません：{error}',
  'history.loadErrorHint': '{error} 再試行するか、新しい会話を始めてください。',
  'history.exported': '会話を書き出しました：{path}',
  'history.exportCancelled': '書き出しをキャンセルしました。',
  'history.downloadStarted': '{name} のダウンロードを開始しました',
  'history.exportFailed': '書き出しに失敗しました：{error}',
  'history.confirmDelete': '「{title}」を削除しますか？元に戻せません。',
  'history.confirmDeleteTitle': '会話を削除',
  'history.confirmClear': '{count} 件の会話をすべて削除します。元に戻せません。よろしいですか？',
  'history.confirmClearTitle': '会話履歴を全削除',

  'appearance.title': '外観',
  'appearance.reset': '外観を初期化',
  'appearance.mode': '表示モード',
  'appearance.light': 'ライト',
  'appearance.dark': 'ダーク',
  'appearance.system': 'システム連動',
  'appearance.accent': 'テーマカラー',
  'appearance.presets': 'プリセットカラー',
  'appearance.custom': 'カスタムテーマカラー',
  'appearance.hex': 'テーマカラーの16進値',
  'appearance.invalid': '#RRGGBB 形式で入力してください',
  'appearance.preset.green': 'パイングリーン',
  'appearance.preset.blue': 'レイクブルー',
  'appearance.preset.violet': 'バイオレット',
  'appearance.preset.rose': 'ローズ',
  'appearance.preset.amber': 'アンバー',
  'appearance.preset.graphite': 'グラファイト',
  'appearance.language': '言語',
  'appearance.languageHint': '画面の言語です。README と紹介ページも3言語で用意しています。',

  'common.cancel': 'キャンセル',
  'common.delete': '削除',
  'common.confirm': 'OK',
}

export const catalogs: { zh: typeof zh; en: typeof zh; ja: typeof zh } = { zh, en, ja }

function systemLocale(): Locale {
  const languages = typeof navigator === 'undefined' ? [] : navigator.languages || [navigator.language]
  for (const tag of languages) {
    const value = String(tag || '').toLowerCase()
    if (value.startsWith('ja')) return 'ja'
    if (value.startsWith('en')) return 'en'
    if (value.startsWith('zh')) return 'zh'
  }
  return 'zh'
}

function storedChoice(): LocaleChoice {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'zh' || saved === 'en' || saved === 'ja' || saved === 'system') return saved
  } catch { /* private mode */ }
  return 'system'
}

const choice = ref<LocaleChoice>(storedChoice())
export const locale = computed<Locale>(() => (choice.value === 'system' ? systemLocale() : choice.value))
export const localeChoice = computed(() => choice.value)

export function setLocale(next: LocaleChoice) {
  choice.value = next
  try { localStorage.setItem(STORAGE_KEY, next) } catch { /* private mode */ }
  if (typeof document !== 'undefined') {
    document.documentElement.lang = locale.value === 'zh' ? 'zh-CN' : locale.value
  }
}

/** Translate a key, substituting {name} placeholders; falls back to Chinese, then to the key. */
export function t(key: string, params?: Record<string, string | number>): string {
  const table = catalogs[locale.value] as Record<string, string>
  let value = table[key] ?? (catalogs.zh as Record<string, string>)[key] ?? key
  if (params) {
    for (const [name, replacement] of Object.entries(params)) {
      value = value.split(`{${name}}`).join(String(replacement))
    }
  }
  return value
}

export function applyLocale() {
  if (typeof document !== 'undefined') {
    document.documentElement.lang = locale.value === 'zh' ? 'zh-CN' : locale.value
  }
}
