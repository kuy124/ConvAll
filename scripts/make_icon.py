"""Size-tuned, antialiased artwork for Windows taskbars at different DPIs."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / 'assets'
SIZES = (16, 20, 24, 28, 32, 36, 40, 48, 60, 64, 72, 96, 128, 256)


def draw_icon(size):
    scale = 2
    final_size = size
    size *= scale
    image = Image.new('RGBA', (size, size))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, size - 1, size - 1),
                           radius=round(size * .23), fill='#17324f')
    # Two high-contrast arrows only: no tiny folds or overlapping badges.
    # Horizontal stems sit on whole pixels, with generous separation.
    left, right = round(size * .19), round(size * .81) - 1
    stem = max(2 * scale, round(final_size * .12) * scale)
    head = max(stem + 1, round(size * .23))
    for center, forward in ((round(size * .34), True),
                            (round(size * .66), False)):
        top = center - stem // 2
        bottom = top + stem - 1
        if forward:
            neck = right - head
            draw.rectangle((left, top, neck, bottom), fill='white')
            draw.polygon(((neck, center - head // 2), (right, center),
                          (neck, center + head // 2)), fill='white')
        else:
            neck = left + head
            draw.rectangle((neck, top, right, bottom), fill='white')
            draw.polygon(((neck, center - head // 2), (left, center),
                          (neck, center + head // 2)), fill='white')
    return image.resize((final_size, final_size), Image.Resampling.LANCZOS)


if __name__ == '__main__':
    icons = [draw_icon(size) for size in SIZES]
    icons[-1].save(OUT / 'icon.ico', sizes=[(s, s) for s in SIZES],
                   append_images=icons[:-1])
    with Image.open(OUT / 'icon.ico') as icon:
        assert icon.info['sizes'] == {(s, s) for s in SIZES}
        for original in icons:
            actual = icon.ico.getimage(original.size)
            assert actual.tobytes() == original.tobytes(), original.size
            assert any(0 < a < 255 for a in actual.getchannel('A').getdata()), \
                'rounded edges must be antialiased'
    print(f'All {len(SIZES)} antialiased icon sizes embedded and verified')
