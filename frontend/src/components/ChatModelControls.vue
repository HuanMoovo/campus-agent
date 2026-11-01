<script setup lang="ts">
import { computed } from 'vue'
import type { LocalModels, ModelConfig } from '../api'
import { providerGroups, workspaceModelForProvider, type ModelCatalogEntry } from '../model-providers'
import { t } from '../i18n'
import type { ProjectPermission } from '../desktop'
import { effectiveReasoning, REASONING_LEVELS, type ReasoningCapability, type ReasoningPreference, isReasoningLevel } from '../reasoning'

const props = defineProps<{
  modelValue: string
  reasoning: ReasoningPreference
  capability: ReasoningCapability
  config: ModelConfig | null
  localModels: LocalModels | null
  localModel: string
  localBusy: boolean
  disabled: boolean
  projectPermission?: ProjectPermission
  projectWriteAvailable?: boolean
}>()
const emit = defineEmits<{
  selectModel: [value: string]
  selectReasoning: [value: ReasoningPreference]
  selectProjectPermission: [value: ProjectPermission]
  refresh: []
}>()
const groups = computed(() => providerGroups(props.config))
const installed = computed(() => props.localModels?.installed.some(item => item.name === props.localModel))
const selectedReasoning = computed(() => effectiveReasoning(props.reasoning, props.capability))
const reasoningNote = computed(() => {
  if (props.modelValue === 'auto') return t('chat.reasoningAutoRoute')
  if (props.capability.mode !== 'effort') return t(`chat.reasoningMode.${props.capability.mode}`)
  return props.reasoning !== 'auto' && selectedReasoning.value === 'auto' ? t('chat.reasoningUnavailable') : ''
})
function providerLabel(item: ModelCatalogEntry) {
  return item.id === 'openai_compatible' ? t('model.compatible') : item.label
}
function configuredModel(item: ModelCatalogEntry) {
  return props.config?.providers[item.id]?.model?.trim() || ''
}
function modelLabel(item: ModelCatalogEntry) {
  const model = configuredModel(item)
  return model ? `${providerLabel(item)} · ${model}` : providerLabel(item)
}
function selectModel(value: string) {
  if (!props.disabled) emit('selectModel', value)
}
function selectReasoning(value: unknown) {
  if (props.disabled || !(value === 'auto' || value === 'deep' || isReasoningLevel(value))) return
  if (effectiveReasoning(value, props.capability) === value) emit('selectReasoning', value)
}
function selectProjectPermission(value: unknown) {
  if (props.disabled || value !== 'read_only' && value !== 'confirm' || value === 'confirm' && !props.projectWriteAvailable) return
  emit('selectProjectPermission', value)
}
</script>

<template>
  <div class="composer-preferences" role="group" :aria-label="t('chat.preferences')">
    <div class="chat-model-picker composer-control">
      <label for="chat-model-select">{{ t('chat.modelLabel') }}</label>
      <el-select id="chat-model-select" :model-value="modelValue" :aria-label="t('chat.modelPicker')"
        :disabled="disabled" filterable :no-match-text="t('chat.modelNoMatch')" placement="top-start" popper-class="chat-model-menu" :fit-input-width="false"
        @update:model-value="selectModel" @visible-change="(visible: boolean) => { if (visible) emit('refresh') }">
        <el-option value="auto" :label="t('app.model.auto')" />
        <el-option-group v-for="group in groups" :key="group.id" :label="t(`model.group.${group.id}`)">
          <el-option v-for="item in group.entries" :key="item.id" :value="workspaceModelForProvider(item.id)" :label="modelLabel(item)">
            <span class="composer-model-option"><span>{{ providerLabel(item) }}</span><small v-if="configuredModel(item)">{{ configuredModel(item) }}</small></span>
          </el-option>
        </el-option-group>
        <el-option-group :label="t('chat.modelLocal')">
          <el-option v-if="modelValue.startsWith('local:') && !installed" :value="`local:${localModel}`" :label="localModel || t('app.model.local')" disabled />
          <el-option v-for="item in localModels?.installed || []" :key="item.name" :value="`local:${item.name}`" :label="item.name" :disabled="!localModels?.running" />
          <el-option v-if="!localModels?.installed.length && !modelValue.startsWith('local:')" value="unavailable"
            :label="localBusy ? t('chat.localChecking') : localModels?.running ? t('chat.localNone') : t('chat.ollamaOffline')" disabled />
        </el-option-group>
      </el-select>
    </div>
    <div class="chat-reasoning-picker composer-control">
      <label for="chat-reasoning-select">{{ t('chat.reasoning') }}</label>
      <el-select id="chat-reasoning-select" :model-value="selectedReasoning" :aria-label="t('chat.reasoning')"
        :disabled="disabled" placement="top-end" popper-class="chat-reasoning-menu" :fit-input-width="false"
        :title="t('chat.reasoningSupport')" :aria-describedby="reasoningNote ? 'chat-reasoning-note' : undefined" @update:model-value="selectReasoning">
        <el-option value="auto" :label="t('chat.reasoningDefault')"><span class="reasoning-option-text"><strong>{{ t('chat.reasoningDefault') }}</strong><small>{{ t('chat.reasoningDefaultDesc') }}</small></span></el-option>
        <el-option v-if="capability.mode === 'toggle'" value="deep" :label="t('chat.reasoningOn')"><span class="reasoning-option-text"><strong>{{ t('chat.reasoningOn') }}</strong><small>{{ t('chat.reasoningMode.toggle') }}</small></span></el-option>
        <el-option v-for="level in REASONING_LEVELS" :key="level" :value="level" :label="t(`chat.reasoningLevel.${level}`)"
          :disabled="capability.mode !== 'effort' || !capability.levels.includes(level)">
          <span class="reasoning-option-text"><strong>{{ t(`chat.reasoningLevel.${level}`) }}</strong><small>{{ t(`chat.reasoningDesc.${level}`) }}</small></span>
        </el-option>
      </el-select>
    </div>
    <div class="chat-permission-picker composer-control">
      <label for="chat-permission-select">{{ t('chat.projectPermission') }}</label>
      <el-select id="chat-permission-select" :model-value="projectPermission || 'read_only'" :aria-label="t('chat.projectPermission')"
        :disabled="disabled" placement="top-end" popper-class="chat-permission-menu" :fit-input-width="false"
        :title="t('chat.projectPermissionScope')" aria-describedby="chat-permission-note" @update:model-value="selectProjectPermission">
        <el-option value="read_only" :label="t('chat.projectPermissionReadOnly')"><span class="reasoning-option-text"><strong>{{ t('chat.projectPermissionReadOnly') }}</strong><small>{{ t('chat.projectPermissionReadOnlyDesc') }}</small></span></el-option>
        <el-option value="confirm" :label="t('chat.projectPermissionConfirm')" :disabled="!projectWriteAvailable"><span class="reasoning-option-text"><strong>{{ t('chat.projectPermissionConfirm') }}</strong><small>{{ t(projectWriteAvailable ? 'chat.projectPermissionConfirmDesc' : 'chat.projectPermissionWeb') }}</small></span></el-option>
      </el-select>
    </div>
    <p v-if="reasoningNote" id="chat-reasoning-note" class="composer-reasoning-note">{{ reasoningNote }}</p>
    <p id="chat-permission-note" class="composer-reasoning-note composer-permission-note">{{ t('chat.projectPermissionScope') }}</p>
  </div>
</template>
