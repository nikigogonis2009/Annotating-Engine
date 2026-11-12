#!/usr/bin/env python3
"""
Annotating Engine: marks up a PDF the way a student annotates a reading, with hand-drawn marks
(highlights, underlines, circles, brackets, stars...) and margin notes in the person's own
handwriting (written by the Handwriting Engine).

    python3 tools/annotate.py inspect reading.pdf [--text]
    python3 tools/annotate.py apply plan.json --engine hw-engine --samples my-handwriting.json [--png 110]
    python3 tools/annotate.py apply plan.json --font            # preview with a plain font, no handwriting needed

Annotations point at the text by quoting it, so nobody has to measure coordinates. See README.md for the
plan format. Needs PyMuPDF (pip install pymupdf) and, for handwriting, Node 18+.
"""
import argparse
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unicodedata

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))

INK = '#1749b3'  # Notability blue, same as the Handwriting Engine
HIGHLIGHTER = '#ffe14d'
GAP = 6.0  # points between the text column and anything in the margin
MIN_NOTE_W = 40.0
MAX_NOTE_W = 190.0
LINE_MARKS = {'highlight', 'underline', 'squiggle', 'strike'}
SHAPE_MARKS = {'circle', 'box'}
MARGIN_MARKS = {'bracket', 'star', 'check', 'double-bracket', 'vline'}
ALL_MARKS = LINE_MARKS | SHAPE_MARKS | MARGIN_MARKS | {'none'}
HIGHLIGHT_COLORS = {
    'yellow': '#ffe14d', 'green': '#8fe388', 'blue': '#8cc8ff', 'pink': '#ff9ecf', 'orange': '#ffb35c', 'purple': '#c9a3ff',
}


# ---------------------------------------------------------------- small helpers

def hex_rgb(h):
    h = HIGHLIGHT_COLORS.get(h, h).lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def norm_chars(s):
    """Lower-case letters and digits only, ligatures and accents folded, so a quote matches whatever the PDF stores."""
    s = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in s.lower() if c.isalnum())


def union(rects):
    r = pymupdf.Rect(rects[0])
    for q in rects[1:]:
        r |= q
    return r


# ---------------------------------------------------------------- reading the page

def page_words(page):
    """Words in reading order with their boxes: (rect, text, block, line)."""
    return [(pymupdf.Rect(w[:4]), w[4], w[5], w[6]) for w in page.get_text('words', sort=False)]


def text_column(page, words=None):
    """The box the body text sits in. Ignores stray words (page numbers, headers) by trimming the outermost 2%."""
    words = words if words is not None else page_words(page)
    if not words:
        r = page.rect
        return pymupdf.Rect(r.x0 + 72, r.y0 + 72, r.x1 - 72, r.y1 - 72)
    xs0 = sorted(w[0].x0 for w in words)
    xs1 = sorted(w[0].x1 for w in words)
    k = int(len(words) * 0.02)
    # lines run a little past the typical edge (ragged right); keep those, drop only far-out strays
    x0 = min(x for x in xs0 if x >= xs0[k] - 15)
    x1 = max(x for x in xs1 if x <= xs1[-1 - k] + 15)
    return pymupdf.Rect(x0, min(w[0].y0 for w in words), x1, max(w[0].y1 for w in words))


def is_scanned(page):
    """True when a picture covers most of the page (a scan or photo), so marks cannot go underneath the text."""
    area = abs(page.rect)
    for info in page.get_image_info():
        if abs(pymupdf.Rect(info['bbox']) & page.rect) > 0.5 * area:
            return True
    return False


