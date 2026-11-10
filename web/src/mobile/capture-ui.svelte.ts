// What Add's floating "Import & drafts" key shares with the Add screen (projects/phone-add-sheet, then
// projects/phone-add-confirm). The key is drawn in the bare sheet's corner (CaptureKey.svelte, placed by Mobile.svelte);
// the panel that drops from it belongs to Capture.svelte. Capture writes the number of other drafts here (the key's
// badge) and whether its panel is open (the key turns dark), and opens the panel when `tray` changes; the key only
// counts its taps.
export const capUi = $state({ drafts: 0, tray: 0, open: false })
