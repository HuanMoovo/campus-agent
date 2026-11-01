'use strict'

const MODELS = new Set(['auto', 'qwen3', 'deepseek', 'openai_compatible', 'ollama',
  'openai_responses', 'anthropic', 'gemini', 'zhipu', 'moonshot', 'doubao', 'siliconflow',
  'hunyuan', 'qianfan', 'minimax', 'stepfun', 'spark', 'yi', 'xiaomi', 'zai', 'xai', 'openrouter',
  'groq', 'mistral', 'together', 'fireworks', 'deepinfra', 'cerebras', 'huggingface', 'cohere'])
const REASONING_EFFORTS = new Set(['auto', 'low', 'medium', 'high', 'xhigh', 'max', 'fast', 'deep'])

function isOwnUrl(url, origin) {
  if (!origin) return false
  try {
    const parsed = new URL(url)
    return parsed.origin === origin && parsed.protocol === 'http:' && !parsed.username && !parsed.password
  } catch { return false }
}

function validateWorkspace(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new TypeError('Invalid workspace settings')
  if (Object.keys(value).some(key => !['model', 'conversationId', 'clientId', 'localModel', 'appearance', 'accentColor', 'webSearch', 'reasoning', 'projectPermission', 'onboardingDone'].includes(key))) throw new TypeError('Unsupported setting')
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
  if ('onboardingDone' in value && typeof value.onboardingDone !== 'boolean') throw new TypeError('Invalid onboarding completion')
  if ('reasoning' in value && !REASONING_EFFORTS.has(value.reasoning)) throw new TypeError('Invalid reasoning effort')
  if ('projectPermission' in value && !['read_only', 'confirm'].includes(value.projectPermission)) throw new TypeError('Invalid project permission')
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

const PROJECT_CHANGE_CODES = new Set([
  'project_change_read_only',
  'project_change_unsupported', 'project_change_conflict', 'project_change_busy',
  'project_change_journal_unavailable', 'project_change_limit', 'project_change_invalid',
  'project_change_not_found', 'project_change_failed', 'project_change_transport',
  'project_change_invalid_response', 'project_change_invalid_arguments', 'project_change_sender',
])
const CHANGE_ACTIONS = new Set(['apply', 'revert', 'keep'])
const CHANGE_STATES = new Set(['pending', 'applied', 'reverted', 'kept', 'conflict', 'failed', 'uncertain'])
const HASH = /^[a-f0-9]{64}$/

function validateProjectId(value) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(value)) throw new TypeError('Invalid project change ID')
  return value
}

function validateProjectChangeArguments(args) {
  if (!Array.isArray(args) || args.length !== 3 || !CHANGE_ACTIONS.has(args[2])) throw new TypeError('Invalid project change arguments')
  return { projectId: validateProjectId(args[0]), subjectId: validateProjectId(args[1]), action: args[2] }
}

