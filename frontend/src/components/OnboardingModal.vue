<script setup lang="ts">
import { ChatLineRound, Clock, Search, Setting } from '@element-plus/icons-vue'

import { t } from '../i18n'
import mensLogo from '../assets/mens.png'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ (event: 'update:open', value: boolean): void; (event: 'done'): void }>()

const steps = [
  { icon: ChatLineRound, title: 'onb.step1.title', desc: 'onb.step1.desc' },
  { icon: Setting, title: 'onb.step2.title', desc: 'onb.step2.desc' },
  { icon: Clock, title: 'onb.step3.title', desc: 'onb.step3.desc' },
  { icon: Search, title: 'onb.step4.title', desc: 'onb.step4.desc' },
]
</script>

<template>
  <div v-if="open" class="onboarding" role="dialog" :aria-label="t('onb.title')">
    <div class="onb-panel">
      <img class="onb-logo" :src="mensLogo" alt="Mens" />
      <h2>{{ t('onb.title') }}</h2>
      <p class="onb-sub">{{ t('onb.subtitle') }}</p>
      <div class="onb-steps">
        <div v-for="step in steps" :key="step.title" class="onb-step">
          <el-icon :size="18"><component :is="step.icon" /></el-icon>
          <div><strong>{{ t(step.title) }}</strong><small>{{ t(step.desc) }}</small></div>
        </div>
      </div>
      <el-button type="primary" @click="emit('done')">{{ t('onb.start') }}</el-button>
    </div>
  </div>
</template>

<style scoped>
.onboarding { position: fixed; inset: 0; z-index: 70; background: rgba(18, 31, 34, .45); display: flex; justify-content: center; align-items: center; padding: 24px 16px; }
.onb-panel { width: min(520px, 100%); background: var(--surface); border: 1px solid var(--border); border-radius: 6px; box-shadow: 0 18px 50px #00000033; padding: 26px 26px 22px; text-align: left; }
.onb-logo { width: 44px; height: 44px; object-fit: contain; border-radius: 20%; }
.onb-panel h2 { margin: 12px 0 6px; font-size: 19px; color: var(--text); }
.onb-sub { margin: 0 0 18px; font-size: 12.5px; color: var(--text-muted); line-height: 1.6; }
.onb-steps { display: flex; flex-direction: column; gap: 14px; margin-bottom: 20px; }
.onb-step { display: flex; gap: 12px; align-items: flex-start; color: var(--accent-text); }
.onb-step strong { display: block; font-size: 13px; color: var(--text); }
.onb-step small { display: block; margin-top: 3px; font-size: 12px; color: var(--text-muted); line-height: 1.55; }
</style>
