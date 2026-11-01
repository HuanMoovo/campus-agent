// @vitest-environment node
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { describe, expect, it } from 'vitest'

const origin = 'https://campus.test'
const currentCache = 'mens-shell-1.2.2'
const source = readFileSync(new URL('../public/sw.js', import.meta.url), 'utf8')
  .replaceAll('__MENS_VERSION__', '1.2.2')

type CacheKey = string | Request
type WorkerEvent = {
  request?: Request
  respondWith?: (response: Promise<Response>) => void
  waitUntil: (work: Promise<unknown>) => void
}

function response(body: string, status = 200, contentType = 'text/html'): Response {
  const result = new Response(body, { status, headers: { 'Content-Type': contentType } })
  // Same-origin fetch responses are basic; constructed Node responses are default.
  Object.defineProperty(result, 'type', { value: 'basic' })
  return result
}

function request(path: string, mode?: 'navigate', method = 'GET'): Request {
  const result = new Request(new URL(path, origin), { method })
  if (mode) Object.defineProperty(result, 'mode', { value: mode })
  return result
}

function worker() {
  const listeners = new Map<string, (event: WorkerEvent) => void>()
  const stores = new Map<string, Map<string, Response>>()
  let network: (request: Request) => Promise<Response> = async () => { throw new Error('offline') }
  const key = (value: CacheKey) => new URL(typeof value === 'string' ? value : value.url, `${origin}/`).href
  const caches = {
    async open(name: string) {
      if (!stores.has(name)) stores.set(name, new Map())
      const entries = stores.get(name)!
      return {
        async match(value: CacheKey) { return entries.get(key(value))?.clone() },
        async put(value: CacheKey, result: Response) { entries.set(key(value), result.clone()) },
        async addAll(values: string[]) {
          for (const value of values) {
            const result = await network(request(value))
            if (!result.ok) throw new Error('Precache failed')
            entries.set(key(value), result.clone())
          }
        },
      }
    },
    async keys() { return [...stores.keys()] },
    async delete(name: string) { return stores.delete(name) },
  }
  runInNewContext(source, {
    URL,
    caches,
    fetch: (value: Request) => network(value),
    self: {
      location: { origin },
      addEventListener: (type: string, listener: (event: WorkerEvent) => void) => listeners.set(type, listener),
      skipWaiting: async () => {},
      clients: { claim: async () => {} },
    },
  })
  return {
    caches,
    setNetwork(handler: typeof network) { network = handler },
    async seed(path: string, body: string, name = currentCache) {
      await (await caches.open(name)).put(path, response(body))
    },
    async fetch(value: Request): Promise<Response | undefined> {
      let result: Promise<Response> | undefined
      const pending: Promise<unknown>[] = []
      listeners.get('fetch')!({
        request: value,
        respondWith: promise => { result = promise },
        waitUntil: promise => { pending.push(promise) },
      })
      const resolved = await result
      await Promise.all(pending)
      return resolved
    },
    async activate() {
      let pending: Promise<unknown> | undefined
      listeners.get('activate')!({ waitUntil: promise => { pending = promise } })
      await pending
    },
  }
}

describe('offline service worker', () => {
  it('serves a rebuilt shell from the network even when the app version is unchanged', async () => {
    const app = worker()
    await app.seed('./', '<script src="/assets/old.js"></script>')
    await app.seed('./index.html', '<script src="/assets/old.js"></script>')
    app.setNetwork(async () => response('<script src="/assets/new.js"></script>'))

    expect(await (await app.fetch(request('/', 'navigate')))!.text())
      .toBe('<script src="/assets/new.js"></script>')
  })

  it('uses the most recently downloaded shell for offline navigation to another route', async () => {
    const app = worker()
    await app.seed('./index.html', 'old shell')
    app.setNetwork(async () => response('new shell'))
    await app.fetch(request('/workspace', 'navigate'))
    app.setNetwork(async () => { throw new Error('offline') })

    expect(await (await app.fetch(request('/settings', 'navigate')))!.text()).toBe('new shell')
  })

  it('refreshes explicit HTML requests before returning a cached copy', async () => {
    const app = worker()
    await app.seed('./index.html', 'old shell')
    app.setNetwork(async () => response('new shell'))

    expect(await (await app.fetch(request('/index.html')))!.text()).toBe('new shell')
  })

  it.each([404, 503])('keeps the known-good shell when navigation returns HTTP %s', async status => {
    const app = worker()
    await app.seed('./index.html', 'last working shell')
    app.setNetwork(async () => response('server error', status))

    expect(await (await app.fetch(request('/workspace', 'navigate')))!.text()).toBe('last working shell')
    expect(await (await (await app.caches.open(currentCache)).match('./index.html'))!.text())
      .toBe('last working shell')
    expect(await (await app.caches.open(currentCache)).match('/workspace')).toBeUndefined()
  })

  it('preserves the HTTP error when no offline shell is available', async () => {
    const app = worker()
    app.setNetwork(async () => response('unavailable', 503))

    const result = await app.fetch(request('/', 'navigate'))
    expect(result?.status).toBe(503)
    expect(await result!.text()).toBe('unavailable')
    expect(await (await app.caches.open(currentCache)).match('./index.html')).toBeUndefined()
  })

  it('propagates network failure when no offline shell is available', async () => {
    const app = worker()
    await expect(app.fetch(request('/', 'navigate'))).rejects.toThrow('offline')
  })

  it.each(['/api/config', '/api/chat/stream'])('does not intercept or cache %s', async path => {
    const app = worker()
    await app.seed(path, 'stale API data')
    app.setNetwork(async () => { throw new Error('API must bypass the worker') })

    expect(await app.fetch(request(path, 'navigate'))).toBeUndefined()
  })

  it('does not intercept writes or cross-origin requests', async () => {
    const app = worker()
    expect(await app.fetch(request('/workspace', undefined, 'POST'))).toBeUndefined()
    expect(await app.fetch(new Request('https://other.test/index.html'))).toBeUndefined()
    expect(await app.caches.keys()).toEqual([])
  })

  it('caches successful static assets and serves them while offline', async () => {
    const app = worker()
    app.setNetwork(async () => response('export const version = 2', 200, 'text/javascript'))
    expect(await (await app.fetch(request('/assets/app-abcd1234.js')))!.text())
      .toBe('export const version = 2')
    app.setNetwork(async () => { throw new Error('offline') })

    expect(await (await app.fetch(request('/assets/app-abcd1234.js')))!.text())
      .toBe('export const version = 2')
  })

  it('does not cache unsuccessful static assets or replace them with HTML', async () => {
    const app = worker()
    await app.seed('./index.html', 'offline shell')
    app.setNetwork(async () => response('missing asset', 404))
    expect((await app.fetch(request('/assets/missing.js')))?.status).toBe(404)
    app.setNetwork(async () => { throw new Error('offline') })

    await expect(app.fetch(request('/assets/missing.js'))).rejects.toThrow('offline')
  })

  it('removes only obsolete application shell caches during activation', async () => {
    const app = worker()
    await app.seed('./index.html', 'current shell')
    await app.seed('./index.html', 'old shell', 'mens-shell-1.2.1')
    await app.seed('/draft', 'user data', 'user-workspace')
    await app.activate()

    expect(await app.caches.keys()).toEqual([currentCache, 'user-workspace'])
    expect(await (await (await app.caches.open('user-workspace')).match('/draft'))!.text()).toBe('user data')
  })
})
