import { describe, expect, it } from 'vitest'

import { filterCommands, matchSlashCommands, SLASH_COMMANDS } from '../src/commands'

describe('matchSlashCommands', () => {
  it('matches slash commands by prefix and ignores other input', () => {
    expect(matchSlashCommands(SLASH_COMMANDS, '/')).toHaveLength(4)
    expect(matchSlashCommands(SLASH_COMMANDS, '/ne').map(item => item.id)).toEqual(['new'])
    expect(matchSlashCommands(SLASH_COMMANDS, '/NEW').map(item => item.id)).toEqual(['new'])
    expect(matchSlashCommands(SLASH_COMMANDS, '/new 参数')).toEqual([])
    expect(matchSlashCommands(SLASH_COMMANDS, 'new')).toEqual([])
    expect(matchSlashCommands(SLASH_COMMANDS, '你好')).toEqual([])
    expect(matchSlashCommands(SLASH_COMMANDS, '/没有这个')).toEqual([])
  })
})

describe('filterCommands', () => {
  const items = [
    { label: '新建对话', hint: '开始一段新对话' },
    { label: '切换到深色', hint: 'Toggle dark' },
    { label: '导出当前对话 Markdown', hint: '下载' },
  ]

  it('returns everything for an empty query', () => {
    expect(filterCommands(items, '   ')).toHaveLength(3)
  })

  it('matches label and hint case-insensitively', () => {
    expect(filterCommands(items, '对话').map(item => item.label)).toEqual(['新建对话', '导出当前对话 Markdown'])
    expect(filterCommands(items, 'toggle').map(item => item.label)).toEqual(['切换到深色'])
    expect(filterCommands(items, 'markdown')).toHaveLength(1)
    expect(filterCommands(items, '不存在')).toHaveLength(0)
  })
})
