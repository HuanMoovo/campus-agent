'use strict'

const MODELS = new Set(['auto', 'qwen3', 'deepseek', 'ollama'])
const REASONING_EFFORTS = new Set(['fast', 'deep'])

function isOwnUrl(url, origin) {
  if (!origin) return false
  try {
    const parsed = new URL(url)
    return parsed.origin === origin && parsed.protocol === 'http:' && !parsed.username && !parsed.password
  } catch { return false }
}

function validateWorkspace(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new TypeError('Invalid workspace settings')
  if (Object.keys(value).some(key => !['model', 'conversationId', 'clientId', 'localModel', 'appearance', 'accentColor', 'webSearch', 'reasoning'].includes(key))) throw new TypeError('Unsupported setting')
  if ('model' in value && !MODELS.has(value.model)) throw new TypeError('Invalid model')
  if ('conversationId' in value && (typeof value.conversationId !== 'string' || !/^[a-zA-Z0-9-]{0,64}$/.test(value.conversationId))) {
    throw new TypeError('Invalid conversation ID')
  }
  if ('clientId' in value && (typeof value.clientId !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(value.clientId))) {
    throw new TypeError('Invalid client ID')
  }
  if ('localModel' in value && (typeof value.localModel !== 'string' || value.localModel.length > 128 || /[\x00-\x1f\x7f]/.test(value.localModel))) throw new TypeError('Invalid local model')
  if ('appearance' in value && !['light', 'dark', 'system'].includes(value.appearance)) throw new TypeError('Invalid appearance')
  if ('accentColor' in value && (typeof value.accentColor !== 'string' || !/^#[0-9a-f]{6}$/i.test(value.accentColor))) throw new TypeError('Invalid accent color')
  if ('webSearch' in value && typeof value.webSearch !== 'boolean') throw new TypeError('Invalid web search preference')
  if ('reasoning' in value && !REASONING_EFFORTS.has(value.reasoning)) throw new TypeError('Invalid reasoning effort')
  return { ...value }
}

function parseReadyLine(line, nonce) {
  let value
  try { value = JSON.parse(line) } catch { return null }
  if (value?.event !== 'campus-ready' || value.nonce !== nonce || value.host !== '127.0.0.1'
      || !Number.isInteger(value.port) || value.port < 1024 || value.port > 65535) return null
  return { origin: `http://127.0.0.1:${value.port}`, port: value.port }
}

const BACKUP_LIMIT = 300 * 1024 * 1024

function validateBackupName(name) {
  if (typeof name !== 'string' || name.startsWith('.') || !/^[A-Za-z0-9._-]{1,80}\.zip$/.test(name)) {
    throw new TypeError('Invalid backup file name')
  }
  return name
}

function validateBackupBytes(bytes, limit = BACKUP_LIMIT) {
  const size = bytes instanceof ArrayBuffer ? bytes.byteLength
    : ArrayBuffer.isView(bytes) ? bytes.byteLength : -1
  if (size < 0) throw new TypeError('Invalid backup payload')
  if (size > limit) throw new TypeError('Backup payload is too large')
  return size
}

const EXPORT_LIMIT = 20 * 1024 * 1024

function validateExportName(name) {
  if (typeof name !== 'string' || name.startsWith('.') || !/^[A-Za-z0-9._-]{1,120}\.(md|json)$/.test(name)) {
    throw new TypeError('Invalid export file name')
  }
  return name
}

function validateExternalUrl(url) {
  if (typeof url !== 'string' || url.length > 2048) throw new TypeError('Invalid external URL')
  let parsed
  try { parsed = new URL(url) } catch { throw new TypeError('Invalid external URL') }
  if (parsed.protocol !== 'https:' || !parsed.hostname || parsed.username || parsed.password) {
    throw new TypeError('Invalid external URL')
  }
  return parsed.href
}

module.exports = { isOwnUrl, BACKUP_LIMIT, EXPORT_LIMIT, validateWorkspace, parseReadyLine, validateBackupName, validateBackupBytes, validateExportName, validateExternalUrl }
