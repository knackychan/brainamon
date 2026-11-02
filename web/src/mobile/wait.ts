// A wait with an end: `p`'s answer, or an Error(`message`) after `ms`. A late answer is dropped (and its
// failure swallowed: nobody listens any more). No imports: Node runs this file (tests/test_phone_diagnose.py).
export function withTimeout<T>(p: Promise<T>, ms: number, message: string): Promise<T> {
  p.catch(() => { /* after the wait ended, nobody listens */ })
  let timer: ReturnType<typeof setTimeout> | undefined
  const late = new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error(message)), ms) })
  return Promise.race([p, late]).finally(() => clearTimeout(timer))
}
