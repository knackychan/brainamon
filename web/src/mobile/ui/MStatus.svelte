<script lang="ts">
  // One state on a phone screen (.m-status in mobile.css): a dot for its tone (done: all well, todo: nothing to do
  // here, next: needs you, busy: working), the sentence, an optional detail under it, then at most one key (the
  // children). look="hero" (projects/phone-settings, spec section 2.1; settings.css) is the top of Settings and Backup
  // & phones: the kicker line (the dot, `kicker` in mono capitals, a link with `href`, an (i) with `info`), the
  // sentence as the title, the detail, then the key.
  import type { Snippet } from 'svelte'
  import type { HTMLAttributes } from 'svelte/elements'
  import MInfo from './MInfo.svelte'
  // no ShellIcon here: tests/test_ui_blocks.py renders MStatus under plain Node, which cannot resolve tabicons.ts's
  // extensionless imports; the kicker's chevron is drawn by settings.css (.m-hero-chev)

  type Props = HTMLAttributes<HTMLDivElement> & {
    tone: 'done' | 'todo' | 'next' | 'busy'; text: string; detail?: string; look?: 'line' | 'hero'
    kicker?: string; href?: string; infoTitle?: string; info?: Snippet; children?: Snippet
  }
  let { tone, text, detail = '', look = 'line', kicker = '', href, infoTitle = '', info, class: cls, children, ...rest }: Props = $props()
</script>

{#if look === 'hero'}
  <div {...rest} class={['m-status', 'm-hero', cls]}>
    <div class="m-hero-k">
      {#if href}<a class="m-hero-kick" {href}><i class={['m-status-dot', tone]} aria-hidden="true"></i><span>{kicker}</span><i class="m-hero-chev" aria-hidden="true"></i></a>
      {:else}<span class="m-hero-kick"><i class={['m-status-dot', tone]} aria-hidden="true"></i><span>{kicker}</span></span>{/if}
      {#if info}<MInfo title={infoTitle || kicker}>{@render info()}</MInfo>{/if}
    </div>
    <p><b>{text}</b>{#if detail}<small>{detail}</small>{/if}</p>
    {#if children}<div class="m-hero-key">{@render children()}</div>{/if}
  </div>
{:else}
  <div {...rest} class={['m-status', cls]}><p><b><i class={['m-status-dot', tone]} aria-hidden="true"></i>{text}</b>{#if detail}<small>{detail}</small>{/if}</p>{@render children?.()}</div>
{/if}
