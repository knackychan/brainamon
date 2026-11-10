import type { messages as English } from '../en/onboarding.ts'
import type { Localized } from '../en/index.ts'

export const messages = {
  "onboarding.answer.skip": "略過",
  "onboarding.answer.question": "你有在電腦上使用 Brainamon 嗎？",
  "onboarding.answer.helpTitle": "手機上的 Brainamon",
  "onboarding.answer.helpLabel": "關於手機應用程式",
  "onboarding.answer.help": "這個手機應用程式讓你隨時瀏覽電腦上的資料庫。請保留電腦版應用程式，以使用完整功能，包括影片分析與 Claude Code 整合。",
  "onboarding.answer.pc": "是，連結我的電腦",
  "onboarding.answer.pcHelp": "電腦上的資料庫會顯示在這裡",
  "onboarding.answer.phone": "還沒，先使用這支手機",
  "onboarding.answer.phoneHelp": "儲存連結和筆記，之後再連結電腦",
  "onboarding.answer.desktop": "取得電腦版應用程式",
  "onboarding.task.title": "開始使用",
  "onboarding.task.done": "完成",
  "onboarding.task.count": "{done}／{total}",
  "onboarding.task.hide": "隱藏",
  "onboarding.task.doneSuffix": "，完成",
  "onboarding.task.ready": "Brainamon 已可使用。",
  "onboarding.task.install": "安裝 Brainamon",
  "onboarding.task.save": "儲存第一個連結",
  "onboarding.task.wiskit": "啟用 Wiskit",
  "onboarding.coach.help": "從任何應用程式分享到 Brainamon，或點選新增。",
  "onboarding.coach.close": "知道了",
} as const satisfies Localized<typeof English>


