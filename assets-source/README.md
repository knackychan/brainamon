# Editable application artwork and styles

These inputs replace the generators' dependency on private design documents.
The application author confirmed creating these materials on 2026-11-02 for the
planned GPL-3.0-only edition. The LICENSE at the revision you use governs it;
third-party notices and final release verification remain separate.

- Edit Wiskit's drawing logic in `wiskit/drawing.js`, then run
  `node web/scripts/export_wiskit.mjs` and `py -m desktop.wiskit_sprite`.
  `node web/scripts/export_wiskit.mjs --check` checks the generated Python art.
- Edit the two files under `styles/`, then run `npm --prefix web run css`.
  `py web/scripts/extract_v6_css.py --check` verifies generated CSS.
- The preferred logo geometry is embedded in `scripts/build_brand.py`. Run it on
  Windows with Pillow, test-only Playwright and Microsoft Edge installed. It
  generates web, Windows and Android icons and all eleven splash sizes from
  scratch; no existing image or private design kit is needed as an input.

Rebuild web/dist and sync the Android web assets after changing generated files.
Do not edit generated files as substitutes for these editable inputs. The four
runtime card CSS/JS files remain editable at their existing design/card-designs
paths; specimen images and design pages are not needed by the runtime.
