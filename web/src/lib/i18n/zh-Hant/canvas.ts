export const messages = {
  "canvas.waitingBackup": "畫布等待較早的備份",
  "canvas.list": "畫布",
  "canvas.new": "新增畫布",
  "canvas.empty": "尚無畫布。請 Wiskit 幫你建立。",
  "canvas.elements": {"other":"{n} 個元素"},
  "canvas.saved": "已儲存",
  "canvas.phone": "手機",
  "canvas.offlineSaved": "✓ 已儲存",
  "canvas.offline": "儲存供離線使用",
  "canvas.composer.shared": "已分享到「新增」。你選取的項目仍保留在這裡。",
  "canvas.composer.name": "畫布名稱",
  "canvas.composer.namePlaceholder": "為畫布命名",
  "canvas.composer.layout": "排列",
  "canvas.composer.rows": "橫列",
  "canvas.composer.columns": "直欄",
  "canvas.composer.addTo": "加入這個畫布",
  "canvas.composer.discardTitle": "要捨棄這些選取項目嗎？",
  "canvas.composer.uncertainLeave": "電腦可能已儲存這次新增內容。離開只會捨棄這些選取項目。",
  "canvas.composer.notAdded": {"other":"還有 {n} 個尚未加入。"},
  "canvas.composer.keep": "繼續編輯",
  "canvas.composer.discard": "捨棄",
  "canvas.composer.picks": "畫布選取項目",
  "canvas.composer.resize": "調整面板大小",
  "canvas.composer.controls": "選取控制項",
  "canvas.composer.search": "搜尋資料庫",
  "canvas.composer.clearSearch": "清除搜尋",
  "canvas.composer.smart": "語意",
  "canvas.composer.write": "撰寫筆記",
  "canvas.composer.adding": "加入中…",
  "canvas.composer.colour": "筆記顏色",
  "canvas.composer.colourNumber": "顏色 {n}",
  "canvas.composer.collections": "收藏分類",
  "canvas.composer.favs": "最愛",
  "canvas.composer.item": "項目 {id}",
  "canvas.composer.used": "，已在這個畫布上",
  "canvas.composer.loading": "正在載入資料庫…",
  "canvas.composer.none": "沒有符合的結果",
  "canvas.composer.clear": "清除",
  "canvas.preview": "畫布預覽，拖曳移動，雙指縮放",
  "canvas.board": "畫布 {name}，拖曳移動，雙指縮放",
  "canvas.pickBelow": "在下方選取圖片",
  "canvas.pickedImage": "已選取的圖片",
  "canvas.notHere": "尚未下載到這支手機",
  "canvas.image": "圖片",
  "canvas.imageUnavailable": "圖片無法使用",
  "canvas.namedUnavailable": "{label}：圖片無法使用",
  "canvas.remove": "✕ 移除",
  "canvas.fitBoard": "縮放至畫布範圍",
  "canvas.fit": "符合範圍",
  "canvas.fitKey": "全覽",
  "canvas.zoomIn": "放大",
  "canvas.zoomOut": "縮小",
  "canvas.proposal.label": "Wiskit 畫布提案",
  "canvas.proposal.add": "加入畫布",
  "canvas.proposal.helpTitle": "套用畫布變更",
  "canvas.proposal.help": "現有元素會保留。要求重新排列時，只會移動列出的元素。點「套用」後才會變更。",
  "canvas.proposal.newBoard": "新畫布",
  "canvas.proposal.existing": {"other":"已有 {n} 個元素"},
  "canvas.proposal.summary": "{layout}排列・{thumbs} 個縮圖・{frames} 個影格・{notes} 則文字筆記・移動 {moves} 個",
  "canvas.proposal.ungrouped": "未分組",
  "canvas.proposal.move": "移動現有元素",
  "canvas.proposal.text": "文字筆記",
  "canvas.proposal.frame": "影格",
  "canvas.proposal.thumbnail": "縮圖",
  "canvas.proposal.placed": "指定位置",
  "canvas.proposal.existingKind": "現有元素",
  "canvas.proposal.frameKind": "影格",
  "canvas.proposal.textKind": "文字",
  "canvas.proposal.thumbnailKind": "縮圖",
  "canvas.proposal.decline": "拒絕",
  "canvas.proposal.applying": "套用中…",
  "canvas.proposal.apply": "套用",
  "canvas.composer.unavailable": {
    "other": "選取的圖片中有 {n} 張尚未下載到這支手機"
  },
  "canvas.error.detail": "畫布錯誤：{detail}",
  "canvas.composer.changed": "畫布已變更。請檢查畫布後再點「新增」。",
  "canvas.composer.limit": "一次最多 60 個。請先加入這些項目，再繼續新增。",
  "canvas.composer.uncertain": "無法確認新增結果。請點「新增」檢查同一次新增。",
  "canvas.composer.invalid": "請移除名稱或筆記中的無效字元。",
  "canvas.composer.longName": "畫布名稱最多 80 個字元。",
  "canvas.composer.longNote": "筆記最多 1000 個字元。",
  "canvas.composer.nameFirst": "請先為畫布命名。",
  "canvas.composer.exists": "「{name}」已存在。",
  "canvas.composer.added": "已加入 {n} 個至 {name}。",
  "canvas.composer.created": "已建立 {name}，含 {n} 個。",
  "canvas.composer.duplicates": {
    "other": "有 {n} 個選取項目已在這個畫布上。"
  },
  "canvas.status.missing": "找不到先前建立的畫布。請在備份送達後重新整理。",
  "canvas.status.synced": "已同步",
  "canvas.status.phone": "在這支手機上",
  "canvas.status.waiting": "等待同步",
  "canvas.status.update": "已儲存在這支手機。請更新電腦以同步畫布。",
  "canvas.status.refused": "尚未同步：{reason} {kept}",
  "canvas.status.refusedCreation": "尚未同步：{reason}",
  "canvas.status.creationReason": "電腦拒絕了這次建立作業。",
  "canvas.status.changeReason": "電腦拒絕了這次變更。",
  "canvas.status.pcCopy": "電腦稍後已變更這個畫布，因此顯示電腦上的副本。",
  "canvas.status.kept": "已保留手機上的副本。"
} as const

export const budgets = {
  "canvas.offline": {
    "limit": 22,
    "params": {}
  },
  "canvas.composer.rows": {
    "limit": 10,
    "params": {}
  },
  "canvas.composer.columns": {
    "limit": 12,
    "params": {}
  },
  "canvas.composer.keep": {
    "limit": 14,
    "params": {}
  },
  "canvas.composer.discard": {
    "limit": 12,
    "params": {}
  },
  "canvas.fitKey": {
    "limit": 5,
    "params": {}
  },
  "canvas.proposal.apply": {
    "limit": 14,
    "params": {}
  },
  "canvas.proposal.decline": {
    "limit": 14,
    "params": {}
  }
} as const


