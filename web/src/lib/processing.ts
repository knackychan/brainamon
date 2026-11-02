import { isVid, NEED, type NeedKey, type Row } from './library.svelte'

export const PROCESS_ACTIONS: { kind: NeedKey; label: string; description: string; cost: string; replace: string }[] = [
  { kind: 'thumb', label: 'Fetch link info', description: 'Get a link’s thumbnail, title and caption without downloading its video. Start here when a saved link has no preview.', cost: 'No AI for fetching. Some sites need browser cookies.', replace: 'Fetch thumbnails again and replace saved captions. Custom titles and creators are kept.' },
  { kind: 'describe', label: 'Describe', description: 'Write a short static AI summary from the saved post description/caption, video title and thumbnail when available. No video is downloaded, watched or newly transcribed. Available page text or a saved transcript may also be used. Choose Analyze videos for the video’s actual content.', cost: 'Uses your AI model; provider charges may apply.', replace: 'Replace existing AI descriptions.' },
  { kind: 'categorize', label: 'Auto-categorize', description: 'Let AI choose a collection and tags from each item’s available content. Use this to organize unsorted items.', cost: 'Uses your AI model; provider charges may apply.', replace: 'Replace existing collections and tags.' },
  { kind: 'analyze', label: 'Analyze videos', description: 'Use a local video or download it if missing, then sample frames and/or transcribe its audio according to your options. An optional AI report explains the video’s content from those frames and transcript.', cost: 'Optional. Can take several minutes per video. AI and transcription charges may apply.', replace: 'Run video analysis again using the options you choose.' },
  { kind: 'index', label: 'Index for search', description: 'Update search by meaning for items with new or changed text. Ordinary keyword search works without this.', cost: 'Uses your embeddings provider; charges may apply. Unchanged text is skipped.', replace: '' },
]

export function processingEligible(row: Row, kind: NeedKey): boolean {
  return kind === 'thumb' ? /^https?:\/\//i.test(row.url) : kind !== 'analyze' || isVid(row)
}

export function processingTargets(rows: Row[], kind: NeedKey, rerun = false): number[] {
  return rows.filter(r => processingEligible(r, kind) && (kind === 'index' || rerun || !!(r.nd & NEED[kind]))).map(r => r.id)
}

// Recommend one step, never silently chain jobs or opt users into video downloads.
export function recommendedProcessing(rows: Row[]): NeedKey | null {
  return (['thumb', 'describe', 'categorize', 'index'] as NeedKey[])
    .find(k => rows.some(r => processingEligible(r, k) && !!(r.nd & NEED[k]))) ?? null
}

export function processingStatus(row: Row): string {
  const missing = PROCESS_ACTIONS.filter(a => processingEligible(row, a.kind) && !!(row.nd & NEED[a.kind]))
  return missing.length ? `${missing.length} available step${missing.length === 1 ? '' : 's'}` : 'Review processing'
}
