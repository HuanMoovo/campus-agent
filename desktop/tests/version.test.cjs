'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

test('desktop, frontend and backend report the same release version', () => {
  const root = path.resolve(__dirname, '../..')
  const desktop = require('../package.json')
  const desktopLock = require('../package-lock.json')
  const frontend = require('../../frontend/package.json')
  const frontendLock = require('../../frontend/package-lock.json')
  const backend = fs.readFileSync(path.join(root, 'backend/app/main.py'), 'utf8')
  const backendVersion = backend.match(/FastAPI\(title="Mens API", version="([^"]+)"/)?.[1]
  assert.match(desktop.version, /^\d+\.\d+\.\d+$/)
  assert.equal(desktopLock.version, desktop.version)
  assert.equal(desktopLock.packages[''].version, desktop.version)
  assert.equal(frontend.version, desktop.version)
  assert.equal(frontendLock.version, desktop.version)
  assert.equal(frontendLock.packages[''].version, desktop.version)
  assert.equal(backendVersion, desktop.version)
})
