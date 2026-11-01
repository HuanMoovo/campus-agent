import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../src/api'

afterEach(() => vi.unstubAllGlobals())

it('includes project originals only when the export explicitly opts in', async () => {
  const urls: string[] = []
  vi.stubGlobal('fetch', async (url: string) => { urls.push(url); return new Response('zip', { headers: { 'Content-Type': 'application/zip' } }) })
  await api.exportBackup()
  await api.exportBackup(true)
  expect(urls[0]).toBe('/api/backup/export')
  expect(urls[1]).toBe('/api/backup/export?include_project_recoveries=true')
})

it('retains imported and duplicate recovery-material counts from the import response', async () => {
  vi.stubGlobal('fetch', async () => Response.json({ restored: ['project-recovery.json'], failed: [], restart_required: false, project_recoveries: { imported: 2, duplicates: 1 } }))
  const result = await api.importBackup(new Uint8Array([1, 2]), 'backup.zip')
  expect(result.project_recoveries).toEqual({ imported: 2, duplicates: 1 })
})
