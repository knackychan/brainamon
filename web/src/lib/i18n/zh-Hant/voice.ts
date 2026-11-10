import type { messages as English } from '../en/voice.ts'
import type { Localized } from '../en/index.ts'

export const messages = {
  'voice.unsaved': '無法儲存一段錄音。請重試或捨棄這段錄音。',
  'voice.retrySave': '重試儲存錄音',
  'voice.discard': '捨棄錄音',
  "voice.record.unsupported": "這個瀏覽器無法錄音。請使用 Brainamon 應用程式。",
  "voice.record.denied": "未允許使用麥克風。請在手機設定中授權 Brainamon。",
  "voice.record.startFailed": "無法開始錄音：{message}",
  "voice.record.tooLong": "單次錄音過長，請分段錄製。",
  "voice.queue.waiting": "已儲存到這支手機。連線後會轉為文字。",
  "voice.record.noSpeech": "未偵測到語音。",
  "voice.queue.notSaved": "無法轉錄：{message} 無法將錄音儲存到這支手機。",
  "voice.queue.kept": "無法轉錄：{message} 錄音已保留在這支手機。",
  "voice.record.discarded": "已捨棄錄音。",
  "voice.record.clock": "錄音中 {clock}",
  "voice.record.level": "麥克風音量",
  "voice.record.stop": "停止並轉錄",
  "voice.record.discard": "捨棄",
  "voice.record.busy": "正在轉錄音訊…",
  "voice.record.transcribing": "轉錄中",
  "voice.record.start": "錄音",
  "voice.record.file": "音訊檔案",
  "voice.record.info": "音訊轉錄",
  "voice.record.upload": "錄音或選擇音訊檔案後，會上傳到 OpenAI 進行轉錄；直接連線電腦模式則透過電腦上傳。",
  "voice.record.retention": "服務商費用另計，並適用其條款與保留政策。離線錄音可先保留在這裡，連線後再上傳。",
  "voice.record.keyNeeded": "語音筆記需要這支手機上的 OpenAI 金鑰（設定 > 這支手機上的 Wiskit）。",
  "voice.queue.offline": "沒有網路：錄音會在這支手機上等待。",
} as const satisfies Localized<typeof English>