def find_quote(doc, quote, page_no=None, occurrence=1):
    """
    Finds `quote` in the document and returns (page index, [line rects]) or None. Matching ignores case,
    punctuation, spacing, ligatures and hyphenation at line ends, so a quote can be typed as it reads.
    Pages are searched in order; `occurrence` picks the n-th match (counting from page_no if given).
    """
    target = norm_chars(quote)
    if not target:
        return None
    pages = [page_no - 1] if page_no else range(len(doc))
    seen = 0
    for pi in pages:
        if pi < 0 or pi >= len(doc):
            continue
        words = page_words(doc[pi])
        chars = []
        owner = []
        for i, w in enumerate(words):
            t = norm_chars(w[1])
            chars.append(t)
            owner.extend([i] * len(t))
        flat = ''.join(chars)
        start = 0
        while True:
            at = flat.find(target, start)
            if at < 0:
                break
            seen += 1
            if seen == occurrence:
                idx = sorted(set(owner[at:at + len(target)]))
                lines = {}
                for i in idx:
                    r, _, b, ln = words[i]
                    key = (b, ln)
                    lines[key] = lines[key] | r if key in lines else pymupdf.Rect(r)
                rects = sorted(lines.values(), key=lambda r: (round(r.y0), r.x0))
                return pi, rects
            start = at + 1
    return None


# ---------------------------------------------------------------- hand-drawn strokes

class Hand:
    """Makes polylines that look drawn by hand: a slow wander plus a little tremor, and ends that overshoot."""

    def __init__(self, seed):
        self.rng = random.Random(seed)

    def wander(self):
        r = self.rng
        a1, a2 = r.uniform(-1, 1), r.uniform(-1, 1)
        p1, p2 = r.uniform(0, 6.3), r.uniform(0, 6.3)
        return lambda t: a1 * math.sin(2.1 * t * math.pi + p1) + 0.5 * a2 * math.sin(4.7 * t * math.pi + p2)

    def line(self, p0, p1, amp=0.5, overshoot=0.0):
        (x0, y0), (x1, y1) = p0, p1
        L = math.hypot(x1 - x0, y1 - y0) or 1.0
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        x0, y0 = x0 - ux * overshoot * self.rng.random(), y0 - uy * overshoot * self.rng.random()
        x1, y1 = x1 + ux * overshoot * self.rng.random(), y1 + uy * overshoot * self.rng.random()
        L = math.hypot(x1 - x0, y1 - y0) or 1.0
        n = max(6, int(L / 3))
        f = self.wander()
        nx, ny = -(y1 - y0) / L, (x1 - x0) / L
        pts = []
        for i in range(n + 1):
            t = i / n
            w = amp * f(t) + self.rng.gauss(0, amp * 0.08)
            pts.append((x0 + (x1 - x0) * t + nx * w, y0 + (y1 - y0) * t + ny * w))
        return pts

    def wave(self, x0, x1, y, amp=1.1, period=4.5):
        n = max(8, int((x1 - x0) / 0.8))
        ph = self.rng.uniform(0, 6.3)
        drift = self.wander()
        return [(x0 + (x1 - x0) * i / n,
                 y + amp * math.sin(2 * math.pi * (x1 - x0) * i / n / period + ph) + 0.4 * drift(i / n)) for i in range(n + 1)]

    def loop(self, rect, pad_x=4.0, pad_y=3.0):
        """A loose oval round `rect`, drawn a little more than once round, like a quick pen circle."""
        r = self.rng
        cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
        rx, ry = rect.width / 2 + pad_x, rect.height / 2 + pad_y
        a0 = r.uniform(-2.6, -2.0)  # start at the upper left, as most people do
        turns = r.uniform(1.06, 1.16)
        f = self.wander()
        tilt = r.uniform(-0.03, 0.03)
        n = 96
        pts = []
        for i in range(n + 1):
            t = i / n
            a = a0 + 2 * math.pi * turns * t
            grow = 1 + 0.05 * f(t) + 0.06 * t  # the second pass lands a little outside the first
            x, y = rx * grow * math.cos(a), ry * grow * math.sin(a)
            pts.append((cx + x - tilt * y, cy + y + tilt * x))
        return pts

    def box(self, rect, pad=2.5):
        r = pymupdf.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)
        c = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
        return [self.line(c[i], c[(i + 1) % 4], amp=0.4, overshoot=2.0) for i in range(4)]

    def bracket(self, x, y0, y1, toward):
        hook = 3.0 * toward
        return [self.line((x + hook, y0), (x, y0 + 0.5), 0.15) + self.line((x, y0 + 0.5), (x, y1 - 0.5), 0.5)[1:]
                + self.line((x, y1 - 0.5), (x + hook, y1), 0.15)[1:]]

    def star(self, cx, cy, size=4.0):
        a0 = -math.pi / 2 + self.rng.uniform(-0.2, 0.2)
        pts = []
        for i in range(6):
            a = a0 + i * 4 * math.pi / 5
            pts.append((cx + size * math.cos(a) + self.rng.gauss(0, 0.25), cy + size * math.sin(a) + self.rng.gauss(0, 0.25)))
        return [pts]

    def check(self, cx, cy, size=4.0):
        p = [(cx - size, cy), (cx - size * 0.3, cy + size * 0.8), (cx + size, cy - size * 1.1)]
        return [self.line(p[0], p[1], 0.2) + self.line(p[1], p[2], 0.3)[1:]]

    def arrow(self, way, head=3.2):
        """A leader through the waypoints, rounded at the corners like one stroke of the pen, with an arrowhead."""
        pts = []
        for p, q in zip(way, way[1:]):
            seg = self.line(p, q, amp=0.3)
            pts.extend(seg if not pts else seg[1:])
        for _ in range(3):  # Chaikin: round the corners off
            sm = [pts[0]]
            for p, q in zip(pts, pts[1:]):
                sm += [(0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]), (0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1])]
            sm.append(pts[-1])
            pts = sm
        x1, y1 = pts[-1]
        bx, by = pts[max(0, len(pts) - 8)]
        ang = math.atan2(y1 - by, x1 - bx)
        tip = [(x1 - head * math.cos(ang - 0.5), y1 - head * math.sin(ang - 0.5)), (x1, y1),
               (x1 - head * math.cos(ang + 0.5), y1 - head * math.sin(ang + 0.5))]
        return [pts, tip]


