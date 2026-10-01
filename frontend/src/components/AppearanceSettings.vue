<script setup lang="ts">
import { ref, watch } from 'vue'
import { Check, Monitor, Moon, RefreshLeft, Sunny } from '@element-plus/icons-vue'
import { DEFAULT_ACCENT, normalizeAccent, type AppearanceMode } from '../appearance'

const props = defineProps<{ mode: AppearanceMode; accent: string; disabled?: boolean }>()
const emit = defineEmits<{
  'update:mode': [value: AppearanceMode]
  'update:accent': [value: string]
}>()
const modes = [
  { value: 'light' as const, label: '浅色', icon: Sunny },
  { value: 'dark' as const, label: '深色', icon: Moon },
  { value: 'system' as const, label: '跟随系统', icon: Monitor },
]
const presets = [
  { value: DEFAULT_ACCENT, label: '松绿' },
  { value: '#2563eb', label: '湖蓝' },
  { value: '#8b5cf6', label: '紫罗兰' },
  { value: '#c84062', label: '玫红' },
  { value: '#c66a17', label: '琥珀' },
  { value: '#5e6873', label: '石墨' },
]
const draft = ref(props.accent)
const invalid = ref(false)
watch(() => props.accent, value => { draft.value = value; invalid.value = false })

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
      <div class="settings-copy"><h2 id="appearance-heading">外观</h2></div>
      <el-tooltip content="恢复默认外观" placement="top">
        <el-button :icon="RefreshLeft" :disabled="disabled" aria-label="恢复默认外观" @click="reset" />
      </el-tooltip>
    </div>
    <div class="appearance-row">
      <span id="appearance-mode-label" class="appearance-label">显示模式</span>
      <div class="appearance-modes" role="radiogroup" aria-labelledby="appearance-mode-label">
        <label v-for="item in modes" :key="item.value" class="appearance-mode" :class="{ selected: mode === item.value }">
          <input type="radio" name="appearance-mode" :value="item.value" :checked="mode === item.value" :disabled="disabled" @change="emit('update:mode', item.value)">
          <el-icon><component :is="item.icon" /></el-icon><span>{{ item.label }}</span>
        </label>
      </div>
    </div>
    <div class="appearance-row accent-row">
      <label class="appearance-label" for="custom-accent">主题色</label>
      <div class="accent-controls">
        <div class="accent-presets" role="group" aria-label="预设主题色">
          <el-tooltip v-for="preset in presets" :key="preset.value" :content="preset.label" placement="top">
            <button type="button" class="accent-swatch" :disabled="disabled" :class="{ selected: accent.toLowerCase() === preset.value }" :style="{ '--swatch-color': preset.value }" :aria-label="preset.label" :aria-pressed="accent.toLowerCase() === preset.value" @click="chooseColor(preset.value)">
              <el-icon v-if="accent.toLowerCase() === preset.value"><Check /></el-icon>
            </button>
          </el-tooltip>
        </div>
        <div class="custom-accent-controls">
          <input id="custom-accent" class="accent-picker" type="color" :disabled="disabled" :value="accent" aria-label="自定义主题色" @input="chooseColor(($event.target as HTMLInputElement).value)">
          <input v-model="draft" class="accent-hex" type="text" :disabled="disabled" maxlength="7" spellcheck="false" aria-label="主题色十六进制值" :aria-invalid="invalid" :aria-describedby="invalid ? 'accent-error' : undefined" @change="commitColor" @keydown.enter.prevent="commitColor">
        </div>
        <p v-if="invalid" id="accent-error" class="accent-error" role="alert">请输入 #RRGGBB 格式的颜色值</p>
      </div>
    </div>
  </section>
</template>
