import { lang, t } from '../../lib/i18n/index.ts'
import type { Key } from '../../lib/i18n/en/index.ts'

const KINDS: Record<string, Key> = {
  existing: 'canvas.proposal.existingKind', text: 'canvas.proposal.textKind', frame: 'canvas.proposal.frameKind', thumbnail: 'canvas.proposal.thumbnailKind',
}
export const proposalKind = (kind: string): string => KINDS[kind] ? t(KINDS[kind]) : kind
export const layoutName = (layout: string): string => lang() === 'en' ? layout : layout === 'rows' ? t('canvas.composer.rows') : layout === 'columns' ? t('canvas.composer.columns') : layout
