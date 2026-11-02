<script lang="ts">
  // tests/test_ui_blocks.py renders this on the server and compares it with expected.html
  import Button from '../../../web/src/components/ui/Button.svelte'
  import Field from '../../../web/src/components/ui/Field.svelte'
  import Hint from '../../../web/src/components/ui/Hint.svelte'
  import Label from '../../../web/src/components/ui/Label.svelte'
  import Progress from '../../../web/src/components/ui/Progress.svelte'
  import SectionTitle from '../../../web/src/components/ui/SectionTitle.svelte'
  import Status from '../../../web/src/components/ui/Status.svelte'
  import WinBody from '../../../web/src/components/ui/WinBody.svelte'
  import WinFoot from '../../../web/src/components/ui/WinFoot.svelte'
  import Disclosure from '../../../web/src/components/ui/Disclosure.svelte'
  import MBox from '../../../web/src/mobile/ui/MBox.svelte'
  import MButton from '../../../web/src/mobile/ui/MButton.svelte'
  import MHint from '../../../web/src/mobile/ui/MHint.svelte'
  import MRow from '../../../web/src/mobile/ui/MRow.svelte'
  import MToggle from '../../../web/src/mobile/ui/MToggle.svelte'
  import MSeg from '../../../web/src/mobile/ui/MSeg.svelte'
  import MDisclosure from '../../../web/src/mobile/ui/MDisclosure.svelte'
  import MTextButton from '../../../web/src/mobile/ui/MTextButton.svelte'
  import MStatus from '../../../web/src/mobile/ui/MStatus.svelte'
</script>

<div id="desktop">
  <Button>Close</Button>
  <Button variant="pri" size="sm" disabled>Save</Button>
  <Button variant="danger" type="submit" class="x">Delete</Button>
  <Button kind="tool" wide class={{ on: true, off: false }} aria-label="Tool">T</Button>
  <WinBody class="set-body" id="b"><Hint>Help line</Hint><Hint as="small" tone="error">Bad</Hint><Hint as="ol" class="steps"><li>One</li></Hint></WinBody>
  <WinFoot>{#snippet start()}<small>Note</small>{/snippet}<Button>Close</Button></WinFoot>
  <WinFoot class="wide"><Button variant="pri">OK</Button></WinFoot>
  <div class="fg"><Field label="Name" for="n"><input id="n" class="inp" /></Field><Field as="span">{#snippet label()}Mode <b>x</b>{/snippet}<div class="frow"></div></Field></div>
  <Label for="z">Alone</Label><Label as="span" class="wide">Group</Label>
  <SectionTitle class="set-section">Search</SectionTitle><SectionTitle as="p">Plain</SectionTitle>
  <Status on /><Status>Missing</Status><Status on as="span" role="status">Ready</Status>
  <Progress label="Checking" /><Progress label="Copying" pct={50} /><Hint as="pre" class="set-cmd">winget</Hint><Disclosure summary="More"><Hint>Body</Hint></Disclosure>
</div>
<div id="phone">
  <MButton>Go</MButton><MButton variant="pri" size="sm" type="submit">Send</MButton><MButton as="a" href="/x" variant="dk">Open</MButton>
  <MBox as="section" id="m"><MRow title="Wi-Fi only" desc="Uses data"><MButton size="sm">Change</MButton></MRow><MRow title={3} /></MBox>
  <MRow title="T">{#snippet desc()}With <a href="/h">link</a>{/snippet}</MRow>
  <MBox><MHint>Hint</MHint><MHint as="p" tone="error" class="m-pad-x">Err</MHint></MBox>
  <MStatus tone="done" text="In sync." detail="Changes from this phone: All sent."><MButton size="sm">Send now</MButton></MStatus><MStatus tone="next" text="Connect Google Drive." id="s" class="x" />
  <MToggle label="Wi-Fi only" on={true} /><MToggle label="Keep" on={false} disabled /><MSeg label="Keep videos" options={[['off', 'Off'], ['all', 'All']]} value="all" size="sm" /><MDisclosure summary="More" id="m-pair"><MHint>Body</MHint></MDisclosure><MTextButton>Hide</MTextButton><MTextButton tone="danger" class="x">Remove</MTextButton>
</div>
