# R7 viewer maintenance

Open `../interactive/qa/r7-preview.html` for the self-contained offline viewer.
The displayed geometry, dimensions, original QA evidence and three final PNGs
were retained byte for byte during consolidation. No older revision directory is
required to view or reconstruct it.

## Exact reconstruction and validation

From the release directory, with Python 3.10 or newer:

```text
python -B tools/rebuild_r7_viewer.py
python -B tools/rebuild_r7_viewer.py --output NEW-FRAGMENT.html
python -B interactive/validate_portability.py
```

The default is read-only. `--output` creates a new file and refuses to overwrite
an existing one. It decodes both compressed geometry transports, checks every
triangle index, checks the nine dimension lengths and focus IDs, reconstructs
the HTML with the original newline convention, and verifies the standalone
preview embeds that exact fragment. `interactive/build_viewer.py` and
`interactive/rebuild_viewer.py` are aliases for this operation.

`reconstruct(interactive_directory)` remains the importable validation API;
it returns `(fragment_bytes, report)` and does not write files or import CAD.

## Native geometry and small reference inputs

Run `interactive/prepare_inputs.py` with a Python interpreter that can import
FreeCAD and Part, such as the Python supplied by FreeCAD. It checks the native
hash against the approved viewer and reads all 2,949 component shapes using
`shape.Placement = object.getGlobalPlacement()`. The assembly parent transform
must be included; raw child Shape coordinates omit its Z translation.

The same checker reads current R7 coax/tie BREPs and the small local references
listed in `interactive/PORTABLE-REFERENCES.json`. These include the speaker
detail/fastener/lead shapes, coax plug and provisional battery-harness route.
The full current PCB assembly is already inside the R7 FCStd. Old full native
models, old display meshes and the old external assembly STEP are unnecessary.
Inspection is read-only and does not certify clearances after a CAD change.

## Geometry changes require a new review

Exact reconstruction uses the **retained approved mesh transports**, not fresh
tessellation of edited CAD. It deliberately does not update an edited model's
viewer or relabel it as approved. The old exporters depended on deleted
iterations and have been retired. The pure reusable tessellation functions in
`interactive/mesh/tessellator.py` remain available for future development.

For a future CAD change, export globally placed native shapes and the current
reference inputs to a new candidate directory, regenerate overview and Boolean
focus sections, rerun the eighteen dimension endpoint-to-surface checks, and
revalidate the transport and browser interactions. Rebind the native, fragment
and standalone-preview hashes only after that geometry review. This retained
release does not supply an automated fresh-CAD-to-viewer generation pipeline.

## Optional browser reruns

Use Node.js with `playwright` or `playwright-core` installed, and a compatible
Chromium browser. There are no fixed user paths. Set these environment variables
when using a nondefault installation:

- `R7_PLAYWRIGHT_MODULE`: module name or absolute module directory.
- `R7_BROWSER_EXECUTABLE`: browser executable; otherwise Playwright's browser.
- `R7_QA_OUTPUT`: a **new, nonexistent** results directory for browser QA.
- `R7_VIEWS_OUTPUT`: a **new, nonexistent** directory for three new illustrations.
- `R7_BROWSER_REPORT`: optional path to the newly generated browser report.
- `R7_VIEWER_ROOT`: optional relocated interactive directory.

Then run:

```text
node interactive/qa/r7-viewer-qa.cjs
node interactive/qa/export-final-views.cjs
```

New output directories protect the original evidence and images. Browser QA
tests the exact wrapper and fragment hashes. Exported images need visual review;
their new report intentionally starts with `visual_review_pending: true`.

## Historical evidence

Original `SOURCE-INPUTS.json` and all original validation JSON files are unchanged
historical records of the approved release. Paths inside them describe the
earlier build location; normal reconstruction and native-input inspection do
not dereference those old paths. `CONSOLIDATION-BASELINE.json` protects the 23
retained evidence/visual files, and `PORTABLE-REFERENCES.json` supplies the current
relative reference paths. The native CAD and manufacturing files remain the
authority for fabrication; display cuts and exploded offsets are inspection aids.
