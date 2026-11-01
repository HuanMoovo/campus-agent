<script setup lang="ts">
import { SETTINGS_CATEGORIES, type SettingsCategory } from '../settings-navigation'
import { t } from '../i18n'

defineProps<{ modelValue: SettingsCategory }>()
const emit = defineEmits<{ 'update:modelValue': [value: SettingsCategory] }>()
</script>

<template>
  <div class="settings-layout">
    <nav class="settings-nav" :aria-label="t('settings.navigation')">
      <button
        v-for="category in SETTINGS_CATEGORIES" :id="`settings-nav-${category}`" :key="category"
        type="button" :data-settings-target="category"
        :aria-current="modelValue === category ? 'page' : undefined"
        :aria-controls="`settings-panel-${category}`"
        @click="emit('update:modelValue', category)"
      >{{ t(`settings.category.${category}`) }}</button>
    </nav>
    <div class="settings-content">
      <section
        v-for="category in SETTINGS_CATEGORIES" :id="`settings-panel-${category}`" :key="category"
        v-show="modelValue === category" :data-settings-section="category"
        :aria-labelledby="`settings-nav-${category}`"
      ><slot :name="category" /></section>
    </div>
  </div>
</template>

<style scoped>
.settings-layout { display: grid; grid-template-columns: 148px minmax(0, 1fr); gap: 36px; align-items: start; }
.settings-nav { display: flex; flex-direction: column; gap: 4px; position: sticky; top: 0; }
.settings-nav button { width: 100%; text-align: left; padding: 11px 12px; border: 0; border-radius: 7px; background: transparent; color: var(--text-secondary); font: inherit; font-size: 13px; line-height: 1.5; cursor: pointer; overflow-wrap: anywhere; }
.settings-nav button:hover { background: var(--surface-hover); color: var(--text); }
.settings-nav button[aria-current] { background: var(--surface-muted); color: var(--text); font-weight: 600; }
.settings-nav button:focus-visible { outline: 2px solid var(--text); outline-offset: 2px; }
.settings-content, .settings-content > section { min-width: 0; }
.settings-content :deep(.settings-section:first-child), .settings-content :deep(.settings-panel:first-child), .settings-content :deep(.model-settings:first-child) { border-top: 0; padding-top: 0; }
.settings-content :deep(.settings-copy) { max-width: none; }
.settings-content :deep(.settings-section) { gap: 18px; }
.settings-content :deep(.panel-heading) { margin-bottom: 18px; }
@media (max-width: 768px) {
  .settings-layout { grid-template-columns: minmax(0, 1fr); gap: 26px; }
  .settings-nav { position: static; flex-direction: row; flex-wrap: wrap; gap: 3px; padding-bottom: 16px; border-bottom: 1px solid var(--border-subtle); }
  .settings-nav button { width: auto; max-width: 100%; padding: 9px 10px; font-size: 12px; }
}
</style>
