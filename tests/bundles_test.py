"""Multiple outputs are atomic ZIPs; PDF documents and ebooks round trip."""
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
import convall_engine as engine
from convall_documents import read_text
from PIL import Image
from pypdf import PdfReader, PdfWriter

with tempfile.TemporaryDirectory() as temp:
    d = Path(temp)
    single = d / 'text.pdf'
    engine.make_text_pdf(single)
    writer = PdfWriter()
    reader = PdfReader(single)
    writer.add_page(reader.pages[0])
    writer.add_page(reader.pages[0])
    pdf = d / 'pages.pdf'
    writer.write(pdf)
    for fmt in ('png', 'jpg', 'webp'):
        outdir = d / fmt
        outputs = engine.convert(pdf, fmt, outdir)
        assert len(outputs) == 1 and outputs[0].suffix == '.zip'
        assert list(outdir.iterdir()) == outputs, 'Loose output or staging files leaked'
        with zipfile.ZipFile(outputs[0]) as archive:
            assert len(archive.namelist()) == 2 and archive.testzip() is None
            for member in archive.namelist():
                with archive.open(member) as file:
                    Image.open(file).verify()
    again = engine.convert(pdf, 'png', d / 'png')[0]
    assert again.name != 'pages_png.zip', 'Existing archive overwritten'
    custom = engine.convert(pdf, 'png', d / 'custom', {'output_name': 'Faris'})[0]
    assert custom.name == 'Faris_png.zip'
    assert engine.convert(single, 'png', d / 'one')[0].suffix == '.png'
    for fmt in ('docx', 'odt', 'html', 'epub', 'fb2'):
        assert engine.conversion_route(pdf, fmt) == [fmt]
        out = engine.convert(pdf, fmt, d / 'books')[0]
        assert 'ConvAll' in read_text(out), (fmt, read_text(out))
        text = engine.convert(out, 'txt', d / 'roundtrip')[0]
        assert 'ConvAll' in text.read_text(encoding='utf-8')
    clip = ROOT / 'tests' / 'samples' / 'clip.mp4'
    frames = engine.convert(clip, 'png-frames', d / 'frames')[0]
    with zipfile.ZipFile(frames) as archive:
        assert len(archive.namelist()) > 1
    print('PDF pages and video frames ZIP; collision safety; PDF to DOCX/ODT/HTML/EPUB/FB2 OK')
