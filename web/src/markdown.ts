// Markdown rendering helpers.
//
// All rendered markdown is bound into the DOM with `v-html`, and message
// content is free-form LLM/agent text delivered over an unauthenticated,
// CORS-open broadcast endpoint. `marked` does NOT strip raw HTML, so its output
// must be sanitized with DOMPurify before it reaches the DOM — otherwise a
// crafted `<img src=x onerror=...>` payload executes as stored XSS in every
// viewer's session.
import { marked } from 'marked'
import DOMPurify from 'dompurify'

/** Sanitize already-rendered HTML before it is bound with v-html. */
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html)
}

/** Parse markdown to HTML and sanitize the result. */
export function renderMarkdown(raw: unknown): string {
  return sanitizeHtml(marked.parse(String(raw ?? '')) as string)
}
