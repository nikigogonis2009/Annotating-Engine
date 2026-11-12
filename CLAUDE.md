# Annotating Engine: notes for Claude

Marks up a PDF like a student annotating a reading. Python (PyMuPDF) does everything on the page; the margin notes are
written in the user's handwriting by the Handwriting Engine (`nikigogonis2009/Handwriting-Engine`), called through
`tools/write-notes.js`. Read that repo's `CLAUDE.md` for what the handwriting can and cannot do.

| File | Job |
| --- | --- |
| `tools/annotate.py` | `inspect` (page sizes, text column, margins, the text line by line) and `apply` (a plan to an annotated PDF). |
| `tools/write-notes.js` | Writes each note as an SVG with the Handwriting Engine, trimmed to the ink, and reports its size in points. |
| `tests/` | `make-reading.py` (a sample page), `fake-handwriting.js` (fake samples from the engine's test pen), unit tests. |
| `skill/niko-annotating/SKILL.md` | The Claude skill that drives all this. Zip that folder to upload it. |
| `skill/niko-annotating/references/annotating-guide.md` | What good annotation is (AP Lang, AP Lit, poetry, college), as rules and a mark key. |

How `apply` works: find each quote (`find_quote`: compares letters and digits only, so case, punctuation, ligatures
and line-end hyphens do not matter; returns one rect per text line) -> pick each note's side and width from the margins
(`Margins`, `choose_side`) -> write all notes in one Node call (building the handwriting style takes ~7 s, so never one
call per note) -> per page, draw the marks first, then place the notes top to bottom so they can make way for brackets
and stars (`Margins.spot`), then draw leaders along the gap between text lines (`Hand.arrow`) so they never cross words.

Hand-drawn look: `Hand` adds a slow wander and a little tremor to every stroke, overshoots ends, draws circles a bit more
than once round. Highlighter goes under the text (`commit(overlay=False)`) except on scanned pages, where it would be
hidden by the picture, so there it is see-through on top.

Rules: never commit handwriting samples, passwords, or users' readings/annotated PDFs (`.gitignore` covers the usual
names). Every behaviour change gets a test in `tests/test_annotate.py`; look at a rendered page (`--png 110`) before
saying a layout change works.
