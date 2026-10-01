// Run against the local preview; API responses are isolated fixtures, never paid inference.
const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 }, colorScheme: 'light' })
  const page = await context.newPage()
  const errors = []
  const chats = []
  let installed = [{ name: 'qwen3:0.6b' }, { name: 'my-local-model:latest' }]
  page.on('pageerror', error => errors.push(error.message))
  const output = path.resolve(__dirname, '../build/ui-verification')
  fs.mkdirSync(output, { recursive: true })
  await page.route('**/api/**', async route => {
    const pathname = new URL(route.request().url()).pathname
    let value = {}
    if (pathname === '/api/health') value = { status: 'ok', models: { qwen: false, deepseek: false, ollama: true }, demo_services: true }
    else if (pathname === '/api/models/config') value = { providers: { qwen: {}, deepseek: {} }, ollama: { model: 'qwen3:0.6b' } }
    else if (pathname === '/api/models/local') value = { running: true, installed, catalog: [], sources: [] }
    else if (pathname === '/api/campus-sources' || pathname === '/api/documents' || pathname.startsWith('/api/plugins')) value = []
    else if (pathname === '/api/chat') {
      chats.push(route.request().postDataJSON())
      value = { conversation_id: 'ui-test', answer: 'Local model verification reply', sources: [], tool_calls: [], mode: 'live' }
    } else if (pathname.startsWith('/api/conversations/')) value = { messages: [] }
    await route.fulfill({ json: value })
  })
  try {
    await page.goto(process.env.MENS_PREVIEW_URL || 'http://127.0.0.1:5174')
    await page.getByRole('heading', { name: '智能问答', exact: true }).waitFor()
    assert.equal(await page.locator('.brand-mark').evaluate(image => image.complete && image.naturalWidth > 0), true)
    await page.locator('.nav-item').filter({ hasText: '设置' }).click()
    await page.getByRole('radio', { name: '深色', exact: true }).check()
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark')
    const hex = page.getByRole('textbox', { name: '主题色十六进制值' })
    await hex.fill('#ffcc00')
    await hex.press('Enter')
    assert.equal(await page.locator('html').evaluate(el => el.style.getPropertyValue('--accent')), '#ffcc00')
    assert.equal(await page.locator('html').evaluate(el => el.style.getPropertyValue('--on-accent')), '#000000')
    await page.screenshot({ path: path.join(output, 'contrast-yellow.png'), animations: 'disabled' })
    const selectionStyle = await page.locator('.el-radio-button.is-active .el-radio-button__inner').first().evaluate(el => ({ color: getComputedStyle(el).color, background: getComputedStyle(el).backgroundColor }))
    assert.deepEqual(selectionStyle, { color: 'rgb(0, 0, 0)', background: 'rgb(255, 204, 0)' })
    await hex.fill('#zzzzzz')
    await hex.press('Enter')
    await page.getByText('请输入 #RRGGBB 格式的颜色值').waitFor()
    assert.equal(await page.locator('html').evaluate(el => el.style.getPropertyValue('--accent')), '#ffcc00')
    await hex.fill('#c84062')
    await hex.press('Enter')
    await page.screenshot({ path: path.join(output, 'desktop-dark.png'), animations: 'disabled' })
    await page.reload()
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark')
    assert.equal(await page.locator('html').evaluate(el => el.style.getPropertyValue('--accent')), '#c84062')
    await page.locator('.nav-item').filter({ hasText: '设置' }).click()
    await page.getByRole('radio', { name: '跟随系统', exact: true }).check()
    await page.emulateMedia({ colorScheme: 'light' })
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'light')
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark')
    await page.getByRole('radio', { name: '浅色', exact: true }).check()
    await page.getByRole('button', { name: '湖蓝', exact: true }).click()
    await page.screenshot({ path: path.join(output, 'desktop-light.png'), animations: 'disabled' })
    await page.locator('.nav-item').filter({ hasText: '智能问答' }).click()
    await page.locator('.chat-model-picker .el-select__wrapper').click()
    await page.getByRole('option', { name: 'my-local-model:latest', exact: true }).click()
    await page.getByRole('textbox', { name: '输入问题' }).fill('Hello local model')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.getByText('Local model verification reply', { exact: true }).waitFor()
    assert.equal(chats[0].model, 'ollama')
    assert.equal(chats[0].local_model, 'my-local-model:latest')
    await page.reload()
    await page.getByRole('combobox', { name: '聊天模型' }).waitFor()
    assert.equal(await page.evaluate(() => localStorage.getItem('mens-local-model')), 'my-local-model:latest')
    await page.screenshot({ path: path.join(output, 'desktop-chat.png'), animations: 'disabled' })
    installed = [{ name: 'qwen3:0.6b' }]
    await page.getByRole('button', { name: '刷新本地模型', exact: true }).click()
    await page.getByText('本地模型 my-local-model:latest 未安装', { exact: true }).waitFor()
    await page.getByRole('textbox', { name: '输入问题' }).fill('Do not silently switch')
    assert.equal(await page.getByRole('button', { name: '发送', exact: true }).isDisabled(), true)
    await page.setViewportSize({ width: 390, height: 844 })
    await page.screenshot({ path: path.join(output, 'mobile-chat.png'), animations: 'disabled' })
    await page.getByRole('button', { name: '打开导航', exact: true }).click()
    await page.locator('.nav-item').filter({ hasText: '设置' }).click()
    await page.getByRole('radio', { name: '深色', exact: true }).check()
    await page.screenshot({ path: path.join(output, 'mobile-settings.png'), animations: 'disabled' })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    const overlap = await page.locator('.appearance-mode').evaluateAll(items => items.some((item, i) => i && item.getBoundingClientRect().left < items[i - 1].getBoundingClientRect().right - 1))
    assert.equal(overlap, false)
    assert.deepEqual(errors, [])
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify({ passed: true, checks: ['logo', 'light/dark/system', 'custom color and validation', 'persistence', 'chat model payload', 'removed model guard', 'mobile layout'], screenshots: fs.readdirSync(output).filter(name => name.endsWith('.png')) }, null, 2))
    console.log('UI verification passed: appearance, model selection, persistence, and desktop/mobile screenshots.')
  } catch (error) {
    await page.screenshot({ path: path.join(output, 'failure.png'), animations: 'disabled' })
    throw error
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
