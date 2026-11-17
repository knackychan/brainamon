// The words and the motion switch of the Android site window's tray (projects/motion-language plan 06, native
// SiteTray.java). The window is native, so it cannot call t(): the page sends the labels once, in the phone's
// language, with the native plural rule's two forms (key_one / key_other) and English fallbacks on the Java side.
// Each label is at most 200 characters and the whole set 16 KB (SiteText.java checks both again).
import { lang, template, t } from '../lib/i18n/index.ts'
import { motionOn } from '../lib/motion/motion.ts'

const PLAIN = ['cancel', 'close', 'signIn', 'signedIn', 'check', 'wait', 'reading', 'doneEnd', 'doneKnown', 'doneCap',
  'doneEmpty', 'review', 'back', 'signedClose', 'signCloseOnly', 'unsaveFailed'] as const
const PLURAL = ['newWord', 'known', 'doneNew'] as const

export interface TrayExtras { labels: string; motion: boolean }

// the labels as a JSON object of strings: the plain ones, the two forms of the plural ones and the language
export function trayLabels(siteName: string): string {
  const out: Record<string, string> = { lang: lang() === 'zh-Hant' ? 'zh' : lang() }
  for (const key of PLAIN) out[key] = t(`sitetray.${key}`, { site: siteName })
  for (const key of PLURAL) {
    out[`${key}_one`] = template(`sitetray.${key}`, { n: 1 })
    out[`${key}_other`] = template(`sitetray.${key}`, { n: 2 })
  }
  return JSON.stringify(out)
}

// motion off (the phone's switch or the system's reduced motion) means no ghosts, no sweep and no slide
export const trayFor = (siteName: string): TrayExtras => ({ labels: trayLabels(siteName), motion: motionOn() })
