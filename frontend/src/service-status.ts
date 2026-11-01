export function serviceResultStatus(kind: string, value: { demo?: boolean; items?: unknown }): string {
  if (value.demo === true && ['notices', 'library', 'dining', 'shuttle'].includes(kind)
      && Array.isArray(value.items) && value.items.length === 0) return 'unconfigured'
  return value.demo === true ? 'demo' : value.demo === false ? 'connected' : 'unknown'
}
