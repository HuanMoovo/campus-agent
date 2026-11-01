// @vitest-environment node
import { createHash } from 'node:crypto'
import { cpSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import { expect, it } from 'vitest'

const frontend = fileURLToPath(new URL('..', import.meta.url))

// Catch a build hook reading/writing an old default dist instead of Vite's resolved outDir.
it.each(['relative', 'absolute'])('versions the real worker in a %s custom output directory', kind => {
  // A child directory inherits installed dependencies without requiring Windows symlink rights.
  const temporary = mkdtempSync(join(frontend, '.build-output-test-'))
  const input = join(temporary, 'frontend')
  mkdirSync(input)
  try {
    for (const name of readdirSync(frontend)) {
      if (['node_modules', 'dist', '.npm-cache', '.vite'].includes(name) || name.startsWith('.build-output-test-')) continue
      cpSync(join(frontend, name), join(input, name), { recursive: true })
    }
    mkdirSync(join(input, 'dist'))
    writeFileSync(join(input, 'dist', 'sw.js'), 'existing default output must stay unchanged')
    const outputArgument = kind === 'relative' ? 'custom-output' : join(temporary, 'absolute-output')
    const result = spawnSync(process.execPath, [
      join(frontend, 'node_modules/vite/bin/vite.js'), 'build', '--configLoader', 'runner',
      '--outDir', outputArgument, '--emptyOutDir',
    ], { cwd: input, encoding: 'utf8', timeout: 60_000 })

    expect(result.error, result.stderr).toBeUndefined()
    expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0)
    const output = resolve(input, outputArgument)
    const worker = readFileSync(join(output, 'sw.js'), 'utf8')
    const version = JSON.parse(readFileSync(join(input, 'package.json'), 'utf8')).version
    const fingerprint = createHash('sha256')
      .update(readFileSync(join(output, 'index.html')))
      .update(readFileSync(join(output, 'favicon.png')))
      .digest('hex').slice(0, 12)
    expect(worker).not.toContain('__MENS_VERSION__')
    expect(worker).toContain(`${version}-${fingerprint}`)
    expect(readFileSync(join(input, 'dist', 'sw.js'), 'utf8')).toBe('existing default output must stay unchanged')
  } finally {
    rmSync(temporary, { recursive: true, force: true })
  }
}, 90_000)
