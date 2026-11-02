// Globals from the locked card files (design/card-designs/engine.js and full-art-v2/fa2.js),
// loaded as classic scripts by index.html and never edited. Top-level const/let/function/class
// declarations of a classic script are visible to module code by name.
interface CardModel {
  key: string; id: number; hex: string; title: string; creator: string; src: string
  rar: 'holo' | 'uncommon' | 'common'; rank: number; isNew?: boolean; size: string; date: string
  cat: string; focus: number; desc: string
}
declare function cardFA2(it: CardModel): string
declare function cardHTML(it: CardModel, variant: string): string
declare class HandCard {
  constructor(slot: Element, opts?: { onTap?: () => void; idle?: boolean; flip?: number; onFace?: (front: boolean) => void })
  idle: boolean
  hover: boolean
  onscreen: boolean
  settle(): void
  // the engine's own pointer handlers, fed by src/mobile/finger.ts on the phone
  press(e: PointerLike): void
  move(e: PointerLike): void
  up(e: PointerLike): void
  cancel(): void
}
interface PointerLike { button: number; pointerId: number; pointerType: string; clientX: number; clientY: number }
declare const TYPE: Record<string, string>
declare const ALL: Set<HandCard>
declare const ACTIVE: Set<HandCard>
declare const IO: IntersectionObserver | null
declare const MOTION: { off: boolean }
declare const FEEL: { idleX: number; idleY: number; idleRoll: number; idleBob: number }
declare function setMotion(on: boolean): void
declare function wake(h: HandCard): void
