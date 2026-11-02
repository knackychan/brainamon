# Publishing source without private history

`scripts/export_public.py` reads individual approved blobs from a full committed
revision. It does not copy a working tree, Git metadata, refs or history. It never
pushes, creates tags/releases, changes visibility, builds or signs. A dirty source
checkout does not affect exported bytes. Commit prepared source before selecting
the release revision.

The current investigation manifest is a candidate, with no approved export.
The exporter refuses it. Do not populate approvals just to make a command pass.
Source ownership, privacy and isolated verification must be reviewed separately
from Windows and Android binary clearance.

## Repositories and records

Use an independent fresh clone of the public repository. Never clone the private
repository as the target, fetch private refs into it, use alternates, or create
the target as a worktree or inside the source checkout. The exporter verifies the
origin and push URL, object-store boundary and reachable commit histories. By
default the allowed origin is `https://github.com/knackychan/brainamon.git`.
`--public-url` selects another reviewed origin for a fork or synthetic test.

Keep manifests, receipts and command reports outside the public clone. They may
contain private input paths and revision IDs. No private receipt is written into
the public payload. Public release metadata should identify only the public
commit, version, tool versions and artifact hashes.

An executable manifest uses schema_version 1 with these fields:

- `source_revision`: full immutable commit ID.
- `entries`: the complete reviewed set of files for this export.
- `approved_export`: every destination in entries and explicit deletions, once.
- `gate_results`: `O1`, `S1`, `C1` and every row-specific gate must be `true`,
  backed by evidence in the private release review. The explicit `--verification`
  mode permits only C1 to remain pending while materializing the exact files to
  test; ownership, privacy and all other row gates still apply.
- `deletions`: explicit destinations owned by the previous receipt, never
  website paths. Omission from entries alone cannot delete a file.

Each entry has `public_destination`, `action`, `status: "approved"`, `gate_ids`,
`output_sha256`, and `output_mode` (`100644` or `100755`). Each `source_inputs`
record must name `path`, `revision`, Git `blob`, SHA-256 `sha256`, and Git `mode`.
All inputs must be regular committed blobs at source_revision. The planning
manifest's input records need these hashes added during preparation.

For a primary input, also supply `source_path`, `source_revision`, `source_blob`,
`source_sha256` and `source_mode`. No paths, hashes or approvals are inferred.
The supported actions are deliberately bounded:

| Action | Definition |
|---|---|
| `copy unchanged` | Exact primary blob; no transform. |
| `modify` | `transform.replacements`: ordered UTF-8 `{old, new, count}` patches. Every nonempty old string must occur exactly count times. |
| `extract` | `transform: {start, end}`: unique UTF-8 markers, in order; retain their inner bytes, strip outer whitespace and append LF. |
| `generate` | `transform.parts`: ordered `{text: "literal UTF-8"}` or `{input: "declared/path"}` records. source_path may be null; all consumed blobs must be declared. |

Unknown actions/transforms fail closed. Store reviewed transformations with the
private manifest/receipt. Regenerate and review expected output hashes after any
change. Paths reject traversal, Git metadata, credentials, private data, ambiguous
Windows names, case collisions, and nonregular input/output files. Only the four
runtime card assets are permitted under design. Website files under docs are
protected; new developer docs belong under docs/development.

## Preview and apply

For the first isolated test tree, add `--verification` to preview and apply.
Its output and private receipt say `purpose: verification`. This is not release
clearance: run the C1 checks, record their exact tree identity and results, then
review/update the gate evidence and repeat without this flag. A verification
receipt alone cannot satisfy the default C1 gate. The target is still an
independent public-only clone; all path/history/contribution checks still apply.

Run from the source checkout, with placeholders replaced by explicit paths:

```powershell
py scripts/export_public.py --source C:\work\source --target C:\work\public --manifest C:\release-review\manifest.json
```

This is a read-only preview reporting paths, operations, modes and final hashes.
It refuses unapproved rows, hash drift, an unrelated dirty target, website
destinations and collisions with existing public files. For the first README
merge only, the reviewed row must contain `public_base_sha256` matching the current
public README, and its prepared output must intentionally preserve public content.