# ---------------------------------------------------------------- notes: handwriting or a plain-font preview

def render_notes_handwriting(notes, args, ink, tmp):
    spec = {'ink': ink, 'notes': [{k: n[k] for k in ('name', 'text', 'kind', 'widthPt', 'xhPt', 'seed', 'neatness') if k in n} for n in notes]}
    path = os.path.join(tmp, 'notes.json')
    with open(path, 'w') as f:
        json.dump(spec, f)
    cmd = ['node', os.path.join(HERE, 'write-notes.js'), '--engine', args.engine, '--samples', args.samples, path, tmp]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        sys.exit('writing the notes failed: ' + res.stderr.strip())
    with open(os.path.join(tmp, 'notes-manifest.json')) as f:
        made = {m['name']: m for m in json.load(f)['notes']}
    for n in notes:
        m = made[n['name']]
        n.update(w=m['w'], h=m['h'], missing=m['missing'], svg=os.path.join(tmp, n['name'] + '.svg'))


def wrap(text, width, size, font='helv'):
    lines, cur = [], ''
    for word in text.split():
        trial = (cur + ' ' + word).strip()
        if cur and pymupdf.get_text_length(trial, fontname=font, fontsize=size) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def render_notes_font(notes):
    for n in notes:
        size = n['xhPt'] / 0.52  # Helvetica's x-height is about 0.52 of its size
        lines = wrap(n['text'], n['widthPt'], size)
        n['lines'] = lines
        n['size'] = size
        n['w'] = max([pymupdf.get_text_length(t, fontname='helv', fontsize=size) for t in lines] + [1]) + 1
        n['h'] = len(lines) * size * 1.25 + 2
        n['missing'] = []


# ---------------------------------------------------------------- layout

