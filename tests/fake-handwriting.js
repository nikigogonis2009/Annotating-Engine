#!/usr/bin/env node
/*
 * Writes a fake handwriting file (my-handwriting.json format) with the Handwriting Engine's own test pen, so the
 * annotating pipeline can be tested without anyone's real handwriting or password. The letters are ugly on purpose.
 *
 *   node tests/fake-handwriting.js <Handwriting-Engine dir> <out.json>
 */
'use strict';
const fs = require('fs');
const path = require('path');

const [, , engine, out] = process.argv;
if (!engine || !out) {
  console.error('usage: node tests/fake-handwriting.js <Handwriting-Engine dir> <out.json>');
  process.exit(2);
}
const { CORPUS } = require(path.resolve(engine, 'tests/fixtures'));
const { writeWord } = require(path.resolve(engine, 'tests/synth-writer'));
const words = [];
for (let rep = 0; rep < 2; rep++) CORPUS.forEach((w, i) => words.push(writeWord(w, { style: 'print', seed: rep * 1000 + i + 1 })));
fs.writeFileSync(out, JSON.stringify({ version: 1, words }));
console.error(`wrote ${words.length} fake words to ${out}`);
