"""Generate labelled debug textures for every slot, to see which surface uses which material.

    python make_debug_textures.py
    python build.py build --textures _build/debug_textures --allow-shared --install

Each slot gets its own colour with its name printed on it. Grid lines are 50 cm apart and the
thick border marks one 2 m texture repeat. Text that reads backwards or arrows that point
sideways on a wall show a mapping problem. Requires Pillow (pip install pillow).
"""
import colorsys
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '_build', 'debug_textures')
SIZE = 512


def font(size):
    for name in ('arialbd.ttf', 'DejaVuSans-Bold.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def draw_slot(name, hue):
    bg = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.65, 0.85))
    img = Image.new('RGB', (SIZE, SIZE), bg)
    d = ImageDraw.Draw(img)
    for i in range(0, SIZE, SIZE // 4):
        d.line([(i, 0), (i, SIZE)], fill=(30, 30, 30), width=2)
        d.line([(0, i), (SIZE, i)], fill=(30, 30, 30), width=2)
    d.rectangle([0, 0, SIZE - 1, SIZE - 1], outline=(0, 0, 0), width=8)
    big, small = font(64 if len(name) < 9 else 44), font(28)
    for cy in (SIZE // 4, 3 * SIZE // 4):
        d.text((SIZE // 2, cy), name, font=big, fill=(255, 255, 255), anchor='mm', stroke_width=4, stroke_fill=(0, 0, 0))
    # Arrow pointing to the top of the image: should point up on walls.
    x, y = 40, SIZE // 2
    d.polygon([(x, y - 60), (x - 22, y - 20), (x + 22, y - 20)], fill=(255, 255, 255), outline=(0, 0, 0))
    d.rectangle([x - 7, y - 22, x + 7, y + 40], fill=(255, 255, 255), outline=(0, 0, 0))
    d.text((x, y + 62), 'UP', font=small, fill=(255, 255, 255), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0))
    return img


def main():
    slots = json.load(open(os.path.join(HERE, 'slots.json')))['slots']
    for i, name in enumerate(slots):
        folder = os.path.join(OUT, name)
        os.makedirs(folder, exist_ok=True)
        draw_slot(name, i / len(slots)).save(os.path.join(folder, 'albedo.png'))
        json.dump({'tint_strength': 0.0, 'roughness': 0.7, 'metallic': 0.0},
                  open(os.path.join(folder, 'settings.json'), 'w'))
    print('Wrote %d debug slots to %s' % (len(slots), OUT))


if __name__ == '__main__':
    main()
