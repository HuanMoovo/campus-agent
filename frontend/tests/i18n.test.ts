import { beforeEach, describe, expect, it } from 'vitest'
import { catalogs, locale, localeChoice, setLocale, t } from '../src/i18n'

describe('interface language', () => {
  beforeEach(() => {
    localStorage.clear()
    setLocale('zh')
  })

  it('keeps every key in all three catalogues', () => {
    const zhKeys = Object.keys(catalogs.zh).sort()
    expect(zhKeys.length).toBeGreaterThan(60)
    for (const key of zhKeys) {
      expect(catalogs.en[key as keyof typeof catalogs.zh], `en is missing ${key}`).toBeTruthy()
      expect(catalogs.ja[key as keyof typeof catalogs.zh], `ja is missing ${key}`).toBeTruthy()
    }
    expect(Object.keys(catalogs.en).sort()).toEqual(zhKeys)
    expect(Object.keys(catalogs.ja).sort()).toEqual(zhKeys)
  })

  it('translates, interpolates, and falls back to Chinese and then to the key', () => {
    setLocale('en')
    expect(t('nav.chat')).toBe('Chat')
    expect(t('history.count', { count: 3 })).toBe('3 messages')
    expect(t('history.exported', { path: 'C:/docs/a.md' })).toBe('Conversation exported: C:/docs/a.md')

    setLocale('ja')
    expect(t('nav.chat')).toBe('質問応答')
    expect(t('history.count', { count: 3 })).toBe('3 件のメッセージ')

    setLocale('zh')
    expect(t('nav.chat')).toBe('智能问答')
    expect(t('definitely.not.a.key')).toBe('definitely.not.a.key')
  })

  it('remembers the choice and tags the document language', () => {
    setLocale('ja')
    expect(localStorage.getItem('campus-agent-locale')).toBe('ja')
    expect(document.documentElement.lang).toBe('ja')
    expect(locale.value).toBe('ja')

    setLocale('en')
    expect(document.documentElement.lang).toBe('en')

    setLocale('system')
    expect(localeChoice.value).toBe('system')
    expect(['zh', 'en', 'ja']).toContain(locale.value)
  })

  it('has no empty translations', () => {
    for (const [name, table] of Object.entries(catalogs)) {
      for (const [key, value] of Object.entries(table)) {
        expect(String(value).trim().length, `${name}:${key}`).toBeGreaterThan(0)
      }
    }
  })
})
