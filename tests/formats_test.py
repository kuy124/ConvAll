"""Round-trip new table/image formats and preserve multiline CSV cells."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from PIL import Image
from convall_engine import convert, _rows_from, ConvertError

with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp)
    rows = [{'odd key & name': 'line one\nline two', 'value': '<hello> & café'}]
    source = d / 'table.json'
    source.write_text(json.dumps(rows), encoding='utf-8')
    for target in ('jsonl', 'xml', 'csv', 'tsv'):
        output = convert(source, target, d)[0]
        assert _rows_from(output) == rows, target
    malicious = d / 'unsafe.xml'
    malicious.write_text('<!DOCTYPE rows [<!ENTITY x "test">]><rows/>')
    try:
        _rows_from(malicious)
    except ConvertError:
        pass
    else:
        raise AssertionError('XML declarations must be rejected')
    picture = d / 'image.png'
    Image.new('RGB', (64, 64), 'navy').save(picture)
    for target in ('pbm', 'pgm', 'sgi', 'xbm', 'icns'):
        output = convert(picture, target, d)[0]
        with Image.open(output) as image:
            image.load()
            assert image.width > 0
print('new formats, table round trips, XML validation, multiline CSV OK')
