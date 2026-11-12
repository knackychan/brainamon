export interface ModelChoice { provider: string; model: string }
export interface ModelView {
  jarvis: ModelChoice; saved: boolean; found_at?: Record<string, string>
  providers: { id: string; label: string; has_key: boolean }[]
  models: Record<string, { id: string; label: string }[]>
  embed_provider: string; embed_providers: { id: string; label: string }[]
}
export interface ToolsView { tools_dir: string; tool_folders?: Record<string, string>; tools: { name: string; found: boolean; path: string; version?: string; state?: string }[]; all_found: boolean; youtube?: { deno: boolean; ejs: string; functional: boolean } }
export interface InstallView { state: 'idle' | 'running' | 'done' | 'error'; step: string; error: string; command: string; winget: boolean }
export interface BrowserRuntime { path?: string; source?: string; managed?: boolean; environment?: string; python_path?: string; state: string; version?: string; step: string; error: string; supported: boolean; workers: boolean; python: boolean; winget: boolean }
export interface SetupView {
  phone_seen?: boolean
  frozen: boolean; data_dir: string; data_dir_next?: string; next_items?: number; next_notes?: number; can_quit?: boolean; has_key: boolean; items: number; dismissed: boolean; cookies: boolean
  keys: Record<string, boolean>; models: ModelView
  tools: Record<string, boolean>; tool_status: ToolsView; tool_install: InstallView
  obsidian: { installed: boolean; vault: string; set: boolean; mode: 'owner' | ''; vault_ok: boolean; is_vault: boolean }
  cloud: { configured: boolean; signed_in: boolean; on: boolean }
}
