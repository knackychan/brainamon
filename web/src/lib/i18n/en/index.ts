import { messages as common } from './common.ts'
import { messages as shell } from './shell.ts'
import { messages as library } from './library.ts'
import { messages as item } from './item.ts'
import { messages as notes } from './notes.ts'
import { messages as canvas } from './canvas.ts'
import { messages as wiskit } from './wiskit.ts'
import { messages as processing } from './processing.ts'
import { messages as capture } from './capture.ts'
import { messages as imports } from './imports.ts'
import { messages as voice } from './voice.ts'
import { messages as settings } from './settings.ts'
import { messages as backup } from './backup.ts'
import { messages as recovery } from './recovery.ts'
import { messages as onboarding } from './onboarding.ts'
import { messages as shared } from './shared.ts'
import { messages as legal } from './legal.ts'

export const areas = [common, shell, library, item, notes, canvas, wiskit, processing, capture, imports, voice, settings, backup, recovery, onboarding, shared, legal] as const
export const messages = { ...common, ...shell, ...library, ...item, ...notes, ...canvas, ...wiskit, ...processing, ...capture, ...imports, ...voice, ...settings, ...backup, ...recovery, ...onboarding, ...shared, ...legal } as const

export type Key = keyof typeof messages
export type Localized<T> = { [K in keyof T]: T[K] extends string ? string : { one?: string; other: string; zero?: string; two?: string; few?: string; many?: string } }
export function exactCatalog<T extends Localized<typeof messages>>(value: T & Record<Exclude<keyof T, Key>, never>): T { return value }

