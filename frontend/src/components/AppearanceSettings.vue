<script setup lang="ts">
import { ref, watch } from 'vue'
import { Check, Monitor, Moon, RefreshLeft, Sunny } from '@element-plus/icons-vue'
import { DEFAULT_ACCENT, normalizeAccent, type AppearanceMode } from '../appearance'
import { localeChoice, setLocale, t, type LocaleChoice } from '../i18n'

const props = defineProps<{ mode: AppearanceMode; accent: string; disabled?: boolean }>()
const emit = defineEmits<{
  'update:mode': [value: AppearanceMode]
  'update:accent': [value: string]
}>()
const modes = [
  { value: 'light' as const, key: 'appearance.light', icon: Sunny },
  { value: 'dark' as const, key: 'appearance.dark', icon: Moon },
  { value: 'system' as const, key: 'appearance.system', icon: Monitor },
]
const presets = [
  { value: DEFAULT_ACCENT, key: 'appearance.preset.green' },
  { value: '#2563eb', key: 'appearance.preset.blue' },
  { value: '#8b5cf6', key: 'appearance.preset.violet' },
  { value: '#c84062', key: 'appearance.preset.rose' },
  { value: '#c66a17', key: 'appearance.preset.amber' },
  { value: '#5e6873', key: 'appearance.preset.graphite' },
]
// Language names stay in their own language; only the "follow the system" entry is translated.
const languages: { value: LocaleChoice; label: string }[] = [
  { value: 'system', label: '' },
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
  { value: 'ja', label: '日本語' },
]
const draft = ref(props.accent)
const invalid = ref(false)
watch(() => props.accent, value => { draft.value = value; invalid.value = false })

function languageLabel(value: LocaleChoice, label: string) {
  return value === 'system' ? t('appearance.system') : label
}

function chooseColor(value: string) {
  if (props.disabled) return
  const normalized = normalizeAccent(value)
  if (normalized) {
    invalid.value = false
    draft.value = normalized
    emit('update:accent', normalized)
  }
}

function commitColor() {
  invalid.value = !normalizeAccent(draft.value)
  if (!invalid.value) chooseColor(draft.value)
}

function reset() {
  emit('update:mode', 'system')
  chooseColor(DEFAULT_ACCENT)
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
    <div class="appearance-row accent-row">
      <label class="appearance-label" for="custom-accent">{{ t('appearance.accent') }}</label>
      <div class="accent-controls">
        <div class="accent-presets" role="group" :aria-label="t('appearance.presets')">
          <el-tooltip v-for="preset in presets" :key="preset.value" :content="t(preset.key)" placement="top">
            <button type="button" class="accent-swatch" :disabled="disabled" :class="{ selected: accent.toLowerCase() === preset.value }" :style="{ '--swatch-color': preset.value }" :aria-label="t(preset.key)" :aria-pressed="accent.toLowerCase() === preset.value" @click="chooseColor(preset.value)">
              <el-icon v-if="accent.toLowerCase() === preset.value"><Check /></el-icon>
            </button>
          </el-tooltip>
        </div>
        <div class="custom-accent-controls">
          <input id="custom-accent" class="accent-picker" type="color" :disabled="disabled" :value="accent" :aria-label="t('appearance.custom')" @input="chooseColor(($event.target as HTMLInputElement).value)">
          <input v-model="draft" class="accent-hex" type="text" :disabled="disabled" maxlength="7" spellcheck="false" :aria-label="t('appearance.hex')" :aria-invalid="invalid" :aria-describedby="invalid ? 'accent-error' : undefined" @change="commitColor" @keydown.enter.prevent="commitColor">
        </div>
        <p v-if="invalid" id="accent-error" class="accent-error" role="alert">{{ t('appearance.invalid') }}</p>
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
