"""Makes a one-page reading (examples/sample-reading.pdf) to try the engine on: public-domain text, normal margins."""
import os
import sys

import pymupdf

TEXT = [
    "The Gift of the Magi, by O. Henry (1905)",
    "One dollar and eighty-seven cents. That was all. And sixty cents of it was in pennies. Pennies saved one and two at a "
    "time by bulldozing the grocer and the vegetable man and the butcher until one's cheeks burned with the silent "
    "imputation of parsimony that such close dealing implied. Three times Della counted it. One dollar and eighty-seven "
    "cents. And the next day would be Christmas.",
    "There was clearly nothing to do but flop down on the shabby little couch and howl. So Della did it. Which instigates "
    "the moral reflection that life is made up of sobs, sniffles, and smiles, with sniffles predominating.",
    "While the mistress of the home is gradually subsiding from the first stage to the second, take a look at the home. A "
    "furnished flat at $8 per week. It did not exactly beggar description, but it certainly had that word on the lookout "
    "for the mendicancy squad.",
    "Della finished her cry and attended to her cheeks with the powder rag. She stood by the window and looked out dully at "
    "a gray cat walking a gray fence in a gray backyard. Tomorrow would be Christmas Day, and she had only $1.87 with which "
    "to buy Jim a present.",
]


def make(out):
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    y = 90
    for i, para in enumerate(TEXT):
        size = 14 if i == 0 else 11
        left = page.insert_textbox(pymupdf.Rect(90, y, 522, 760), para, fontsize=size, fontname='tiro', lineheight=1.5)
        y = 760 - left + 12
    doc.save(out)
    return out


if __name__ == '__main__':
    print('saved', make(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'examples', 'sample-reading.pdf')))
