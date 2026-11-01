import type { Plugin } from 'vue'
import {
  ElAlert, ElButton, ElCheckbox, ElDropdown, ElDropdownItem, ElDropdownMenu,
  ElEmpty, ElIcon, ElInput, ElInputNumber, ElLoading, ElOption, ElOptionGroup,
  ElProgress, ElSelect, ElSwitch, ElTable, ElTableColumn, ElTag, ElTooltip,
} from 'element-plus'

/** Shared by production and integration tests so missing registrations are observable. */
export const campusUi: Plugin = {
  install(app) {
    for (const component of [
      ElAlert, ElButton, ElCheckbox, ElDropdown, ElDropdownItem, ElDropdownMenu,
      ElEmpty, ElIcon, ElInput, ElInputNumber, ElOption, ElOptionGroup,
      ElProgress, ElSelect, ElSwitch, ElTable, ElTableColumn, ElTag, ElTooltip,
    ]) app.use(component)
    app.use(ElLoading)
  },
}
