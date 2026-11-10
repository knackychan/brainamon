import { messages as english, type Key } from './en/index.ts'

export type Lang = 'en' | 'fr' | 'zh-Hant'
export type Choice = 'auto' | Lang
export type Plural = { other: string; zero?: string; one?: string; two?: string; few?: string; many?: string }
export type Message = string | Plural
export type Catalog = Record<string, Message>
export type Params = Record<string, unknown>

export const LANGS = [
  { id: 'en', name: 'English', html: 'en', intl: 'en', ready: true },
  { id: 'fr', name: 'Français', html: 'fr', intl: 'fr', ready: false },
  { id: 'zh-Hant', name: '繁體中文', html: 'zh-Hant-TW', intl: 'zh-Hant-TW', ready: false },
] as const

const own = (o: object, key: PropertyKey) => Object.prototype.hasOwnProperty.call(o, key)
const supported = (value: unknown): value is Lang => value === 'en' || value === 'fr' || value === 'zh-Hant'

export function pickLang(choice: unknown, tags: readonly string[], readiness: Partial<Record<Lang, boolean>> = {}): Lang {
  if (supported(choice)) return choice
  for (const tag of Array.isArray(tags) ? tags : []) {
    try {
      const primary = Intl.getCanonicalLocales(tag)[0]?.split('-')[0].toLowerCase()
      const candidate = primary === 'en' ? 'en' : primary === 'fr' ? 'fr' : primary === 'zh' ? 'zh-Hant' : null
      if (candidate && (candidate === 'en' || (readiness[candidate] ?? LANGS.find(l => l.id === candidate)!.ready))) return candidate
    } catch { /* malformed browser language */ }
  }
  return 'en'
}

const protectedText = /(<code>[\s\S]*?<\/code>|<\/?(?:b|i|code|a(?::[\w.-]+)?)>|\{[^{}]+\}|https?:\/\/[^\s<>]+|(?:[A-Za-z]:[\\/]|\\\\|\.{1,2}\/|\/)[^\s<>]+)/g
export function frenchTypography(value: string): string {
  return value.split(protectedText).map((part, i) => i % 2 ? part : part
    .replace(/[ \u202f]*([?!;]+)/g, '\u202f$1')
    .replace(/[ \u00a0]*(:)/g, '\u00a0$1')
    .replace(/«[ \u00a0]*/g, '«\u00a0')
    .replace(/[ \u00a0]*»/g, '\u00a0»')).join('')
}

function prepareFrench(catalog: Catalog): Catalog {
  return Object.fromEntries(Object.entries(catalog).map(([key, value]) => [key, typeof value === 'string'
    ? frenchTypography(value)
    : { ...Object.fromEntries(Object.entries(value).map(([form, text]) => [form, frenchTypography(text)])), other: frenchTypography(value.other) }]))
}

let current: Lang = 'en'
let active: Catalog = english
export const lang = (): Lang => current

export function setup(catalogs: Partial<Record<Lang, Catalog>>, choice: unknown, tags: readonly string[], readiness: Partial<Record<Lang, boolean>> = {}): Lang {
  current = pickLang(choice, tags, readiness)
  const selected = current === 'en' ? english : catalogs[current] ?? {}
  active = current === 'fr' ? prepareFrench(selected) : selected
  return current
}

export function template(key: Key, params: Params = {}): string {
  if (!own(english, key)) return key
  const values = params && typeof params === 'object' ? params : {}
  const found = own(active, key)
  const message: Message | undefined = found ? active[key] : english[key]
  if (message === undefined) return key
  let text: string
  if (typeof message === 'string') text = message
  else {
    const n = own(values, 'n') ? values.n : undefined
    const locale = found ? current : 'en'
    const category = typeof n === 'number' && Number.isFinite(n) ? new Intl.PluralRules(locale).select(n) : 'other'
    text = own(message, category) ? message[category as keyof Plural] ?? message.other : message.other
  }
  return text
}

export function t(key: Key, params: Params = {}): string {
  const values = params && typeof params === 'object' ? params : {}
  return template(key, values).replace(/\{([\w.-]+)\}/g, (match, name: string) => own(values, name) ? String(values[name]) : match)
}

export type { Key }
