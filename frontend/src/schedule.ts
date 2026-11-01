const names = [
  ['周一', '星期一', '礼拜一', 'monday', 'mon'],
  ['周二', '星期二', '礼拜二', 'tuesday', 'tue'],
  ['周三', '星期三', '礼拜三', 'wednesday', 'wed'],
  ['周四', '星期四', '礼拜四', 'thursday', 'thu'],
  ['周五', '星期五', '礼拜五', 'friday', 'fri'],
  ['周六', '星期六', '礼拜六', 'saturday', 'sat'],
  ['周日', '周天', '星期日', '星期天', '礼拜日', '礼拜天', 'sunday', 'sun'],
]

export function groupSchedule(rows: Record<string, unknown>[]) {
  const days = Array.from({ length: 7 }, () => [] as Record<string, unknown>[])
  const unclassified: Record<string, unknown>[] = []
  for (const row of rows) {
    const weekday = typeof row.weekday === 'string' ? row.weekday.trim().toLowerCase() : ''
    const day = names.findIndex(options => options.includes(weekday))
    if (day < 0) unclassified.push(row)
    else days[day].push(row)
  }
  return { days, unclassified }
}
