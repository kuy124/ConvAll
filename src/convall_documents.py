"""Offline text-document import/export; no office installation required."""
import html
import zipfile
from html.parser import HTMLParser
from pathlib import Path
import xml.etree.ElementTree as ET

FORMATS = ('txt', 'md', 'html', 'docx', 'odt')
MAX_DOCUMENT_BYTES = 32 * 1024 * 1024


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        elif tag in ('p', 'div', 'br', 'li', 'tr') or tag.startswith('h') and len(tag) == 2:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def read_text(source):
    source = Path(source)
    ext = source.suffix.lower()
    if ext in ('.docx', '.odt'):
        member = 'word/document.xml' if ext == '.docx' else 'content.xml'
        with zipfile.ZipFile(source) as archive:
            if archive.getinfo(member).file_size > MAX_DOCUMENT_BYTES:
                raise ValueError('Document is too large to unpack safely')
            data = archive.read(member)
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
            raise ValueError('XML document declarations are not supported')
        root = ET.fromstring(data)
        # Paragraphs, including table cells; preserve their text, not formatting.
        return '\n'.join(''.join(p.itertext()) for p in root.iter()
                         if p.tag.split('}')[-1] in ('p', 'h'))
    if source.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError('Text document exceeds 32 MB')
    body = source.read_text(encoding='utf-8-sig', errors='replace')
    if ext in ('.html', '.htm'):
        parser = TextHTML()
        parser.feed(body)
        return ''.join(parser.parts).strip()
    return body


def write_text(body, output):
    output = Path(output)
    ext = output.suffix.lower()
    if ext == '.html':
        output.write_text('<!doctype html><html><head><meta charset="utf-8">'
                          '</head><body><pre>' + html.escape(body) +
                          '</pre></body></html>', encoding='utf-8')
    elif ext == '.docx':
        paragraphs = ''.join('<w:p><w:r><w:t xml:space="preserve">' +
                             html.escape(line) + '</w:t></w:r></w:p>'
                             for line in body.split('\n'))
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('[Content_Types].xml',
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
            archive.writestr('_rels/.rels',
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
            archive.writestr('word/document.xml',
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' +
                paragraphs + '</w:body></w:document>')
    elif ext == '.odt':
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('mimetype', 'application/vnd.oasis.opendocument.text')
            archive.writestr('META-INF/manifest.xml',
                '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
                '<manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>')
            archive.writestr('content.xml',
                '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2">'
                '<office:body><office:text>' + ''.join('<text:p>' + html.escape(line) +
                '</text:p>' for line in body.split('\n')) + '</office:text></office:body></office:document-content>')
    else:
        output.write_text(body, encoding='utf-8')
    return [output]
