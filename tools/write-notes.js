#!/usr/bin/env node
/*
 * Writes margin notes in a person's handwriting as transparent SVGs, using the Handwriting Engine
 * (github.com/nikigogonis2009/Handwriting-Engine) as a library. tools/annotate.py calls this; you
 * normally do not run it yourself.
 *
 *   node tools/write-notes.js --engine <Handwriting-Engine dir> --samples <my-handwriting.json | handwriting.enc.json> <notes.json> <outDir>
 *
 * notes.json: {"ink": "#1749b3", "notes": [{"name": "n1", "text": "foreshadowing", "kind": "text", "widthPt": 90,
 *              "xhPt": 5.5, "lineHeight": 2.4, "seed": 1, "neatness": 0.6}]}
 * Writes <outDir>/<name>.svg for each note and <outDir>/notes-manifest.json with each note's size in points
 * (trimmed to the ink, so a short note is a small box) and any characters that had no sample.
 * A sealed file needs HANDWRITING_PASSWORD in the environment (never as an argument).
 */
'use strict';
const fs = require('fs');
const path = require('path');

function parseArgs(argv) {
  const o = { rest: [] };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--engine') o.engine = argv[++i];
    else if (argv[i] === '--samples') o.samples = argv[++i];
    else if (argv[i] === '--password') throw new Error('Give the password in HANDWRITING_PASSWORD, not as an argument.');
    else o.rest.push(argv[i]);
  }
  [o.notesFile, o.outDir] = o.rest;
  if (!o.engine || !o.samples || !o.notesFile || !o.outDir) {
    throw new Error('usage: node tools/write-notes.js --engine <dir> --samples <file> <notes.json> <outDir>');
  }
  return o;
}

function loadSamples(engine, file) {
  const buf = fs.readFileSync(file);
  const sealed = require(path.join(engine, 'mcp/sealed'));
  if (sealed.isSealed(buf)) {
    if (!process.env.HANDWRITING_PASSWORD) throw new Error('This handwriting file is locked: set HANDWRITING_PASSWORD.');
    return sealed.unseal(buf, process.env.HANDWRITING_PASSWORD).toString('utf8');
  }
  return buf.toString('utf8');
}

function main() {
  const o = parseArgs(process.argv.slice(2));
  const engine = path.resolve(o.engine);
  const S = require(path.join(engine, 'src/style'));
  const Y = require(path.join(engine, 'src/synth'));
  const M = require(path.join(engine, 'src/math'));
  const R = require(path.join(engine, 'src/render'));

  const spec = JSON.parse(fs.readFileSync(o.notesFile, 'utf8'));
  const style = S.buildStyle(S.fromJSON(loadSamples(engine, o.samples)));
  fs.mkdirSync(o.outDir, { recursive: true });

  const XH = 34; // engine pixels per lowercase height (same as the engine's own tools)
  const render = { ink: spec.ink || '#1749b3', pen: 1, constant: true, paper: 'none' };
  const out = { notes: [] };
  for (const n of spec.notes || []) {
    const xhPt = n.xhPt || 5.5;
    const K = xhPt / XH; // engine px -> PDF points
    const lib = n.kind === 'math' ? M : Y;
    const lay = lib.layout(style, n.text, {
      xh: XH,
      width: Math.max(4 * XH, Math.round(n.widthPt / K)),
      lineHeight: n.lineHeight || (n.kind === 'math' ? 3.0 : 2.4),
      seed: n.seed || 1,
      margin: 2,
      messiness: 0.3,
      variation: 0.4,
      neatness: n.neatness == null ? 0.6 : n.neatness,
    });
    const pad = 0.1 * XH;
    const moved = R.fitLayout(lay, pad);
    // trim the box to the ink so a two-word note is a small box that sits right next to its text
    let maxX = 0;
    let maxY = 0;
    for (const s of lay.strokes) for (const p of s.pts) { maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y); }
    if (lay.strokes.length) {
      lay.width = Math.ceil(maxX + pad);
      lay.height = Math.ceil(maxY + pad);
    }
    fs.writeFileSync(path.join(o.outDir, n.name + '.svg'), R.toSVG(lay, render));
    out.notes.push({
      name: n.name,
      w: lay.width * K,
      h: Math.ceil(lay.height) * K,
      dx: moved.dx * K,
      dy: moved.dy * K,
      firstBaseline: (lay.baselines && lay.baselines.length ? lay.baselines[0] : XH) * K,
      missing: lay.missing || [],
    });
  }
  fs.writeFileSync(path.join(o.outDir, 'notes-manifest.json'), JSON.stringify(out, null, 1));
  console.error(`wrote ${out.notes.length} notes to ${o.outDir}`);
}

try {
  main();
} catch (e) {
  console.error(e.message);
  process.exit(1);
}
