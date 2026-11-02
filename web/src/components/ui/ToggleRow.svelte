<script lang="ts">
  // A switch and its words on one line (.tgl, app.css): the label is the accessible name, the optional dim
  // note after it joins aria-describedby. Several stack inside one GroupBox cell. Inside .set-win the input
  // draws as the Settings switch; elsewhere it is the native checkbox. `checked` can be bound, or read
  // through onchange(on) after the switch moves. `info` adds an (i) after the words with the switch's explanation.
  import InfoTip from './InfoTip.svelte'
  const uid = $props.id()
  let { label, note = '', info, checked = $bindable(false), disabled = false, id = uid, describedby = '', onchange }: {
    label: string; note?: string; info?: string | string[]; checked?: boolean; disabled?: boolean; id?: string; describedby?: string; onchange?: (on: boolean) => void
  } = $props()
  const noteId = $derived(note ? `${id}-note` : '')
  const described = $derived([describedby, noteId].filter(Boolean).join(' ') || undefined)
</script>

<label class="tgl" for={id}>
  <input {id} type="checkbox" role="switch" {checked} {disabled} aria-label={info ? label : undefined} aria-describedby={described} onchange={e => { checked = e.currentTarget.checked; onchange?.(checked) }} />
  <span>{label}{#if note}{' '}<small id={noteId}>· {note}</small>{/if}{#if info}<InfoTip label={`What ${label} does`} text={info} />{/if}</span>
</label>
