"""Semantic cross-media routes and document round trips, using real decoders."""
import sys
import tempfile
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PIL import Image
import pypdfium2 as pdfium
from convall_engine import convert, conversion_route, targets_for, make_text_pdf
from convall_documents import read_text

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    text = root / 'hello.txt'
    text.write_text('Hello <world> & Unicode café\nSecond paragraph', encoding='utf-8')
    for fmt in ('docx', 'odt', 'html', 'md'):
        output = convert(text, fmt, root)[0]
        assert read_text(output).strip() == read_text(text).strip(), fmt
        if fmt in ('docx', 'odt'):
            assert zipfile.is_zipfile(output)
        pdf = convert(output, 'pdf', root / fmt)[0]
        with pdfium.PdfDocument(str(pdf)) as doc:
            assert len(doc) > 0
        png = convert(output, 'png', root / fmt)[0]
        with Image.open(png) as im:
            assert im.width > 100
        print(fmt, 'round trip, PDF and PNG OK')
    pic = root / 'sample.png'
    Image.new('RGB', (120, 80), 'red').save(pic)
    assert 'txt' not in targets_for(pic), 'Do not promise OCR'
    assert 'mp3' not in targets_for(pic), 'Do not synthesize speech from pixels'
    movie = convert(pic, 'mp4', root)[0]
    assert movie.stat().st_size > 1000
    table = root / 'rows.csv'
    table.write_text('name,value\nx,10\n', encoding='utf-8')
    for fmt in ('docx', 'odt', 'pdf', 'png'):
        assert convert(table, fmt, root)[0].stat().st_size > 100
    audio = convert(text, 'wav', root)[0]
    for fmt in ('pdf', 'webp', 'tif'):
        assert convert(audio, fmt, root)[0].stat().st_size > 100
    pdf = root / 'text.pdf'
    make_text_pdf(pdf)
    assert 'ConvAll' in read_text(convert(pdf, 'docx', root)[0])
    for fmt in ('flac', 'opus'):
        assert convert(text, fmt, root)[0].stat().st_size > 100
    print('image → video, table → documents/images, audio → documents/images, PDF → DOCX, text → audio OK')
print('cross-media routes OK')
