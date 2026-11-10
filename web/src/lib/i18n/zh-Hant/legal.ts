import type { messages as English } from '../en/legal.ts'
import type { Localized } from '../en/index.ts'

export const messages = {
  "legal.label.contact": "聯絡 Frederic TOMAS：",
  "legal.label.privacy": "隱私權政策",
  "legal.label.license": "軟體授權",
  "legal.label.notices": "第三方聲明",
  "legal.label.original": "英文原文",
} as const satisfies Localized<typeof English>


