<script setup lang="ts">
import { computed } from 'vue'
import { groupSchedule } from '../schedule'

const props = defineProps<{ rows: Record<string, unknown>[] }>()
const groups = computed(() => groupSchedule(props.rows))
const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
function text(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未提供'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}
</script>

<template>
  <div class="schedule-week" aria-label="课表周视图">
    <section v-for="(day, index) in groups.days" :key="index" class="schedule-day">
      <h4>{{ weekdays[index] }}</h4>
      <p v-if="day.length === 0" class="empty-day">暂无课程</p>
      <article v-for="(row, rowIndex) in day" :key="rowIndex" class="schedule-course">
        <strong>{{ text(row.course) }}</strong>
        <span>{{ text(row.time) }}</span>
        <span>{{ text(row.room) }}</span>
      </article>
    </section>
  </div>
  <p class="schedule-note">按星期分组展示接口提供的课程，不代表特定日期或教学周。完整信息见下方列表。</p>
  <div v-if="groups.unclassified.length" class="schedule-unclassified">
    <strong>星期未识别：{{ groups.unclassified.length }} 条</strong>
    <span>这些课程保留在下方完整列表中。</span>
  </div>
</template>

<style scoped>
.schedule-week { display: grid; grid-template-columns: repeat(7, minmax(125px, 1fr)); gap: 8px; overflow-x: auto; padding-bottom: 4px; }
.schedule-day { background: var(--surface, #fff); border: 1px solid var(--border, #ddd); border-radius: 7px; padding: 10px; min-height: 115px; }
.schedule-day h4 { margin: 0 0 10px; font-size: 14px; }
.schedule-course { display: flex; flex-direction: column; gap: 4px; background: var(--el-color-primary-light-9, #eeeeee); border-radius: 5px; padding: 8px; margin-bottom: 8px; font-size: 12px; overflow-wrap: anywhere; }
.empty-day, .schedule-note, .schedule-unclassified { color: var(--el-text-color-secondary); font-size: 12px; }
.schedule-unclassified { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
</style>