After reviewing the preview, add `--apply --receipt-output` with a private receipt
path. On subsequent runs also pass `--previous-receipt`:

```powershell
py scripts/export_public.py --source C:\work\source --target C:\work\public --manifest C:\release-review\manifest.json --previous-receipt C:\release-review\previous.json --apply --receipt-output C:\release-review\next.json
```

The tool writes only approved files. It records executable flags in the public
Git index where needed, so gradlew remains executable when exported on Windows.
It does not commit. A repeat using the new receipt must report no changes, before
and after committing the public result. Review `git diff` and `git diff --cached`.
An interrupted filesystem write requires reviewing partial output before retry;
there is no multi-file transaction or automatic rollback.

## Preserve contributions on every release

### Routine updates from a Content Manager worktree

Content Manager remains the development source of truth. Use a separate,
durable public-only clone for the outward mirror. A public clone must never be
a private Git worktree. Synchronize selected commits after review and checks;
unfinished local edits remain local. Avoid folder-sync programs and Git hooks
that push every save or commit: a newly added credential, fixture or private
document must not become public through a directory glob.

`scripts/prepare_public_update.py` turns the last reviewed manifest into a new
**private candidate**. It refreshes blob IDs, modes and hashes for existing mapped
files at an explicit full commit ID. It reports changed public destinations and
changed source paths outside the mapping. Unmapped paths stay excluded. Previous
approvals and gates are cleared; it cannot export, commit, tag or push. It refuses
deleted/nonregular inputs and changed transformations until their mapping/output
has been reviewed manually. Unchanged transformations retain their exact output.

Run it from the intended development worktree, after committing the changes:

```powershell
$sourceRevision = git rev-parse HEAD
py scripts/prepare_public_update.py --source . --manifest C:\release-review\last-manifest.json --revision $sourceRevision --output build/source-update-review/next-manifest.json
```

Replace the manifest with the last reviewed one on subsequent updates. Use a new
private output filename each time; the command refuses to overwrite a record.
Outputs must stay inside the private source checkout. The candidate includes
private path/revision information and must never be copied into the public clone.

Review both lists. Keep private plans/data/tooling excluded; explicitly add any
new runtime modules, assets and tests with their hashes and mapping. Handle
renames/deletions explicitly, using the existing deletion rules. Fetch the public
clone and integrate contributions as described below. Review ownership/privacy,
scan the delta and validate the exact candidate in isolation before recording new
approvals. Then use the existing export preview/apply commands with the previous
receipt. Review the public diff, commit it, and confirm a repeat export is empty.

Public source main may advance between application releases. Release tags remain
immutable snapshots. Give each new release a fresh tag and build any future
binaries from that exact public source commit. If an application version tag is
already occupied by a historical binary/website commit, use a distinct source tag
such as `source-v1.1.0`; never move the occupied tag or imply an unverified binary
match. Source-only releases stay prereleases with make-latest false so the stable
Windows updater continues selecting a release with official installer assets.

### Integrate accepted public changes

Fetch public changes only into the independent public clone. Compare its HEAD
and owned file hashes against the previous receipt. Import reviewed public
file-level patches into the corresponding source paths, with contributor
attribution, and commit them before regenerating the manifest. Use the last
receipt, current public files and new transformed source for the comparison.

An owned public file changed since the receipt is accepted only when the newly
prepared source produces those same reviewed bytes. Public-only changes and
same-file conflicts otherwise stop the export for integration; they are never
silently overwritten. Keep public-only files outside export ownership, including
website changes. Map extracted or relocated files explicitly to their canonical
editable inputs. Never reconstruct editable artwork from generated PNGs.

Receipts retain deletion tombstones to make explicit deletion repeatable. Only
previously owned paths may be deleted; edited files require integration first.
Changing export ownership or adding a destination requires a new manifest review.

Before publication, verify isolated source builds and each intended binary's
notices, corresponding source and device checks. Build future official artifacts
from their exact clean public source commit. Record artifact hashes and refresh
the website/tag/release preservation comparison. Do not claim historical binaries
match newly published source. Publication is a separate authorized action after
the concrete commit and artifacts are reviewable.
