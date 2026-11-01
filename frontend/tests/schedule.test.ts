import { describe, expect, it } from 'vitest'
import { groupSchedule } from '../src/schedule'

describe('schedule week grouping', () => {
  it('groups familiar weekdays and preserves raw times and records', () => {
    const a = { course: '数学', weekday: '周一', time: '第1-2节', room: 'A' }
    const b = { course: '英语', weekday: '星期天', time: '08:00-09:40', room: 'B' }
    const c = { course: '实验', weekday: 'Monday', time: '待定', room: 'C' }
    const groups = groupSchedule([a, b, c])
    expect(groups.days[0]).toEqual([a, c])
    expect(groups.days[6]).toEqual([b])
    expect(groups.unclassified).toEqual([])
  })
  it('keeps ambiguous or missing weekdays in the unclassified list', () => {
    const rows = [{ course: '体育', weekday: '周一、周三', time: '待定' }, { course: '实践', weekday: '' }]
    const groups = groupSchedule(rows)
    expect(groups.days.flat()).toEqual([])
    expect(groups.unclassified).toEqual(rows)
  })
})
