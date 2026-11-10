import type { messages as English } from '../en/legal.ts'
import type { Localized } from '../en/index.ts'

export const messages = {
  "legal.label.contact": "Contacter Frederic TOMAS :",
  "legal.label.privacy": "Politique de confidentialité",
  "legal.label.license": "Licence du logiciel",
  "legal.label.notices": "Mentions des tiers",
  "legal.label.original": "Original anglais",
} as const satisfies Localized<typeof English>


