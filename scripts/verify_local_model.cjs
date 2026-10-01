'use strict'
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const { startBackend } = require('../desktop/lib/backend.cjs')

async function main() {
  const root = path.resolve(__dirname, '..')
  const output = path.join(root, 'build', 'local-model-verification')
  fs.mkdirSync(output, { recursive: true })
  const dataDir = fs.mkdtempSync(path.join(output, 'data-'))
  fs.writeFileSync(path.join(dataDir, '.env'), 'QWEN_API_KEY=\nDEEPSEEK_API_KEY=\nENABLE_RAG=false\n')
  const backend = startBackend({ packaged: true, projectRoot: root,
    resourcesPath: path.join(root, 'release', 'win-unpacked', 'resources'), dataDir })
  try {
    const { origin, token } = await backend.ready
    const headers = { 'Content-Type': 'application/json', 'X-Campus-Desktop-Token': token }
    const models = await fetch(`${origin}/api/models/local`, { headers }).then(response => response.json())
    assert.equal(models.running, true)
    assert.ok(models.installed.length > 0, 'No installed model to verify')
    const model = models.installed[0].name
    console.log(`Testing installed model ${model} with the packaged Mens backend.`)
    const before = Date.now()
    const response = await fetch(`${origin}/api/chat`, { method: 'POST', headers,
      body: JSON.stringify({ message: '请用一句简短的中文问候我。', model: 'ollama', local_model: model }),
      signal: AbortSignal.timeout(190000) })
    const answer = await response.json()
    assert.equal(response.status, 200, JSON.stringify(answer))
    assert.equal(answer.mode, 'llm', JSON.stringify(answer))
    assert.ok(answer.answer.trim().length > 0)
    const result = { passed: true, model, elapsed_ms: Date.now() - before, mode: answer.mode, answer: answer.answer }
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2))
    console.log(JSON.stringify(result))
  } finally { await backend.stop() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
