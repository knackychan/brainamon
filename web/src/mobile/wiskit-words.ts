import { t } from '../lib/i18n/index.ts'

// The shared desktop examples remain English; this array is made only when the phone shows it.
export const askExamples = (): string[] => [
  t('wiskit.example.recipes'), t('wiskit.example.workout'), t('wiskit.example.productivity'),
  t('wiskit.example.travel'), t('wiskit.example.routine'), t('wiskit.example.design'),
]
