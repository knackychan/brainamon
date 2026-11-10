// The shared prompt files (knowledge/prompts/, read by knowledge/ask_core.py and synth.py too), bundled
// into the phone page. vite.config.ts lets the dev server read that folder.
import ask from '../../../../knowledge/prompts/ask_quick.json'
import synth from '../../../../knowledge/prompts/synth.json'
import deep from '../../../../knowledge/prompts/ask_deep.json'
// the AI settings of a phone with no PC (plans/08-phone-solo.md), written from core/ai_client.py
import phoneAi from '../../../../knowledge/prompts/phone_ai.json'
import languages from '../../../../knowledge/prompts/languages.json'
import type { AskPrompts } from './quick.ts'
import type { SynthPrompts } from './synth.ts'
import type { DeepPrompts } from './deep.ts'

export const ASK = ask as unknown as AskPrompts
export const SYNTH = synth as unknown as SynthPrompts
export const DEEP = deep as unknown as DeepPrompts
export const PHONE_AI = phoneAi
export const LANGUAGES = languages
