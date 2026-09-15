"""Inline SVG generators: QR codes and Code-128 barcodes for printed documents.

Both return raw <svg> markup (no XML declaration) safe to embed directly
in printable pages. Pure-python libraries — no Pillow / system deps.
"""
import io
import re

import qrcode
import qrcode.image.svg
import barcode as _barcode
from barcode.writer import SVGWriter

_XML_DECL = re.compile(r'<\?xml[^>]*\?>\s*|<!DOCTYPE[^>]*>\s*')


def qr_svg(data, size_mm=22):
    """QR code as inline SVG, ~size_mm square."""
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage,
                      box_size=10, border=1)
    buf = io.BytesIO()
    img.save(buf)
    svg = _XML_DECL.sub('', buf.getvalue().decode())
    svg = svg.replace('<svg ', f'<svg width="{size_mm}mm" height="{size_mm}mm" ', 1)
    return svg


def code128_svg(data, height_mm=9):
    """Code-128 barcode as inline SVG (no human-readable text line)."""
    if not data:
        return ''
    code = _barcode.get('code128', str(data), writer=SVGWriter())
    buf = io.BytesIO()
    code.write(buf, options={'write_text': False, 'module_height': height_mm,
                             'quiet_zone': 1.5})
    svg = _XML_DECL.sub('', buf.getvalue().decode())
    return svg
