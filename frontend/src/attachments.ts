/** 附件提问的共享定义与纯函数（便于单元测试）。 */

export interface ChatAttachment {
  name: string
  text: string
}

export const ATTACHMENT_MAX_COUNT = 3
export const ATTACHMENT_MAX_TEXT = 200_000
/** 本地直接读取的文本类扩展名。 */
export const ATTACHMENT_TEXT_EXTENSIONS = [
  'txt', 'md', 'markdown', 'csv', 'json', 'log', 'yml', 'yaml', 'ini', 'toml',
  'py', 'js', 'mjs', 'ts', 'vue', 'java', 'c', 'cpp', 'h', 'hpp', 'css', 'html', 'xml', 'sql', 'sh', 'bat', 'ps1', 'go', 'rs',
]
/** 需要后端解析的扩展名（PDF / Word）。 */
export const ATTACHMENT_EXTRACT_EXTENSIONS = ['pdf', 'docx']

export type AttachmentKind = 'text' | 'extract' | 'reject'

export function fileExtension(name: string): string {
  const index = name.lastIndexOf('.')
  return index >= 0 ? name.slice(index + 1).toLowerCase() : ''
}

export function attachmentKind(name: string): AttachmentKind {
  const extension = fileExtension(name)
  if (ATTACHMENT_TEXT_EXTENSIONS.includes(extension)) return 'text'
  if (ATTACHMENT_EXTRACT_EXTENSIONS.includes(extension)) return 'extract'
  return 'reject'
}

/** 输入选择框的 accept 值。 */
export function attachmentAccept(): string {
  return [...ATTACHMENT_TEXT_EXTENSIONS, ...ATTACHMENT_EXTRACT_EXTENSIONS].map(extension => `.${extension}`).join(',')
}

/** 随消息正文展示/落库的附件后缀（内容只随本次请求发给模型）。 */
export function attachmentSuffix(names: string[]): string {
  return `[附件] ${names.join('、')}`
}

/** 校验已读文本：为空或超出上限时返回错误键，否则 null。 */
export function attachmentTextProblem(text: string): string | null {
  if (!text.trim()) return 'chat.attachEmpty'
  if (text.length > ATTACHMENT_MAX_TEXT) return 'chat.attachTooLarge'
  return null
}
