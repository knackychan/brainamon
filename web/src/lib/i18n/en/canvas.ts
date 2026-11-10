export const messages = {
  "canvas.list": "Canvases",
  "canvas.waitingBackup": "Canvas waiting for earlier backup",
  "canvas.new": "New canvas",
  "canvas.empty": "No canvases yet. Ask Wiskit to make one.",
  "canvas.elements": {"one":"{n} elements","other":"{n} elements"},
  "canvas.saved": "Saved",
  "canvas.phone": "Phone",
  "canvas.offlineSaved": "✓ Saved",
  "canvas.offline": "Save for offline",
  "canvas.composer.shared": "Shared to Add. Your picks are still here.",
  "canvas.composer.name": "Canvas name",
  "canvas.composer.namePlaceholder": "Name this canvas",
  "canvas.composer.layout": "Layout",
  "canvas.composer.rows": "Rows",
  "canvas.composer.columns": "Columns",
  "canvas.composer.addTo": "Add to it",
  "canvas.composer.discardTitle": "Discard these picks?",
  "canvas.composer.uncertainLeave": "The PC may have saved this addition. Leaving discards only these picks.",
  "canvas.composer.notAdded": {"one":"{n} not added yet.","other":"{n} not added yet."},
  "canvas.composer.keep": "Keep editing",
  "canvas.composer.discard": "Discard",
  "canvas.composer.picks": "Canvas picks",
  "canvas.composer.resize": "Resize drawer",
  "canvas.composer.controls": "Pick controls",
  "canvas.composer.search": "Search the library",
  "canvas.composer.clearSearch": "Clear search",
  "canvas.composer.smart": "Smart",
  "canvas.composer.write": "Write a note",
  "canvas.composer.adding": "Adding…",
  "canvas.composer.colour": "Note colour",
  "canvas.composer.colourNumber": "Colour {n}",
  "canvas.composer.collections": "Collections",
  "canvas.composer.favs": "Favs",
  "canvas.composer.item": "Item {id}",
  "canvas.composer.used": ", already on this canvas",
  "canvas.composer.loading": "Loading the library…",
  "canvas.composer.none": "Nothing matches",
  "canvas.composer.clear": "Clear",
  "canvas.preview": "Canvas preview, drag to move, pinch to zoom",
  "canvas.board": "Canvas {name}, drag to move, pinch to zoom",
  "canvas.pickBelow": "Pick images below",
  "canvas.pickedImage": "Picked image",
  "canvas.notHere": "Not on this phone yet",
  "canvas.image": "image",
  "canvas.imageUnavailable": "Image unavailable",
  "canvas.namedUnavailable": "{label}: image unavailable",
  "canvas.remove": "✕ Remove",
  "canvas.fitBoard": "Fit the board",
  "canvas.fit": "Fit",
  "canvas.fitKey": "FIT",
  "canvas.zoomIn": "Zoom in",
  "canvas.zoomOut": "Zoom out",
  "canvas.proposal.label": "Wiskit canvas proposal",
  "canvas.proposal.add": "Add to canvas",
  "canvas.proposal.helpTitle": "Applying canvas changes",
  "canvas.proposal.help": "Existing elements stay. Only the listed elements move when rearranging is requested. Nothing changes until you tap Apply.",
  "canvas.proposal.newBoard": "New board",
  "canvas.proposal.existing": {"one":"{n} elements already here","other":"{n} elements already here"},
  "canvas.proposal.summary": "{layout} layout · {thumbs} thumbnails · {frames} frames · {notes} text notes · {moves} moved",
  "canvas.proposal.ungrouped": "Ungrouped",
  "canvas.proposal.move": "Move existing",
  "canvas.proposal.text": "Text note",
  "canvas.proposal.frame": "Frame",
  "canvas.proposal.thumbnail": "Thumbnail",
  "canvas.proposal.placed": "Placed positions",
  "canvas.proposal.existingKind": "existing",
  "canvas.proposal.frameKind": "frame",
  "canvas.proposal.textKind": "text",
  "canvas.proposal.thumbnailKind": "thumbnail",
  "canvas.proposal.decline": "Decline",
  "canvas.proposal.applying": "Applying…",
  "canvas.proposal.apply": "Apply",
  "canvas.composer.unavailable": {
    "one": "{n} picked image is not on this phone yet",
    "other": "{n} picked images are not on this phone yet"
  },
  "canvas.error.detail": "{detail}",
  "canvas.composer.changed": "Canvas changed. Check the board and tap Add again.",
  "canvas.composer.limit": "60 is the most for one go. Add these, then add more.",
  "canvas.composer.uncertain": "Could not confirm Add. Tap Add to check the same addition.",
  "canvas.composer.invalid": "Remove invalid characters from the name or note.",
  "canvas.composer.longName": "Use at most 80 characters for the canvas name.",
  "canvas.composer.longNote": "Use at most 1000 characters for the note.",
  "canvas.composer.nameFirst": "Name your canvas first.",
  "canvas.composer.exists": "\"{name}\" already exists.",
  "canvas.composer.added": "Added {n} to {name}.",
  "canvas.composer.created": "{name} created with {n}.",
  "canvas.composer.duplicates": {
    "one": "{n} pick is already on this canvas.",
    "other": "{n} picks are already on this canvas."
  },
  "canvas.status.missing": "Earlier canvas creation is missing. Refresh after the backup arrives.",
  "canvas.status.synced": "Synced",
  "canvas.status.phone": "On this phone",
  "canvas.status.waiting": "Waiting to sync",
  "canvas.status.update": "Saved on this phone. Update the PC to sync canvases.",
  "canvas.status.refused": "Not synced: {reason} {kept}",
  "canvas.status.refusedCreation": "Not synced: {reason}",
  "canvas.status.creationReason": "The PC refused this creation.",
  "canvas.status.changeReason": "The PC refused this change.",
  "canvas.status.pcCopy": "The PC changed this canvas since, so its copy is shown.",
  "canvas.status.kept": "Your phone copy is kept."
} as const

export const budgets = {
  "canvas.waitingBackup": { "limit": 40, "params": {} },
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

