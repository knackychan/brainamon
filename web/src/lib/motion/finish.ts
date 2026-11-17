import type { JobSnap, JobsState } from '../events.svelte.ts'

// Only a manual run that actually did work holds its finish, never a stop or an old hello snapshot.
export function finishedJob(prev: JobsState, next: JobsState): JobSnap | null {
  const last = next.last, id = prev.current?.id
  return id !== undefined && last?.id === id && next.current?.id !== id &&
    last.state === 'finished' && last.done > 0 && !last.auto ? last : null
}

// An automatic follow-up (indexing) runs underneath the manual run's held finish.
export function endsHold(prev: JobsState, next: JobsState): boolean {
  return !!next.current && next.current.id !== prev.current?.id && !next.current.auto
}
