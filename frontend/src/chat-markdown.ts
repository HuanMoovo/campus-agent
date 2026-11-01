import { renderMarkdown } from './markdown'

/** Per-message rendering state; callers keep the original text for actions and persistence. */
export function createChatMarkdown(publish: (html: string) => void) {
  let identity: unknown = Symbol('uninitialized message')
  let text = ''
  let renderedText = ''
  let renderedAt = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let disposed = false

  function cancel() {
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
  }

  function render() {
    cancel()
    if (disposed || text === renderedText) return
    renderedText = text
    renderedAt = Date.now()
    publish(text ? renderMarkdown(text) : '')
  }

  return {
    update(nextText: string, streaming: boolean, message: unknown) {
      if (disposed) return
      if (identity !== message) {
        cancel()
        identity = message
        renderedText = ''
        renderedAt = 0
        publish('')
      }
      text = nextText
      if (text === renderedText) { cancel(); return }
      // First content and every terminal state bypass the cadence timer.
      const remaining = 80 - (Date.now() - renderedAt)
      if (!streaming || !renderedText || remaining <= 0) render()
      else if (timer === undefined) timer = setTimeout(render, remaining)
    },
    dispose() { disposed = true; cancel() },
  }
}