function changeResponseInvalid() { throw new TypeError('Invalid project change response') }
function object(value) { return value && typeof value === 'object' && !Array.isArray(value) }
function boundedText(value, maximum) {
  return typeof value === 'string' && [...value].length <= maximum
    && ![...value].some(char => char.length === 1 && /[\ud800-\udfff]/u.test(char))
}
function relativeProjectPath(value) {
  return boundedText(value, 2048) && value.length > 0 && !/[\\:\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]/u.test(value)
    && value.split('/').every(part => part && part !== '.' && part !== '..')
}
function validChangeCommon(value) {
  if (!object(value) || !CHANGE_ACTIONS.has(value.action) || !relativeProjectPath(value.path)
      || !boundedText(value.summary, 800) || typeof value.digest !== 'string' || !HASH.test(value.digest)) changeResponseInvalid()
  for (const key of ['project_id', 'subject_id', 'proposal_id']) validateProjectId(value[key])
}
function validateProjectChangePreparation(value, expected) {
  validChangeCommon(value)
  if (value.project_id !== expected.projectId || value.subject_id !== expected.subjectId || value.action !== expected.action
      || value.action === 'apply' && value.proposal_id !== value.subject_id
      || !HASH.test(value.expected_sha256) || !HASH.test(value.target_sha256)
      || !Number.isInteger(value.added_lines) || value.added_lines < 0 || value.added_lines > 2000
      || !Number.isInteger(value.removed_lines) || value.removed_lines < 0 || value.removed_lines > 2000) changeResponseInvalid()
  return value
}
function validateProjectChangeReceipt(value, expected = {}) {
  validChangeCommon(value)
  for (const key of ['operation_id', 'recovery_id']) validateProjectId(value[key])
  if (!CHANGE_STATES.has(value.state) || typeof value.can_revert !== 'boolean'
      || value.action === 'apply' && value.proposal_id !== value.subject_id
      || value.action !== 'apply' && value.recovery_id !== value.subject_id
      || !boundedText(value.created_at, 64) || !Number.isFinite(Date.parse(value.created_at))
      || value.error_code !== undefined && !PROJECT_CHANGE_CODES.has(value.error_code)) changeResponseInvalid()
  for (const [key, wanted] of Object.entries(expected)) if (value[key] !== wanted) changeResponseInvalid()
  return value
}
function projectChangePublicReceipt(value) {
  // Construct the renderer surface explicitly; never spread backend-only data.
  return {
    operation_id: value.operation_id, project_id: value.project_id, subject_id: value.subject_id,
    proposal_id: value.proposal_id, recovery_id: value.recovery_id, action: value.action, state: value.state,
    path: value.path, summary: value.summary, created_at: value.created_at, can_revert: value.can_revert,
    ...(value.error_code ? { error_code: value.error_code } : {}),
  }
}
function validateProjectChangeList(value, projectId) {
  if (!object(value) || typeof value.available !== 'boolean' || !Array.isArray(value.records) || value.records.length > 64) changeResponseInvalid()
  const ids = new Set()
  const records = value.records.map(row => {
    validateProjectChangeReceipt(row, { project_id: projectId })
    if (ids.has(row.operation_id)) changeResponseInvalid()
    ids.add(row.operation_id)
    return projectChangePublicReceipt(row)
  })
  const archiveRows = value.archives === undefined ? [] : value.archives
  if (!Array.isArray(archiveRows) || archiveRows.length > 256) changeResponseInvalid()
  const archiveIds = new Set()
  const archives = archiveRows.map(row => {
    if (!object(row) || typeof row.archive_id !== 'string' || !/^backup_[a-f0-9]{64}$/.test(row.archive_id)
        || archiveIds.has(row.archive_id) || !relativeProjectPath(row.path) || !boundedText(row.summary, 800)
        || !boundedText(row.created_at, 64) || !Number.isFinite(Date.parse(row.created_at))
        || !Number.isInteger(row.size_bytes) || row.size_bytes < 0 || row.size_bytes > 65536) changeResponseInvalid()
    archiveIds.add(row.archive_id)
    return { archive_id: row.archive_id, path: row.path, summary: row.summary,
      created_at: row.created_at, size_bytes: row.size_bytes }
  })
  return { available: value.available, records, archives }
}
function validateProjectRecoveryOriginal(value) {
  if (!object(value) || !boundedText(value.text, 12000) || Buffer.byteLength(value.text, 'utf8') > 65536
      || /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/u.test(value.text) || typeof value.bom !== 'boolean'
      || !['none', 'lf', 'crlf', 'cr', 'mixed'].includes(value.newline)) changeResponseInvalid()
  return { text: value.text, bom: value.bom, newline: value.newline }
}

module.exports = { isOwnUrl, BACKUP_LIMIT, EXPORT_LIMIT, validateWorkspace, parseReadyLine, validateBackupName, validateBackupBytes, validateExportName, validateExternalUrl,
  PROJECT_CHANGE_CODES, validateProjectId, validateProjectChangeArguments, validateProjectChangePreparation,
  validateProjectChangeReceipt, projectChangePublicReceipt, validateProjectChangeList, validateProjectRecoveryOriginal }