class Margins:
    """What is already in each margin of a page, so notes do not land on each other."""

    def __init__(self, page, col):
        self.page, self.col = page, col
        self.taken = {'left': [], 'right': []}
        self.inner = {'left': [], 'right': []}  # brackets and symbols right next to the text: (y0, y1, width)
        self.left_w = col.x0 - page.rect.x0 - 2 * GAP
        self.right_w = page.rect.x1 - col.x1 - 2 * GAP

    def width(self, side):
        return min(MAX_NOTE_W, self.left_w if side == 'left' else self.right_w)

    def usable(self, side):
        return self.width(side) >= MIN_NOTE_W

    def place(self, side, y_want, h, x_in=0.0):
        """Top y for an h-tall thing in `side`, as close below y_want as fits, or None when the page runs out."""
        top = max(y_want, self.page.rect.y0 + 10)
        for (a, b) in sorted(self.taken[side]):
            if top < b + 2 and top + h + 2 > a:
                top = max(top, b + 3)
        if top + h > self.page.rect.y1 - 10:
            return None
        return top

    def take(self, side, y0, y1):
        self.taken[side].append((y0, y1))

    def inset(self, side, y0, y1):
        """How far a note between y0 and y1 must sit out from the text to clear the brackets and symbols there."""
        return max([w for (a, b, w) in self.inner[side] if a < y1 and b > y0] + [0.0])

    def spot(self, side, want, w, h):
        """(top, inset) for a w x h note in `side`, beside any bracket or symbol when it fits there, else below it."""
        room = self.left_w if side == 'left' else self.right_w
        for _ in range(20):
            top = self.place(side, want, h)
            if top is None:
                return None
            inset = self.inset(side, top, top + h)
            if w + inset <= room + 2:
                return top, inset
            want = max(b for (a, b, _w) in self.inner[side] if a < top + h and b > top) + 2
        return None


def choose_side(want, anchor, m):
    if want in ('left', 'right'):
        return want if m.usable(want) else ('right' if want == 'left' else 'left')
    mid = (m.col.x0 + m.col.x1) / 2
    if (anchor.x0 + anchor.x1) / 2 < mid - m.col.width * 0.25 and m.usable('left'):
        return 'left'
    return 'right' if m.usable('right') else 'left'


# ---------------------------------------------------------------- applying a plan

def widen(doc, extra_left, extra_right):
    """A copy of the document with blank space added at the sides of every page, for room to write."""
    out = pymupdf.open()
    for page in doc:
        r = page.rect
        new = out.new_page(width=r.width + extra_left + extra_right, height=r.height)
        new.show_pdf_page(pymupdf.Rect(extra_left, 0, extra_left + r.width, r.height), doc, page.number)
    return out


