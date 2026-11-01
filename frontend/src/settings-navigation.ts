export const SETTINGS_CATEGORIES = ['general', 'models', 'usage', 'connections', 'data'] as const
export type SettingsCategory = typeof SETTINGS_CATEGORIES[number]
