// Restart Brainamon (POST /api/app/restart): a new launch waits for this one to close, so a library
// folder chosen for the next start loads without a manual quit and reopen.
import { api } from './api'
import { toast } from './ui.svelte'

export async function restartApp(): Promise<void> {
  await api.post('/api/app/restart')
  toast('Brainamon is restarting…')
  window.pywebview?.api?.close?.()
}