def apply(args):
    with open(args.plan) as f:
        plan = json.load(f)
    base = os.path.dirname(os.path.abspath(args.plan))
    src = os.path.join(base, plan['pdf']) if not os.path.isabs(plan['pdf']) else plan['pdf']
    dst = plan.get('out') or os.path.splitext(src)[0] + '-annotated.pdf'
    dst = os.path.join(base, dst) if not os.path.isabs(dst) else dst

    doc = pymupdf.open(src)
    ext = plan.get('extend_margin') or 0
    ext_l, ext_r = (ext.get('left', 0), ext.get('right', 0)) if isinstance(ext, dict) else (0, ext)
    if ext_l or ext_r:
        doc = widen(doc, ext_l, ext_r)

    ink = plan.get('ink', INK)
    note_xh = float(plan.get('note_xh_pt', 5.5))
    pen = float(plan.get('pen_pt', max(0.6, 0.12 * note_xh)))
    seed = int(plan.get('seed', 1))
    report = []

    words = {i: page_words(doc[i]) for i in range(len(doc))}
    margins = {i: Margins(doc[i], text_column(doc[i], words[i])) for i in range(len(doc))}

    # 1. find every quote
    items = []
    for k, a in enumerate(plan.get('annotations', [])):
        a = dict(a)
        a['i'] = k
        mark = a.get('mark', 'highlight' if a.get('quote') else 'none')
        if mark not in ALL_MARKS:
            report.append(f'#{k + 1}: unknown mark "{mark}" (use one of {", ".join(sorted(ALL_MARKS))})')
            continue
        a['mark'] = mark
        if a.get('quote'):
            hit = find_quote(doc, a['quote'], a.get('page'), int(a.get('occurrence', 1)))
            if not hit:
                report.append(f'#{k + 1}: could not find "{a["quote"][:60]}"' + (f' on page {a["page"]}' if a.get('page') else ''))
                continue
            a['pi'], a['rects'] = hit
        else:
            if not a.get('page'):
                report.append(f'#{k + 1}: a note without a quote needs a page')
                continue
            a['pi'], a['rects'] = a['page'] - 1, None
        items.append(a)

    # 2. decide where each note goes, and how wide it may be
    notes = []
    for a in items:
        if not a.get('note'):
            continue
        m = margins[a['pi']]
        at = a.get('at')
        if 'x' in a and 'y' in a:
            width = float(a.get('width', 150))
        elif at in ('top', 'bottom'):
            width = m.col.width
        elif a['rects']:
            a['side'] = choose_side(a.get('side', 'auto'), union(a['rects']), m)
            width = m.width(a['side'])
            if width < MIN_NOTE_W:
                report.append(f'#{a["i"] + 1}: page {a["pi"] + 1} has no room in the margins for a note '
                              f'(add "extend_margin": 150 to the plan, or give the note an x and y)')
                a['note'] = None
                continue
        else:
            at = a['at'] = 'top'
            width = m.col.width
        a['note_spec'] = {'name': f'n{a["i"] + 1}', 'text': a['note'], 'kind': a.get('kind', 'text'),
                          'widthPt': width, 'xhPt': float(a.get('note_xh_pt', note_xh)),
                          'seed': int(a.get('seed', seed + a['i'])), 'neatness': a.get('neatness', 0.6)}
        notes.append(a['note_spec'])

    tmp = tempfile.mkdtemp(prefix='annot-')
    try:
        if notes:
            if args.font:
                render_notes_font(notes)
            else:
                render_notes_handwriting(notes, args, ink, tmp)
        for n in notes:
            if n['missing']:
                report.append(f'{n["name"]}: no handwriting sample for {" ".join(n["missing"])} (left out)')

        # 3. draw, page by page, top to bottom
        hand = Hand(seed)
        ink_rgb = hex_rgb(ink)
        for pi in range(len(doc)):
            page = doc[pi]
            page_items = sorted([a for a in items if a['pi'] == pi],
                                key=lambda a: a['rects'][0].y0 if a['rects'] else -1)
            if not page_items:
                continue
            m = margins[pi]
            under = not is_scanned(page) and plan.get('highlight_under_text', True)
            hl = page.new_shape()
            pen_shape = page.new_shape()
            placed = []

            def stroke(lines, width=pen, color=ink_rgb, closed=False):
                for ln in lines:
                    pen_shape.draw_polyline(ln)
                    pen_shape.finish(color=color, width=width, lineCap=1, lineJoin=1, closePath=closed, fill=None)

            def link(a, U):
                """An arrow from this quote to another one on the page ("connect ideas"), looping through the margin."""
                hit = find_quote(doc, a['link_to'], pi + 1, int(a.get('link_occurrence', 1)))
                if not hit:
                    report.append(f'#{a["i"] + 1}: could not find "{a["link_to"][:60]}" on page {pi + 1} to connect to')
                    return
                T = hit[1]
                S = a['rects']
                # the margin both ends are nearer to, so the arrow crosses as little text as possible
                dl = min(r.x0 for r in S) + min(r.x0 for r in T) - 2 * m.col.x0
                dr = 2 * m.col.x1 - max(r.x1 for r in S) - max(r.x1 for r in T)
                side = a.get('link_side') or ('left' if dl <= dr else 'right')
                out = -1 if side == 'left' else 1
                down = T[0].y0 > S[0].y0
                src = S[-1] if down else S[0]
                dst = T[0] if down else T[-1]
                # the lane is the narrow strip between the text and the notes (notes start GAP out), so it pushes
                # nothing aside; only a bracket or symbol already there moves it further out
                inner = m.inset(side, min(src.y0, dst.y0), max(src.y1, dst.y1))
                lane = (m.col.x0 if side == 'left' else m.col.x1) + out * (3.0 + (inner + 2 if inner else 0))

                def end_x(rs, r):
                    same = [q for q in rs if abs(q.y0 - r.y0) < 1]
                    return min(q.x0 for q in same) + 2 if side == 'left' else max(q.x1 for q in same) - 2

                sx, tx = end_x(S, src), end_x(T, dst)
                # leave and arrive along the gaps between lines, never through words
                gs = src.y1 + 1.8 if down else src.y0 - 1.8
                gt = dst.y0 - 1.8 if down else dst.y1 + 1.8
                sy, ty = gs, (dst.y0 + dst.y1) / 2 + (-3 if down else 3)
                way = [(sx, gs), (lane, gs), (lane, gt), (tx, gt), (tx, ty)]
                stroke(hand.arrow(way), width=pen * 0.9)

            for a in page_items:
                rects = a['rects']
                mark = a['mark']
                color = a.get('color')
                if rects:
                    for r in rects:
                        if mark == 'highlight':
                            y = (r.y0 + r.y1) / 2 + hand.rng.uniform(-0.3, 0.3)
                            tilt = hand.rng.uniform(-0.5, 0.5)
                            hl.draw_polyline(hand.line((r.x0 - 1.2, y - tilt), (r.x1 + 1.2, y + tilt), amp=0.35, overshoot=1.0))
                            hl.finish(color=hex_rgb(color or plan.get('highlighter', HIGHLIGHTER)), width=r.height * 0.95,
                                      lineCap=0, lineJoin=1, closePath=False, fill=None,
                                      stroke_opacity=1.0 if under else 0.38)
                        elif mark == 'underline':
                            stroke([hand.line((r.x0, r.y1 + 0.6), (r.x1, r.y1 + 0.6), amp=0.45, overshoot=1.5)], color=hex_rgb(color or ink))
                        elif mark == 'squiggle':
                            stroke([hand.wave(r.x0, r.x1, r.y1 + 1.3)], color=hex_rgb(color or ink))
                        elif mark == 'strike':
                            ym = (r.y0 + r.y1) / 2 + 0.6
                            stroke([hand.line((r.x0, ym), (r.x1, ym), amp=0.35, overshoot=1.5)], color=hex_rgb(color or ink))
                    U = union(rects)
                    if mark == 'circle':
                        stroke([hand.loop(U)], color=hex_rgb(color or ink))
                    elif mark == 'box':
                        stroke(hand.box(U), color=hex_rgb(color or ink))
                    elif mark in MARGIN_MARKS:
                        side = a.get('side') if a.get('side') in ('left', 'right') else choose_side('auto', U, m)
                        a.setdefault('side', side)
                        edge = m.col.x0 - GAP if side == 'left' else m.col.x1 + GAP
                        out = -1 if side == 'left' else 1
                        if mark in ('bracket', 'double-bracket'):
                            stroke(hand.bracket(edge, U.y0, U.y1, -out))
                            if mark == 'double-bracket':
                                stroke(hand.bracket(edge + 2.2 * out, U.y0 + 0.5, U.y1 - 0.5, -out))
                            m.inner[side].append((U.y0, U.y1, 6.0 if mark == 'bracket' else 8.5))
                        elif mark == 'vline':  # "this whole passage matters": a plain line down the margin
                            stroke([hand.line((edge, U.y0), (edge, U.y1), amp=0.5, overshoot=1.0)])
                            m.inner[side].append((U.y0, U.y1, 5.0))
                        else:
                            cx = edge + 4.5 * out
                            cy = (rects[0].y0 + rects[0].y1) / 2
                            stroke(hand.star(cx, cy) if mark == 'star' else hand.check(cx, cy))
                            m.inner[side].append((cy - 5, cy + 5, 11.0))

                    if a.get('link_to'):
                        link(a, U)

            # notes go in after every mark, so they can make way for brackets and symbols further down the page
            for a in page_items:
                rects, mark = a['rects'], a['mark']
                n = a.get('note_spec') if a.get('note') else None
                if not n:
                    continue
                # where the note goes
                if 'x' in a and 'y' in a:
                    box = pymupdf.Rect(a['x'], a['y'], a['x'] + n['w'], a['y'] + n['h'])
                elif a.get('at') in ('top', 'bottom'):
                    if a['at'] == 'top':
                        top = max(page.rect.y0 + 12, m.col.y0 - n['h'] - 8)
                        if top + n['h'] > m.col.y0 - 2:
                            report.append(f'{n["name"]}: no room above the text on page {pi + 1}; it may overlap the text')
                    else:
                        top = min(page.rect.y1 - 12 - n['h'], m.col.y1 + 8)
                        if top < m.col.y1 + 2:
                            report.append(f'{n["name"]}: no room below the text on page {pi + 1}; it may overlap the text')
                    box = pymupdf.Rect(m.col.x0, top, m.col.x0 + n['w'], top + n['h'])
                else:
                    side = a['side']
                    want = rects[0].y0 - n['xhPt'] * 0.9
                    got = m.spot(side, want, n['w'], n['h'])
                    if got is None:
                        other = 'left' if side == 'right' else 'right'
                        if m.usable(other) and m.width(other) >= n['w']:
                            got = m.spot(other, want, n['w'], n['h'])
                            side = other
                    if got is None:
                        report.append(f'{n["name"]}: no room left in the margins of page {pi + 1}; not written')
                        continue
                    top, inset = got
                    if abs(top - want) > n['h'] * 1.5:
                        report.append(f'{n["name"]}: moved {top - want:.0f} pt down to make room; joined to its text with a line')
                    m.take(side, top, top + n['h'])
                    if side == 'right':
                        x0 = m.col.x1 + GAP + inset
                    else:
                        x0 = m.col.x0 - GAP - inset - n['w']
                    box = pymupdf.Rect(x0, top, x0 + n['w'], top + n['h'])
                    a['side'] = side
                    # a line from the note to its text when the eye cannot make the link on its own
                    U = union(rects)
                    near_x = U.x1 if side == 'right' else U.x0
                    if len(rects) > 1:
                        near_x = max(r.x1 for r in rects) if side == 'right' else min(r.x0 for r in rects)
                    far = abs((box.x0 if side == 'right' else box.x1) - near_x) > 28
                    moved = abs(top - want) > n['h'] * 1.5
                    arrow = a.get('arrow')
                    if arrow is None:
                        arrow = mark not in MARGIN_MARKS and (far or moved)
                    if arrow:
                        ny = box.y0 + min(n['h'] / 2, n['xhPt'] * 1.6)
                        out = 1 if side == 'right' else -1
                        sx = box.x0 - 1.5 if side == 'right' else box.x1 + 1.5
                        tr = rects[0] if ny <= (rects[0].y0 + rects[0].y1) / 2 or len(rects) == 1 else rects[-1]
                        same = [r for r in rects if abs(r.y0 - tr.y0) < 1]
                        pad = 5.5 if mark == 'circle' else 3.5 if mark == 'box' else 1.5
                        tx = (max(r.x1 for r in same) if side == 'right' else min(r.x0 for r in same)) + pad * out
                        mid = (tr.y0 + tr.y1) / 2
                        # run along the gap between lines (below the quote if the note is lower, above if higher),
                        # turning into the column only at its edge, so the leader never crosses through words
                        gy = tr.y1 + 1.8 if ny >= mid else tr.y0 - 1.8
                        edge = (m.col.x1 if side == 'right' else m.col.x0) + 3 * out
                        way = [(sx, ny)]
                        if abs(edge - tx) > 10:
                            way += [(edge, gy), (tx + 6 * out, gy)]
                        way.append((tx, mid + (1.5 if gy > mid else -1.5)))
                        stroke(hand.arrow(way), width=pen * 0.9)
                placed.append((n, box))

            if under:
                hl.commit(overlay=False)
            else:
                hl.commit(overlay=True)
            pen_shape.commit()
            for n, box in placed:
                if args.font:
                    y = box.y0 + n['size']
                    for t in n['lines']:
                        page.insert_text((box.x0, y), t, fontname='helv', fontsize=n['size'], color=ink_rgb)
                        y += n['size'] * 1.25
                else:
                    svg = pymupdf.open(n['svg'])
                    part = pymupdf.open('pdf', svg.convert_to_pdf())
                    page.show_pdf_page(box, part, 0)

        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        doc.save(dst, garbage=3, deflate=True)
        print('saved', dst)
        if args.png:
            stem = os.path.splitext(dst)[0]
            for page in doc:
                if any(a['pi'] == page.number for a in items):
                    p = f'{stem}_page{page.number + 1}.png'
                    page.get_pixmap(dpi=args.png).save(p)
                    print('picture', p)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    found = sum(1 for a in items)
    print(f'{found} of {len(plan.get("annotations", []))} annotations placed')
    for r in report:
        print('note:', r)
    return 0 if found == len(plan.get('annotations', [])) else 1


