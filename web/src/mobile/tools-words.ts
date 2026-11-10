import { t } from '../lib/i18n/index.ts'
import type { Key } from '../lib/i18n/en/index.ts'
import type { StepKind } from './tools.ts'

// tools.ts stays import-free and keeps its English defaults for the engine and pinned model tests.
export const toolText = (key: string, params?: Record<string, unknown>): string => t(key as Key, params)
const KEY_MESSAGES: Partial<Record<StepKind, Key>> = {
  describe: 'processing.error.pcKey', categorize: 'processing.error.pcKey',
  index: 'processing.error.indexKey', analyze: 'processing.error.analyzeKey',
}
export const keyMessage = (kind: StepKind): string => KEY_MESSAGES[kind] ? t(KEY_MESSAGES[kind]!) : ''

const REPLACEMENTS: Partial<Record<StepKind, Key>> = {
  thumb: 'processing.action.thumb.replace', describe: 'processing.action.describe.replace',
  categorize: 'processing.action.categorize.replace', analyze: 'processing.action.analyze.replace',
}
export const replaceText = (kind: StepKind): string => REPLACEMENTS[kind] ? t(REPLACEMENTS[kind]!) : ''
