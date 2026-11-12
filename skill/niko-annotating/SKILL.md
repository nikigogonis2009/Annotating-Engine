---
name: niko-annotating
description: Annotate a reading, article, textbook page or worksheet PDF the way Niko would with a pen, with hand-drawn highlights, underlines, circles, brackets and stars, and margin notes in his own handwriting, using his Annotating Engine and Handwriting Engine repos. Use whenever Niko asks to annotate, mark up, highlight, close-read or "add notes in the margins" of a PDF, even if he doesn't say "handwriting".
---

# Annotating a PDF in Niko's handwriting

Two of Niko's public repos do this together:

- `nikigogonis2009/Annotating-Engine` finds the text to mark, draws hand-drawn marks and lays out the margin notes.
- `nikigogonis2009/Handwriting-Engine` writes the notes in his handwriting, from a password-locked copy of it.

## 1. Get the engines

    git clone --depth 1 https://github.com/nikigogonis2009/Annotating-Engine annot
    git clone --depth 1 https://github.com/nikigogonis2009/Handwriting-Engine hw-engine
    pip install pymupdf

If a clone is refused, attach the repo with the add_repo tool (owner `nikigogonis2009`) and clone again. Node 18+ is
needed (`node --version`). Read `annot/README.md` once for the plan format.

## 2. Unlock the handwriting

Exactly as in the handwriting skill: ask Niko for the password, then unlock ONCE into the scratchpad (never the repo):

    HANDWRITING_PASSWORD='<password>' node -e "const fs=require('fs');const {unseal}=require('./hw-engine/mcp/sealed');fs.writeFileSync(process.argv[1], unseal(fs.readFileSync('hw-engine/handwriting.enc.json'), process.env.HANDWRITING_PASSWORD), {mode:0o600})" "$SCRATCH/my-handwriting.json"

(`$SCRATCH` = the scratchpad directory.) Put the password only in that one environment variable. Never write it to a
file, memory, a commit, a message, an artifact or a scheduled task, and never echo it. If unlocking fails, the password
was wrong: say so and ask again. You can do steps 3 to 5 with `--font` while waiting for it.

## 3. Read the document

    python3 annot/tools/annotate.py inspect reading.pdf --text

This prints each page's margins and its text line by line. Also render the pages (`pdftoppm -r 72 -png reading.pdf pg`)
and LOOK at them. If a page says `NO TEXT LAYER`, it is a scan: OCR it first (`ocrmypdf`), or tell Niko.

## 4. Decide the annotations

Either Niko says what to mark, or he asks you to annotate for something (themes, characters, literary devices, key
terms, evidence for an essay question, things to ask in class). If the focus is unclear, ask in one line before
starting. Then annotate like a good student, not a robot:

- Few and meaningful: about 2 to 5 marks per page, not every sentence. Quote short phrases; highlight a whole sentence
  only when the whole sentence matters.
- Notes are short (1 to 6 words: "foreshadowing", "why lie here?", "theme: sacrifice") because margins are narrow.
  Longer thoughts go in a page note: `{"page": 1, "at": "top", "note": "..."}` or `"bottom"`.
- Keep a consistent key and tell Niko what it is, e.g. yellow = key idea, green = imagery, circle = word to look up,
  bracket = important passage, star = big moment, `?` note = confusing.
- Quote the text exactly as it reads on the page (case, punctuation and line breaks do not matter). If a phrase occurs
  more than once, add `"occurrence": n` or `"page": n`.

Write the plan (`$SCRATCH/plan.json`); paths in it are relative to the plan file, so give `pdf` and `out` as absolute paths:

    {"pdf": "/abs/reading.pdf", "out": "/abs/out/reading-annotated.pdf", "annotations": [
      {"quote": "One dollar and eighty-seven cents", "mark": "highlight", "note": "money is the problem"},
      {"quote": "imputation of parsimony", "mark": "circle", "note": "stingy?"},
      {"quote": "life is made up of sobs, sniffles, and smiles", "mark": "bracket", "note": "narrator voice"},
      {"quote": "Tomorrow would be Christmas Day", "mark": "star"}]}

Marks: `highlight` (colours: yellow, green, blue, pink, orange, purple or #rrggbb), `underline`, `squiggle`, `strike`,
`circle`, `box`, `bracket`, `double-bracket`, `star`, `check`, `none`. Math notes: `"kind": "math"` with TeX-style input.

## 5. Preview, then write it for real

    python3 annot/tools/annotate.py apply "$SCRATCH/plan.json" --font --png 100

The `--font` preview takes a second and needs no handwriting. Look at the pictures and fix the plan: quotes it could not
find, notes it moved or could not fit (if margins are narrow, add `"extend_margin": 150` to the plan to widen the pages
on the right), crowded areas. Then:

    python3 annot/tools/annotate.py apply "$SCRATCH/plan.json" --engine hw-engine --samples "$SCRATCH/my-handwriting.json" --png 110

and read its report (missing characters especially).

## 6. Check, deliver, clean up

- Look at every annotated page picture before handing it over. If a note is hard to read, give it another `seed` or a
  higher `neatness` (0..1) in the plan and run again. If a character is missing or bad, tell Niko which ones need better
  samples in the Handwriting Engine app.
- Send the finished PDF with SendUserFile, and say in a line what the colour/mark key is.
- Delete `$SCRATCH/my-handwriting.json` and any `.handwriting-cache` folder when the task is done.

Annotate only what Niko asked for. Do not put his name or other personal details on the page unless he gives them.
Whether annotations made this way may be handed in is his decision under his school's rules; if he asks you to write
the analysis itself, that is his call too, but make sure he has read the notes so they are actually his understanding.