# ---------------------------------------------------------------- inspect

def inspect(args):
    doc = pymupdf.open(args.pdf)
    for page in doc:
        words = page_words(page)
        col = text_column(page, words)
        r = page.rect
        print(f'page {page.number + 1}: {r.width:.0f} x {r.height:.0f} pt, text column x {col.x0:.0f}..{col.x1:.0f}, '
              f'y {col.y0:.0f}..{col.y1:.0f}; margins left {col.x0 - r.x0:.0f}, right {r.x1 - col.x1:.0f}, '
              f'top {col.y0 - r.y0:.0f}, bottom {r.y1 - col.y1:.0f} pt' + ('; scanned' if is_scanned(page) else '')
              + ('' if words else '; NO TEXT LAYER (run OCR first, quotes cannot be found)'))
        if args.text:
            lines = {}
            for w in words:
                lines.setdefault((w[2], w[3]), []).append(w)
            for i, (_, ws) in enumerate(sorted(lines.items(), key=lambda kv: (round(kv[1][0][0].y0), kv[1][0][0].x0))):
                print(f'  L{i + 1:<3} y={ws[0][0].y0:5.0f}  ' + ' '.join(w[1] for w in ws))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    i = sub.add_parser('inspect', help='page sizes, margins and (with --text) the text, line by line')
    i.add_argument('pdf')
    i.add_argument('--text', action='store_true')
    a = sub.add_parser('apply', help='annotate a PDF from a plan')
    a.add_argument('plan')
    a.add_argument('--engine', default=os.environ.get('HANDWRITING_ENGINE'), help='Handwriting-Engine folder')
    a.add_argument('--samples', default=os.environ.get('HANDWRITING_FILE'), help='my-handwriting.json or handwriting.enc.json')
    a.add_argument('--font', action='store_true', help='write notes in a plain font (a preview; no handwriting needed)')
    a.add_argument('--png', type=int, default=0, help='also save a picture of each annotated page at this dpi')
    args = ap.parse_args()
    if args.cmd == 'apply' and not args.font and not (args.engine and args.samples):
        ap.error('apply needs --engine and --samples for handwriting, or --font for a preview')
    sys.exit(inspect(args) if args.cmd == 'inspect' else apply(args))


if __name__ == '__main__':
    main()
