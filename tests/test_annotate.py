"""
Tests for tools/annotate.py:  python3 -m unittest discover tests

The handwriting test runs only when HANDWRITING_ENGINE points at a Handwriting-Engine checkout; it writes fake
handwriting with that engine's test pen, so no real samples or passwords are needed.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import pymupdf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))
import annotate  # noqa: E402
import importlib  # noqa: E402

make_reading = importlib.import_module('make-reading')


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.pdf = make_reading.make(os.path.join(self.dir, 'reading.pdf'))

    def run_plan(self, annotations, *extra, **plan):
        plan = dict(pdf='reading.pdf', out='done.pdf', annotations=annotations, **plan)
        path = os.path.join(self.dir, 'plan.json')
        with open(path, 'w') as f:
            json.dump(plan, f)
        res = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'annotate.py'), 'apply', path, *extra],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return res, os.path.join(self.dir, 'done.pdf')


class FindQuote(Base):
    def test_ignores_case_punctuation_and_line_breaks(self):
        doc = pymupdf.open(self.pdf)
        hit = annotate.find_quote(doc, 'UNTIL ONE\'S CHEEKS burned')  # runs over a line break in the PDF
        self.assertIsNotNone(hit)
        page, rects = hit
        self.assertEqual(page, 0)
        self.assertEqual(len(rects), 2)

    def test_occurrence_picks_the_nth_match(self):
        doc = pymupdf.open(self.pdf)
        first = annotate.find_quote(doc, 'One dollar and eighty-seven cents', occurrence=1)
        second = annotate.find_quote(doc, 'One dollar and eighty-seven cents', occurrence=2)
        self.assertLess(first[1][0].y0, second[1][0].y0)
        self.assertIsNone(annotate.find_quote(doc, 'One dollar and eighty-seven cents', occurrence=3))

    def test_missing_quote(self):
        self.assertIsNone(annotate.find_quote(pymupdf.open(self.pdf), 'not in this story'))


class Apply(Base):
    def test_every_mark_with_a_preview_font(self):
        marks = ['highlight', 'underline', 'squiggle', 'strike', 'circle', 'box', 'bracket', 'double-bracket', 'star', 'check', 'vline']
        quotes = ['That was all', 'sixty cents', 'Three times Della counted it', 'the next day would be', 'shabby little couch',
                  'So Della did it', 'life is made up of sobs', 'gray cat', 'Tomorrow would be Christmas Day', 'powder rag', 'mendicancy squad']
        anns = [{'quote': q, 'mark': m, 'note': m} for q, m in zip(quotes, marks)]
        anns.append({'page': 1, 'at': 'top', 'note': 'summary at the top'})
        res, out = self.run_plan(anns, '--font')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(f'{len(anns)} of {len(anns)} annotations placed', res.stdout)
        page = pymupdf.open(out)[0]
        text = page.get_text()
        for m in marks:
            self.assertIn(m, text)  # every note was written
        self.assertGreater(len(page.get_drawings()), len(anns))

    def test_notes_stay_on_the_page_and_off_the_text(self):
        anns = [{'quote': q, 'note': 'a note that wraps over a few lines'} for q in
                ['That was all', 'grocer', 'imputation', 'Three times', 'Christmas.', 'clearly', 'moral', 'sniffles predominating']]
        res, out = self.run_plan(anns, '--font')
        page = pymupdf.open(out)[0]
        col = annotate.text_column(pymupdf.open(self.pdf)[0])
        boxes = [pymupdf.Rect(b[:4]) for b in page.get_text('blocks') if 'note' in b[4] or 'wraps' in b[4]]
        self.assertTrue(boxes)
        for b in boxes:
            self.assertTrue(page.rect.contains(b), b)
            self.assertFalse(b.intersects(col), b)
        for i, a in enumerate(boxes):  # and off each other
            for b in boxes[i + 1:]:
                self.assertFalse(pymupdf.Rect(a).intersects(b), (a, b))

    def test_vline_and_link_between_two_quotes(self):
        res, out = self.run_plan([
            {'quote': 'There was clearly nothing to do', 'mark': 'vline'},
            {'quote': 'One dollar and eighty-seven cents', 'mark': 'circle', 'link_to': '$1.87', 'note': 'same sum'},
        ], '--font')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        page = pymupdf.open(out)[0]
        col = annotate.text_column(pymupdf.open(self.pdf)[0])
        # the link runs down the left margin from the first quote to the second, near the bottom of the text
        ys = [p.y for d in page.get_drawings() for it in d['items'] if it[0] == 'l' for p in it[1:]
              if p.x < col.x0 - 2]
        self.assertTrue(ys)
        self.assertLess(min(ys), 140)
        self.assertGreater(max(ys), 380)  # $1.87 is on the last line, at y ~ 390

    def test_link_target_missing_is_reported(self):
        res, _ = self.run_plan([{'quote': 'That was all', 'link_to': 'not on this page'}], '--font')
        self.assertIn('to connect to', res.stdout)

    def test_reports_a_quote_it_cannot_find(self):
        res, _ = self.run_plan([{'quote': 'nowhere in the text', 'mark': 'circle'}], '--font')
        self.assertEqual(res.returncode, 1)
        self.assertIn('could not find', res.stdout)

    def test_extend_margin_makes_room(self):
        res, out = self.run_plan([{'quote': 'That was all', 'note': 'room', 'side': 'right'}], '--font', extend_margin=150)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertAlmostEqual(pymupdf.open(out)[0].rect.width, 612 + 150)


@unittest.skipUnless(os.environ.get('HANDWRITING_ENGINE'), 'set HANDWRITING_ENGINE to a Handwriting-Engine checkout')
class Handwriting(Base):
    def test_notes_in_fake_handwriting(self):
        engine = os.environ['HANDWRITING_ENGINE']
        samples = os.path.join(self.dir, 'fake.json')
        subprocess.run(['node', os.path.join(ROOT, 'tests', 'fake-handwriting.js'), engine, samples], check=True)
        res, out = self.run_plan([{'quote': 'That was all', 'mark': 'circle', 'note': 'the quick brown fox'}],
                                 '--engine', engine, '--samples', samples)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        page = pymupdf.open(out)[0]
        self.assertNotIn('quick brown fox', page.get_text())  # written as ink, not text
        self.assertGreater(len(page.get_drawings()), 2)


if __name__ == '__main__':
    unittest.main()
