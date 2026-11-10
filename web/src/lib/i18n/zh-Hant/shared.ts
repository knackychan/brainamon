import type { messages as English } from '../en/shared.ts'
import type { Localized } from '../en/index.ts'

export const messages = {
  "shared.analysis.interval": "影格間隔",
  "shared.analysis.seconds": "秒 · 0 = 關閉（不擷取影格）",
  "shared.analysis.transcription": "轉錄",
  "shared.analysis.extract": "擷取音訊並轉錄",
  "shared.analysis.model": "轉錄模型",
  "shared.analysis.openai": "GPT-Transcribe（OpenAI 金鑰）",
  "shared.analysis.provider": "AI 服務商",
  "shared.analysis.none": "無",
  "shared.analysis.budget": "傳送給 AI 的影格",
  "shared.analysis.frames": "擷取的影格",
  "shared.analysis.after": "分析後",
  "shared.analysis.deleteVideo": "分析後刪除已下載的影片",
  "shared.analysis.deleteAudio": "分析後刪除已擷取的音訊",
  "shared.analysis.disclosure": "啟用轉錄時，擷取的音訊會傳送至 OpenAI。AI 報告會將文字與選定影格傳送至 Anthropic（claude）、OpenAI，或已設定的 FreeLLMAPI 伺服器及其上游服務商。服務商另行收費；接收方的條款與保留規定適用。選擇「無」只會停用 AI 報告。",
  "shared.analysis.keepShow": "保留並顯示在項目畫布中",
  "shared.analysis.keepDisk": "僅保留在磁碟上（不顯示在畫布中）",
  "shared.analysis.deleteFrames": "分析後刪除影格",
  "shared.analysis.auto": "自動（依長度調整）",
  "shared.analysis.off": "關閉（僅逐字稿）",
  "shared.analysis.upTo": "最多 {n} 個",
  "shared.native.google.replaced": "已由較新的登入取代。",

  "shared.native.backup.pc-managed": "請在電腦上管理電腦備份。此處只能變更獨立手機備份。",
  "shared.native.backup.library-changed": "手機資料庫已變更。此工作無法繼續。",
  "shared.native.backup.account": "請連結此備份選定的 Google 帳戶，再重試。",
  "shared.native.backup.saved-task": "請先完成已儲存的備份工作。",
  "shared.native.backup.select-backup": "請先選擇獨立手機備份。",
  "shared.native.backup.task-changed": "選定的備份工作已變更。",
  "shared.native.backup.identity": "手機金鑰或 Google 登入已變更。請連結選定帳戶並重試。",
  "shared.native.backup.paused": "備份工作已暫停。準備好時可繼續。",
  "shared.native.backup.replacement-missing": "找不到已儲存的替代備份。舊備份已保留。請中斷備份連線，並保留此手機的本機內容。",
  "shared.native.backup.replacement-duplicate": "雲端硬碟中有重複的替代檔案。舊備份已保留。請中斷備份連線，並保留此手機的本機內容。",
  "shared.native.backup.replacement-verification": "替代備份驗證失敗。舊備份已保留。請重試或中斷備份連線。",
  "shared.native.backup.replacement-retained": "無法驗證替代備份。剩餘舊檔案已保留。請重試或中斷備份連線。",
  "shared.native.recovery.material": "請使用原始復原碼、配對連結或已匯出手機復原檔案的文字。",
  "shared.native.recovery.fingerprint": "手機復原金鑰與指紋不符。",
  "shared.native.recovery.unsupported": "不支援此復原檔案。",
  "shared.native.recovery.identity": "手機資料庫或 Google 帳戶已變更。請重新連線並重試復原。",
  "shared.native.recovery.name": "手機復原檔名與內容不符。",
  "shared.native.recovery.missing-setup": "Google 雲端硬碟中缺少此復原設定。請保留復原檔案，並連結原始帳戶。",
  "shared.native.recovery.setup-mismatch": "已儲存的復原檔案與雲端硬碟中的復原設定不符。",
  "shared.native.recovery.verification": "復原驗證失敗。請保留原始復原碼。",
  "shared.native.recovery.select-file": "請選擇此設定儲存的復原檔案。",
  "shared.native.recovery.other-backup": "此復原檔案屬於不同的手機備份。",
  "shared.native.recovery.prepare-first": "請先準備復原設定。",
  "shared.native.recovery.changed-while-saving": "儲存期間手機資料庫或復原設定已變更。請重新儲存復原檔案。",

  "shared.native.google.timeout": "Google 在 2 分鐘內未回應（視窗可能已關閉）。請重試。",
  "shared.native.google.renewal-timeout": "Google 在 20 秒內未回應登入續期。",
  "shared.native.secure.write": "無法安全儲存登入資料。離開此頁面前請重試。",
  "shared.native.network.timeout": "無法檢查網路。",
  "shared.native.recovery.kit-in-code": "這是復原檔案。請在解鎖方式中選擇檔案以開啟。",
  "shared.native.recovery.passphrase-mismatch": "復原密碼片語不相符。",
  "shared.native.recovery.file-limit": "復原檔案必須小於 32 KiB。",
  "shared.native.network.network": "無法檢查網路。",










  "shared.native.google.denied": "尚未連結 Google 雲端硬碟。",
  "shared.native.google.consent": "你必須先同意 Google 雲端硬碟的要求。",
  "shared.native.google.failed": "Google 登入失敗：{detail}",
  "shared.native.scanner.failed": "無法啟動掃描器：{detail}",
  "shared.native.google.detail": "Google 登入：{detail}",
  "shared.native.scanner.detail": "掃描器：{detail}",
  "shared.native.secure.detail": "安全儲存：{detail}",
  "shared.native.network.detail": "網路連線：{detail}",
  "shared.native.vault.detail": "儲存庫操作：{detail}",
  "shared.native.recovery.detail": "復原：{detail}",
  "shared.native.backup.detail": "備份：{detail}",
  "shared.native.openUri.detail": "開啟 Obsidian：{detail}",
} as const satisfies Localized<typeof English>


