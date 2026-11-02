<script lang="ts">
  // A workspace that a later sub-plan builds (02 Knowledge: plan 08, 03 Canvas: plan 09,
  // 04 Notes: plan 10). Each plan replaces its <SoonWs> line in App.svelte with its workspace.
  import { ui, WS_NAME, type Ws } from '../lib/ui.svelte'
  let { ws, cls, code, plan }: { ws: Ws; cls: string; code: string; plan: string } = $props()
</script>

<!-- the V6 markup: main.ws as the workspace tab panel -->
<!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
<main class={'ws ' + cls} id={'ws-' + ws} role="tabpanel" aria-labelledby={'tab-' + ws} data-ws={ws} hidden={ui.ws !== ws}>
  <section class="rwin" aria-labelledby={'soon-' + ws}>
    <div class="wbar"><span class="wdots" aria-hidden="true"><i></i><i></i></span><p class="wtitle" id={'soon-' + ws}>{WS_NAME[ws]}</p><span class="wcode">{code}</span></div>
    <div class="rwin-body"><p class="soon-note">{WS_NAME[ws]} arrives in V6 with plan {plan}. Use the Qt app for it until then.</p></div>
  </section>
</main>
