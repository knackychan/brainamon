import { lang, t } from '../lib/i18n/index.ts'
import type { Key } from '../lib/i18n/en/index.ts'

const KINDS: Record<string, Key> = {
  'Topic digest': 'notes.kind.topic', Personal: 'notes.kind.personal', Synthesized: 'notes.kind.synthesized',
}
export const noteKind = (kind: string): string => Object.hasOwn(KINDS, kind) ? t(KINDS[kind]) : kind

const INKS: Record<string, Key> = {
  "graphite": "notes.editor.ink.graphite",
  "indigo": "notes.editor.ink.indigo",
  "sky": "notes.editor.ink.sky",
  "leaf": "notes.editor.ink.leaf",
  "sun": "notes.editor.ink.sun",
  "ember": "notes.editor.ink.ember",
  "rose": "notes.editor.ink.rose",
  "mint": "notes.editor.ink.mint",
  "peach": "notes.editor.ink.peach"
}
const MARKS: Record<string, Key> = {
  "sky": "notes.editor.mark.sky",
  "sun": "notes.editor.mark.sun",
  "mint": "notes.editor.mark.mint",
  "peach": "notes.editor.mark.peach"
}
const STAMPS: Record<string, Key> = {
  "flower": "notes.stamps.name.flower",
  "sun": "notes.stamps.name.sun",
  "star": "notes.stamps.name.star",
  "heart": "notes.stamps.name.heart",
  "check": "notes.stamps.name.check",
  "arrow": "notes.stamps.name.arrow",
  "sprout": "notes.stamps.name.sprout",
  "mushroom": "notes.stamps.name.mushroom",
  "cloud": "notes.stamps.name.cloud",
  "bolt": "notes.stamps.name.bolt",
  "coffee": "notes.stamps.name.coffee",
  "bulb": "notes.stamps.name.bulb",
  "kettlebell": "notes.stamps.name.kettlebell",
  "pin": "notes.stamps.name.pin",
  "note": "notes.stamps.name.note",
  "question": "notes.stamps.name.question",
  "snail": "notes.stamps.name.snail",
  "sparkle": "notes.stamps.name.sparkle",
  "flag": "notes.stamps.name.flag",
  "smile": "notes.stamps.name.smile"
}
export const inkName = (id: string): string => Object.hasOwn(INKS, id) ? t(INKS[id]) : id
export const markerName = (id: string): string => Object.hasOwn(MARKS, id) ? t(MARKS[id]) : id
export const stampName = (id: string): string => Object.hasOwn(STAMPS, id) ? t(STAMPS[id]) : id

// Only a newly inserted dated heading uses the UI locale; existing Markdown is retained verbatim.
export function datedSection(body: string, now = new Date()): string {
  const locale = lang() === 'en' ? 'en-GB' : lang() === 'fr' ? 'fr' : 'zh-Hant-TW'
  const stamp = now.toLocaleString(locale, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
  const trimmed = body.replace(/\s+$/, '')
  return (trimmed ? trimmed + '\n\n' : '') + `## ${stamp}\n\n`
}
