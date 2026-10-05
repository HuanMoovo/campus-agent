/** 命令面板与斜杠指令的共享定义与匹配逻辑（纯函数，便于单元测试）。 */

export interface SlashCommand {
  id: string
  slash: string
  labelKey: string
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { id: 'new', slash: '/new', labelKey: 'cmd.new' },
  { id: 'history', slash: '/history', labelKey: 'cmd.history' },
  { id: 'export', slash: '/export', labelKey: 'cmd.exportMd' },
  { id: 'theme', slash: '/theme', labelKey: 'cmd.themeToggle' },
]

/** 输入以「/」开头且尚未出现空格时，按前缀匹配斜杠指令；否则返回空（正常输入不受干扰）。 */
export function matchSlashCommands<T extends { slash: string }>(items: T[], input: string): T[] {
  const value = input.trim().toLowerCase()
  if (!value.startsWith('/') || value.includes(' ')) return []
  return items.filter(item => item.slash.startsWith(value))
}

/** 命令面板过滤：不区分大小写，同时匹配标题与提示；空查询返回全部。 */
export function filterCommands<T extends { label: string; hint?: string }>(items: T[], query: string): T[] {
  const q = query.trim().toLowerCase()
  if (!q) return items
  return items.filter(item => `${item.label} ${item.hint || ''}`.toLowerCase().includes(q))
}
