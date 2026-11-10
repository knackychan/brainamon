import type { Lang } from '../../lib/i18n/index.ts'
import { LANGUAGES } from './prompts.ts'

export function appendLanguage(prompt: string, language: Lang, operation: keyof typeof LANGUAGES.fr): string {
  return language === 'en' ? prompt : `${prompt}\n\n${LANGUAGES[language][operation]}`
}
