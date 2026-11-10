import { lang, t } from './index.ts'

type Locales = string | string[] | undefined
type DateValue = string | number | Date
const locale = (english: Locales): Locales => lang() === 'en' ? english : lang() === 'fr' ? 'fr' : 'zh-Hant-TW'
const date = (value: DateValue): Date => value instanceof Date ? value : new Date(value)

export const fmtDate = (value: DateValue, options: Intl.DateTimeFormatOptions, englishLocale?: Locales): string =>
  date(value).toLocaleDateString(locale(englishLocale), options)

export const fmtTime = (value: DateValue, options: Intl.DateTimeFormatOptions, englishLocale?: Locales): string =>
  date(value).toLocaleTimeString(locale(englishLocale), options)

export const fmtNum = (value: number, englishLocale?: Locales, options?: Intl.NumberFormatOptions): string =>
  value.toLocaleString(locale(englishLocale), options)

export function fmtSize(bytes: number): string {
  const unit = bytes >= 1e9 ? 'gb' : bytes >= 1e6 ? 'mb' : 'kb'
  const digits = unit === 'gb' || (unit === 'mb' && bytes < 1e7) ? 1 : 0
  const value = unit === 'gb' ? bytes / 1e9 : unit === 'mb' ? bytes / 1e6 : Math.max(1, Math.round(bytes / 1e3))
  const number = lang() === 'en' ? value.toFixed(digits) : fmtNum(value, undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return `${number} ${t(unit === 'gb' ? 'common.size.gb' : unit === 'mb' ? 'common.size.mb' : 'common.size.kb')}`
}

// The Item screen's byte progress and video size: always megabytes with one decimal, whatever the size
// (a distinct English call-site format from fmtSize, whose unit follows the size).
export const fmtMegabytes = (bytes: number): string => {
  const value = bytes / 1e6
  const number = lang() === 'en' ? value.toFixed(1) : fmtNum(value, undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  return `${number} ${t('common.size.mb')}`
}

export function fmtAgo(ms: number, now = Date.now()): string {
  if (!ms) return t('common.ago.never')
  const minutes = Math.round((now - ms) / 60000)
  if (minutes < 1) return t('common.ago.now')
  if (minutes < 60) return t('common.ago.minutes', { n: minutes })
  if (minutes < 1440) return t('common.ago.hours', { n: Math.round(minutes / 60) })
  return t('common.ago.days', { n: Math.round(minutes / 1440) })
}

export function fmtList(values: readonly string[], english?: { middle: string; last: string; pair: string }): string {
  if (values.length < 2) return values[0] ?? ''
  const separators = lang() === 'en' && english ? english : {
    middle: t('common.list.middle'), last: t('common.list.last'), pair: t('common.list.pair'),
  }
  if (values.length === 2) return values.join(separators.pair)
  return values.slice(0, -1).join(separators.middle) + separators.last + values[values.length - 1]
}
