import json
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
import convall_engine as e
import pypdfium2 as pdfium
from unittest.mock import patch

with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp)
    opts = {'output_name': 'My track', 'title': 'Example', 'author': 'Alice',
            'album': 'Collection', 'sample_rate': 44100, 'channels': 1}
    out = e.convert(ROOT/'tests/samples/clip.mp4', 'mp3', d, opts)[0]
    assert out.stem == 'My track'
    result = e.run_process([e.ffprobe(), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(out)], capture_output=True, text=True)
    info = json.loads(result.stdout)
    assert info['format']['tags']['artist'] == 'Alice'
    assert info['format']['tags']['title'] == 'Example'
    assert info['streams'][0]['sample_rate'] == '44100'
    assert info['streams'][0]['channels'] == 1
    pdf = e.convert(ROOT/'tests/samples/blue.png', 'pdf', d, opts)[0]
    doc = pdfium.PdfDocument(str(pdf))
    assert doc.get_metadata_value('Author') == 'Alice'
    doc.close()
    for target in ('au', 'voc', 'w64', 'alac', 'nut', 'mpeg'):
        assert e.convert(ROOT/'tests/samples/clip.mp4', target, d)[0].stat().st_size
    with patch('convall_process.os.name', 'nt'), patch('convall_process.subprocess.run') as process, patch('convall_process.subprocess.CREATE_NO_WINDOW', 0x08000000, create=True):
        e.run_process(['ffmpeg', '-version'])
        assert process.call_args.kwargs['creationflags'] & 0x08000000
print('metadata, output name, audio properties, six formats, hidden subprocesses OK')
