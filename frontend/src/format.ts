/** Shared presentation helpers: tones, labels and formatters. */
import type { Answer, Question } from './types'

export const ROUTING_TONE: Record<string, string> = {
  act: 'green',
  review: 'amber',
  default: 'slate',
}

export const TYPE_LABEL: Record<string, string> = {
  boolean: 'boolean',
  noul: 'yes/no',
  choice: 'choice',
  score: 'score',
}

export const TYPE_TONE: Record<string, string> = {
  boolean: 'indigo',
  noul: 'indigo',
  choice: 'violet',
  score: 'teal',
}

export const RUN_STATUS_TONE: Record<string, string> = {
  pending: 'slate',
  running: 'amber',
  done: 'green',
  error: 'red',
}

export const pct = (value: number | null | undefined, digits = 0): string =>
  value === null || value === undefined ? '—' : `${(value * 100).toFixed(digits)}%`

export const ms = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return '—'
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`
}

export const num = (value: number | null | undefined, digits = 0): string =>
  value === null || value === undefined ? '—' : value.toFixed(digits)

export const when = (iso: string | null | undefined): string => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export const titleCase = (value: string): string =>
  value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

export const tone = (map: Record<string, string>, key: string, fallback = 'slate'): string =>
  map[key] ?? fallback

/** Compact display of one typed answer. */
export function answerLabel(answer: Answer, question?: Question): string {
  if (answer.type === 'boolean' || answer.type === 'noul') {
    return answer.value === true || answer.value === 'true' ? 'YES' : 'NO'
  }
  if (answer.type === 'score') {
    const level = answer.level ?? Math.round(Number(answer.value ?? 0))
    const labels = Array.isArray(question?.criteria) ? (question!.criteria as string[]) : null
    const short = labels?.[level]?.split(/[.:]/)[0] ?? `L${level}`
    return `${level} · ${short.length > 28 ? `${short.slice(0, 28)}…` : short}`
  }
  return titleCase(String(answer.value ?? '—'))
}

export function answerTone(answer: Answer): string {
  if (answer.type === 'boolean' || answer.type === 'noul') {
    const yes = answer.value === true || answer.value === 'true'
    return yes ? 'orange' : 'green'
  }
  return tone(ROUTING_TONE, answer.routing ?? '', 'indigo')
}

export const probColor = (index: number): string => {
  const palette = ['#4338ca', '#0d9488', '#d97706', '#7c3aed', '#0891b2', '#be123c', '#65a30d']
  return palette[index % palette.length]
}
