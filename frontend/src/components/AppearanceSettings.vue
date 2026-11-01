<script setup lang="ts">
import { Monitor, Moon, RefreshLeft, Sunny } from '@element-plus/icons-vue'
import type { AppearanceMode } from '../appearance'
import { localeChoice, setLocale, t, type LocaleChoice } from '../i18n'

defineProps<{ mode: AppearanceMode; accent?: string; disabled?: boolean }>()
const emit = defineEmits<{
  'update:mode': [value: AppearanceMode]
}>()
const modes = [
  { value: 'light' as const, key: 'appearance.light', icon: Sunny },
  { value: 'dark' as const, key: 'appearance.dark', icon: Moon },
  { value: 'system' as const, key: 'appearance.system', icon: Monitor },
]
// Language names stay in their own language; only the "follow the system" entry is translated.
const languages: { value: LocaleChoice; label: string }[] = [
  { value: 'system', label: '' },
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
  { value: 'ja', label: '日本語' },
]
function languageLabel(value: LocaleChoice, label: string) {
  return value === 'system' ? t('appearance.system') : label
}

function reset() {
  emit('update:mode', 'system')
}
</script>

<template>
  <section class="settings-panel appearance-settings" aria-labelledby="appearance-heading">
    <div class="panel-title-row">
      <div class="settings-copy"><h2 id="appearance-heading">{{ t('appearance.title') }}</h2></div>
      <el-tooltip :content="t('appearance.reset')" placement="top">
        <el-button :icon="RefreshLeft" :disabled="disabled" :aria-label="t('appearance.reset')" @click="reset" />
      </el-tooltip>
    </div>
    <div class="appearance-row">
      <span id="appearance-mode-label" class="appearance-label">{{ t('appearance.mode') }}</span>
      <div class="appearance-modes" role="radiogroup" aria-labelledby="appearance-mode-label">
        <label v-for="item in modes" :key="item.value" class="appearance-mode" :class="{ selected: mode === item.value }">
          <input type="radio" name="appearance-mode" :value="item.value" :checked="mode === item.value" :disabled="disabled" @change="emit('update:mode', item.value)">
          <el-icon><component :is="item.icon" /></el-icon><span>{{ t(item.key) }}</span>
        </label>
      </div>
    </div>
    <div class="appearance-row language-row">
      <span id="appearance-language-label" class="appearance-label">{{ t('appearance.language') }}</span>
      <div class="appearance-modes" role="radiogroup" aria-labelledby="appearance-language-label">
        <label v-for="item in languages" :key="item.value" class="appearance-mode" :class="{ selected: localeChoice === item.value }">
          <input type="radio" name="appearance-language" :value="item.value" :checked="localeChoice === item.value" @change="setLocale(item.value)">
          <span>{{ languageLabel(item.value, item.label) }}</span>
        </label>
      </div>
      <p class="appearance-hint">{{ t('appearance.languageHint') }}</p>
    </div>
  </section>
</template>
