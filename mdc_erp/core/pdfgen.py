"""Server-side PDF generation (reportlab) for invoices and receipts.

The PDFs carry the SAME branded letterhead the HTML print views use: the
letterhead header/footer artwork (static/brand/letterhead-*.jpg, or the
`letterhead_header`/`letterhead_footer` settings) plus a faint centre
watermark of the MDC logo — all governed by the same `letterhead` and
`wm_on` settings. Falls back to a clean text header/footer when the artwork
is switched off, and degrades gracefully if reportlab is unavailable.
"""
import io
import os

PETROL = '#044C8C'


def _qr_png(data):
    """Return an ImageReader of a QR code for `data`, or None if unavailable."""
    try:
        import qrcode
        from reportlab.lib.utils import ImageReader
        img = qrcode.make(str(data), box_size=10, border=1)
        b = io.BytesIO(); img.save(b, format='PNG'); b.seek(0)
        return ImageReader(b)
    except Exception:
        return None


def _barcode_png(text):
    """Return (ImageReader, aspect) of a Code128 barcode for `text`, or (None,1)."""
    try:
        import barcode
        from barcode.writer import ImageWriter
        from reportlab.lib.utils import ImageReader
        bc = barcode.get('code128', str(text), writer=ImageWriter())
        b = io.BytesIO()
        bc.write(b, options={'module_height': 8.0, 'module_width': 0.28,
                             'font_size': 0, 'text_distance': 1, 'quiet_zone': 2})
        b.seek(0)
        from PIL import Image
        im = Image.open(b); asp = im.height / im.width if im.width else 0.3
        b.seek(0)
        return ImageReader(b), asp
    except Exception:
        return None, 0.3


def _draw_barcode(c, text, x, y, width, height):
    """Draw a Code128 barcode using reportlab's BUILT-IN barcode engine (always
    available — no external 'python-barcode' library needed), so the barcode never
    silently drops from the PDF. Draws within the given box, right-aligned width."""
    try:
        from reportlab.graphics.barcode import code128
        bc = code128.Code128(str(text), barHeight=height, humanReadable=False, quiet=False)
        # scale horizontally to fit the requested width
        bw = bc.width or width
        sx = (width / bw) if bw else 1.0
        c.saveState()
        c.translate(x, y)
        c.scale(sx, 1.0)
        bc.drawOn(c, 0, 0)
        c.restoreState()
        return True
    except Exception:
        # last-resort fallback to the image method (external lib), if present
        img, asp = _barcode_png(text)
        if img is not None:
            c.drawImage(img, x, y, width, min(height, width * asp), mask='auto')
            return True
        return False


def available():
    try:
        import reportlab  # noqa: F401
        return True
    except Exception:
        return False


def _brand_dir():
    return os.path.join(os.path.dirname(__file__), '..', 'static', 'brand')


def _asset(setting, key, default_file):
    """Resolve a letterhead asset to an on-disk path (honours the setting, else the bundled file)."""
    val = (setting(key, '') or '').strip()
    if val:
        # a stored setting like '/static/brand/xyz.jpg' → map back to disk
        name = val.split('/static/brand/')[-1] if '/static/brand/' in val else os.path.basename(val)
        p = os.path.join(_brand_dir(), name)
        if os.path.exists(p):
            return p
    p = os.path.join(_brand_dir(), default_file)
    return p if os.path.exists(p) else None


def _faint_logo(alpha=0.06):
    """A very faint RGBA copy of the logo for use as a page watermark."""
    try:
        from PIL import Image
        from reportlab.lib.utils import ImageReader
    except Exception:
        return None
    p = os.path.join(_brand_dir(), 'mdc-logo.png')
    if not os.path.exists(p):
        return None
    try:
        im = Image.open(p).convert('RGBA')
        a = im.split()[3].point(lambda v: int(v * alpha))
        im.putalpha(a)
        buf = io.BytesIO(); im.save(buf, 'PNG'); buf.seek(0)
        return ImageReader(buf)
    except Exception:
        return None


def _draw_letterhead(c, W, H, company, doc_ref):
    """Draw the branded header + footer bands and the faint watermark.

    Returns (top_y, bottom_y): the usable vertical band for document content.
    """
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader
    try:
        from .helpers import setting
    except Exception:
        def setting(k, d=''):
            return d

    lh_on = (setting('letterhead', '1') or '1') == '1'
    wm_on = (setting('wm_on', '1') or '1').strip() == '1'
    header_img = _asset(setting, 'letterhead_header', 'letterhead-header.jpg') if lh_on else None
    footer_img = _asset(setting, 'letterhead_footer', 'letterhead-footer.jpg') if lh_on else None

    top_y = H - 20 * mm
    bottom_y = 18 * mm

    # ---- header ----
    if header_img:
        try:
            ir = ImageReader(header_img)
            iw, ih = ir.getSize()
            hh = W * (ih / float(iw))            # full-bleed, keep aspect
            c.drawImage(ir, 0, H - hh, width=W, height=hh, mask='auto')
            top_y = H - hh - 8 * mm
        except Exception:
            header_img = None
    if not header_img:
        # text fallback header
        c.setFillColor(colors.HexColor(PETROL))
        c.setFont('Helvetica-Bold', 16)
        c.drawString(20 * mm, H - 22 * mm, company)
        c.setStrokeColor(colors.HexColor(PETROL)); c.setLineWidth(1.5)
        c.line(20 * mm, H - 26 * mm, W - 20 * mm, H - 26 * mm)
        top_y = H - 34 * mm

    # ---- footer ----
    if footer_img:
        try:
            ir = ImageReader(footer_img)
            iw, ih = ir.getSize()
            fh = W * (ih / float(iw))
            c.drawImage(ir, 0, 0, width=W, height=fh, mask='auto')
            bottom_y = fh + 8 * mm
        except Exception:
            footer_img = None
    if not footer_img:
        c.setFont('Helvetica', 8)
        c.setFillColor(colors.grey)
        c.drawCentredString(W / 2, 12 * mm,
                            f'{company} · Document Ref: {doc_ref} · Developed by Kulmiye')
        bottom_y = 18 * mm

    # ---- watermark (faint centre logo) ----
    if wm_on:
        wm = _faint_logo(0.06)
        if wm:
            try:
                sz = W * 0.55
                cx, cy = W / 2.0, (top_y + bottom_y) / 2.0
                c.drawImage(wm, cx - sz / 2, cy - sz / 2, width=sz, height=sz, mask='auto')
            except Exception:
                pass

    return top_y, bottom_y


# --------------------------------------------------------------------------- #
#  Odoo-style document bodies                                                  #
# --------------------------------------------------------------------------- #
def _status_of(inv):
    bal = inv.balance
    if getattr(inv, 'status', '') == 'Cancelled':
        return ('CANCELLED', '#98a2b3')
    if bal <= 0.005 and (inv.total or 0) > 0:
        return ('PAID', '#1FA66D')
    if (inv.paid or 0) > 0 or getattr(inv, 'credits', 0):
        return ('PARTIALLY PAID', '#E45424')
    return ('UNPAID', '#C0392B')


def invoice_pdf(inv, company='Modern Diagnostic Center', currency='$'):
    """Hospital-style branded invoice PDF (Name/ID/Dr + status badge + meta row +
    ruled items + boxed totals), or None if reportlab is missing."""
    if not available():
        return None
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas

    def money(n):
        n = float(n or 0); s = f"{abs(n):,.2f}"
        return f"({currency}{s})" if n < 0 else f"{currency}{s}"

    def dmy(iso):
        try:
            y, m, d = str(iso)[:10].split('-'); return f"{d}/{m}/{y}"
        except Exception:
            return str(iso or '-')

    ref = f'INV-{inv.id:04d}'
    PET = colors.HexColor(PETROL); INK = colors.HexColor('#1F2933'); MUT = colors.HexColor('#6B7681')
    NAVY = colors.HexColor('#0F2A44'); LINE = colors.HexColor('#D7DEE6'); GRID = colors.HexColor('#B9C4D0')
    p = inv.patient

    cashier = None; paid_on = inv.date
    try:
        from ..models import PayReceipt
        rcs = PayReceipt.query.filter_by(invoice_id=inv.id).order_by(PayReceipt.id.desc()).all()
        if rcs:
            cashier = rcs[0].cashier; paid_on = rcs[0].date or inv.date
    except Exception:
        pass

    buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4); W, H = A4
    top_y, bottom_y = _draw_letterhead(c, W, H, company, ref)
    L = 16 * mm; R = W - 16 * mm; y = top_y
    cx = L + (R - L) * 0.56

    # Barcode at the TOP-RIGHT (like the vendor bill) — QR goes at the bottom.
    bw_ = 46 * mm; bh_ = 11 * mm
    if _draw_barcode(c, ref, R - bw_, top_y - bh_ + 2, bw_, bh_):
        c.setFont('Helvetica', 8); c.setFillColor(MUT)
        c.drawRightString(R, top_y - bh_ - 6, ref)
        y = top_y - bh_ - 16   # push the content below the barcode

    def lbl(x, yy, label, value):
        c.setFont('Helvetica-Bold', 10.5); c.setFillColor(INK); c.drawString(x, yy, label)
        lw = c.stringWidth(label, 'Helvetica-Bold', 10.5)
        c.setFillColor(NAVY); c.drawString(x + lw + 4, yy, str(value))

    lbl(L, y, 'Name: ', (p.name if p else 'Walk-in'))
    ageg = (f"{p.gender or '-'} / {p.age} Year" if (p and p.age is not None) else ((p.gender if p else '-') or '-'))
    lbl(cx, y, 'Gender/Age: ', ageg)
    y -= 19
    lbl(L, y, 'Patient ID: ', (p.mrn if p and p.mrn else '-'))
    st, stc = _status_of(inv)
    c.setFont('Helvetica-Bold', 10.5); c.setFillColor(INK); c.drawString(cx, y, 'Payment Status: ')
    pw0 = c.stringWidth('Payment Status: ', 'Helvetica-Bold', 10.5)
    bw = c.stringWidth(st, 'Helvetica-Bold', 9) + 14
    c.setFillColor(colors.HexColor(stc)); c.roundRect(cx + pw0, y - 3, bw, 15, 3, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont('Helvetica-Bold', 9); c.drawCentredString(cx + pw0 + bw / 2, y + 1, st)
    y -= 19
    lbl(L, y, 'Dr. Name: ', (inv.doctor_ref.name if inv.doctor_ref else '-'))
    y -= 21
    c.setFont('Helvetica', 15); c.setFillColor(MUT); c.drawString(L, y, f'Invoice {ref}')
    y -= 24

    cols = [('Invoice Date:', dmy(inv.date)),
            ('Reference:', (f'REF-{inv.referral_id:04d}' if getattr(inv, 'referral_id', None) else ref)),
            ('Mobile No:', (p.phone if p and getattr(p, 'phone', None) else '-')),
            ('R. User:', cashier or '-')]
    cw = (R - L) / 4.0
    for i, (lb, vl) in enumerate(cols):
        x = L + i * cw
        c.setFont('Helvetica-Bold', 10); c.setFillColor(INK); c.drawString(x, y, lb)
        c.setFont('Helvetica-Bold', 10.5); c.setFillColor(NAVY); c.drawString(x, y - 15, str(vl))
    y -= 36

    rowh = 18
    xQty = L + (R - L) * 0.50; xPrice = L + (R - L) * 0.66; xAmt = L + (R - L) * 0.82
    table_top = y

    def thead(yy):
        c.setFillColor(colors.HexColor('#F3F6FA')); c.setStrokeColor(GRID); c.setLineWidth(0.8)
        c.rect(L, yy - rowh, R - L, rowh, fill=1, stroke=1)
        c.setFillColor(colors.HexColor('#37506A')); c.setFont('Helvetica-Bold', 9)
        c.drawString(L + 5, yy - rowh + 6, 'DESCRIPTION')
        c.drawCentredString((xQty + xPrice) / 2, yy - rowh + 6, 'QUANTITY')
        c.drawCentredString((xPrice + xAmt) / 2, yy - rowh + 6, 'UNIT PRICE')
        c.drawRightString(R - 6, yy - rowh + 6, 'AMOUNT')
        for vx in (xQty, xPrice, xAmt):
            c.line(vx, yy - rowh, vx, yy)
        return yy - rowh

    y = thead(y); c.setFont('Helvetica', 9.5)
    for it in inv.items:
        if y < bottom_y + 62 * mm:
            c.setStrokeColor(GRID); c.setLineWidth(0.8); c.rect(L, y, R - L, table_top - y, fill=0, stroke=1)
            for vx in (xQty, xPrice, xAmt):
                c.line(vx, y, vx, table_top - rowh)
            c.showPage(); top_y, bottom_y = _draw_letterhead(c, W, H, company, ref)
            y = top_y; table_top = y; y = thead(y); c.setFont('Helvetica', 9.5)
        c.setFillColor(INK)
        c.drawString(L + 5, y - rowh + 6, (it.desc or '')[:46])
        c.drawCentredString((xQty + xPrice) / 2, y - rowh + 6, f'{(it.qty or 0):.5f}')
        c.drawCentredString((xPrice + xAmt) / 2, y - rowh + 6, f'{(it.price or 0):.5f}')
        c.drawRightString(R - 6, y - rowh + 6, money((it.qty or 0) * (it.price or 0)))
        c.setStrokeColor(GRID); c.setLineWidth(0.8); c.line(L, y - rowh, R, y - rowh)
        for vx in (xQty, xPrice, xAmt):
            c.line(vx, y - rowh, vx, y)
        y -= rowh
    c.setStrokeColor(GRID); c.setLineWidth(0.8); c.rect(L, y, R - L, table_top - y, fill=0, stroke=1)
    for vx in (xQty, xPrice, xAmt):
        c.line(vx, y, vx, table_top - rowh)

    disc = (inv.discount or 0) + (inv.subtotal * (getattr(inv, 'discount_pct', 0) or 0) / 100.0)
    ty = y - 16; bx = R - 68 * mm; box_top = ty + 4

    def trow(label, val, fill=None, tcol=None, bold=False, h=15):
        nonlocal ty
        if fill:
            c.setFillColor(fill); c.rect(bx, ty - h + 4, R - bx, h, fill=1, stroke=0)
        # full ruled line under every totals row (matches the print view)
        c.setStrokeColor(GRID); c.setLineWidth(0.7); c.line(bx, ty - h + 4, R, ty - h + 4)
        c.setFont('Helvetica-Bold' if bold else 'Helvetica', 9.5)
        c.setFillColor(tcol or (INK if bold else MUT)); c.drawString(bx + 6, ty - h + 7, label)
        c.setFillColor(tcol or INK); c.drawRightString(R - 6, ty - h + 7, money(val))
        ty -= h

    trow('Subtotal', inv.subtotal)
    trow('Total', inv.subtotal, fill=colors.HexColor('#3F5B7A'), tcol=colors.white, bold=True)
    trow(f'Paid on {dmy(paid_on)}', inv.paid or 0)
    trow('Amount Due', inv.balance)
    if disc > 0.005:
        trow('Discount', disc)
    if (inv.vat or 0) > 0.005:
        trow('Tax / VAT', inv.vat or 0)
    trow('Net Total', inv.total, fill=colors.HexColor('#37506A'), tcol=colors.white, bold=True)
    c.setStrokeColor(GRID); c.setLineWidth(0.9); c.rect(bx, ty + 4, R - bx, box_top - (ty + 4), fill=0, stroke=1)

    # QR at the BOTTOM-RIGHT (the barcode is at the top-right). This matches the
    # vendor-bill layout — barcode up, QR down.
    _sy = min(ty - 12, y - 16)
    _payload = f"{company} | {ref} | {(p.name if p else 'Walk-in')} | Total {money(inv.total)} | {dmy(inv.date)}"
    _qr = _qr_png(_payload)
    if _qr is not None:
        qs = 26 * mm
        c.drawImage(_qr, R - qs, _sy - qs, qs, qs, mask='auto')
        c.setFont('Helvetica', 7.5); c.setFillColor(MUT)
        c.drawRightString(R, _sy - qs - 9, 'Scan to verify / Xaqiiji')
    c.setFont('Helvetica', 9); c.setFillColor(MUT)
    c.drawString(L, _sy - 12 * mm, f'Please use the following communication for your payment : {ref}')

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()





def receipt_pdf(r, company='Modern Diagnostic Center', currency='$'):
    """Odoo-style branded payment receipt PDF, or None if reportlab is missing."""
    if not available():
        return None
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas

    def money(n):
        n = float(n or 0)
        s = f"{abs(n):,.2f}"
        return f"({currency}{s})" if n < 0 else f"{currency}{s}"

    inv = r.invoice
    p = inv.patient if inv else None
    ref = f'RCT-{r.id:05d}'
    PET = colors.HexColor(PETROL)
    INK = colors.HexColor('#1F2933')
    MUT = colors.HexColor('#6B7681')
    LINE = colors.HexColor('#E3E8EE')
    ZEB = colors.HexColor('#F6F8FA')

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    W, H = A5
    top_y, bottom_y = _draw_letterhead(c, W, H, company, ref)
    L = 13 * mm
    R = W - 13 * mm
    y = top_y

    # title + green PAID-style pill
    c.setFillColor(PET); c.setFont('Helvetica-Bold', 15)
    c.drawString(L, y - 2, 'Payment Receipt')
    c.setFont('Helvetica-Bold', 8)
    tag = 'RECEIVED'
    pw = c.stringWidth(tag, 'Helvetica-Bold', 8) + 14
    c.setFillColor(colors.HexColor('#1FA66D')); c.roundRect(R - pw, y - 5, pw, 14, 7, fill=1, stroke=0)
    c.setFillColor(colors.white); c.drawCentredString(R - pw / 2, y - 1, tag)

    # received-from + meta
    y -= 26
    c.setFont('Helvetica', 7.5); c.setFillColor(MUT); c.drawString(L, y, 'RECEIVED FROM')
    c.setFont('Helvetica-Bold', 10.5); c.setFillColor(INK); c.drawString(L, y - 13, (p.name if p else 'Walk-in'))
    if p and p.mrn:
        c.setFont('Helvetica', 8); c.setFillColor(MUT); c.drawString(L, y - 24, f'MRN {p.mrn}')
    for i, (lbl, val) in enumerate([('Receipt No', ref), ('Date', str(r.date or '—')),
                                    ('Invoice', f'INV-{inv.id:04d}' if inv else '—')]):
        yy = y - i * 12
        c.setFont('Helvetica', 7.5); c.setFillColor(MUT); c.drawRightString(R - 30 * mm, yy, lbl.upper())
        c.setFont('Helvetica-Bold', 8.5); c.setFillColor(INK); c.drawRightString(R, yy, str(val))

    # items (ruled table)
    y -= 40
    rowh = 15
    xAmt = R - 30 * mm           # divider between Description and Amount
    r_top = y
    c.setFillColor(PET); c.rect(L, y - rowh, R - L, rowh, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont('Helvetica-Bold', 8)
    c.drawString(L + 5, y - rowh + 5, 'DESCRIPTION')
    c.drawRightString(R - 5, y - rowh + 5, 'AMOUNT')
    y -= rowh
    n = 0
    for it in (inv.items if inv else []):
        if y < bottom_y + 42 * mm:
            c.setStrokeColor(colors.HexColor('#C9D2DC')); c.setLineWidth(0.8)
            c.rect(L, y, R - L, r_top - y, fill=0, stroke=1); c.line(xAmt, y, xAmt, r_top - rowh)
            c.showPage(); top_y, bottom_y = _draw_letterhead(c, W, H, company, ref); y = top_y; r_top = y
            c.setFillColor(PET); c.rect(L, y - rowh, R - L, rowh, fill=1, stroke=0)
            c.setFillColor(colors.white); c.setFont('Helvetica-Bold', 8)
            c.drawString(L + 5, y - rowh + 5, 'DESCRIPTION'); c.drawRightString(R - 5, y - rowh + 5, 'AMOUNT')
            y -= rowh
        if n % 2:
            c.setFillColor(ZEB); c.rect(L, y - rowh, R - L, rowh, fill=1, stroke=0)
        c.setFillColor(INK); c.setFont('Helvetica', 9)
        c.drawString(L + 5, y - rowh + 5, (it.desc or '')[:40])
        c.drawRightString(R - 5, y - rowh + 5, money((it.qty or 0) * (it.price or 0)))
        c.setStrokeColor(colors.HexColor('#C9D2DC')); c.setLineWidth(0.8); c.line(L, y - rowh, R, y - rowh)
        y -= rowh; n += 1
    # outer border + column divider
    c.setStrokeColor(colors.HexColor('#C9D2DC')); c.setLineWidth(0.8)
    c.rect(L, y, R - L, r_top - y, fill=0, stroke=1)
    c.setStrokeColor(colors.HexColor('#C9D2DC')); c.setLineWidth(0.8); c.line(xAmt, y, xAmt, r_top - rowh)

    # totals
    ty = y - 10
    bx = R - 64 * mm
    _tbox_top = ty + 4
    def trow(label, val, bold=False, fill=None, white=False, big=False):
        nonlocal ty
        hh = 16 if big else 13
        if fill:
            c.setFillColor(fill); c.rect(bx, ty - hh + 4, R - bx, hh, fill=1, stroke=0)
        c.setStrokeColor(colors.HexColor('#C9D2DC')); c.setLineWidth(0.7); c.line(bx, ty - hh + 4, R, ty - hh + 4)
        c.setFont('Helvetica-Bold' if bold else 'Helvetica', 11 if big else (9.5 if bold else 9))
        c.setFillColor(colors.white if white else (INK if bold else MUT))
        c.drawString(bx + 6, ty - hh + 8, label)
        c.setFillColor(colors.white if white else INK)
        c.drawRightString(R - 6, ty - hh + 8, money(val))
        ty -= hh
    if inv:
        trow('Invoice Total', inv.total)
    trow(f'Paid Now ({r.method or "Cash"})', r.amount, bold=True, fill=colors.HexColor('#1FA66D'), white=True, big=True)
    if inv:
        trow('Total Paid to Date', inv.paid or 0)
        due = inv.balance
        trow('Balance', due, bold=True, fill=colors.HexColor('#FDECEC' if due > 0.005 else '#EAF3EC'))
    # box border around the totals block
    c.setStrokeColor(colors.HexColor('#C9D2DC')); c.setLineWidth(0.9)
    c.rect(bx, ty + 4, R - bx, _tbox_top - (ty + 4), fill=0, stroke=1)

    ty -= 16
    c.setFont('Helvetica', 8); c.setFillColor(MUT)
    _foot = f'Received by (Cashier): {getattr(r, "cashier", None) or "—"}'
    if getattr(r, 'ref', None):
        _foot += f'     ·     Payment Ref: {r.ref}'
    c.drawString(L, ty, _foot)

    # scan code: verification QR + Code128 barcode of the receipt no
    _sy = ty - 16
    _qr = _qr_png(f"{company} | {ref} | {money(getattr(r, 'amount', 0) or 0)}")
    _bx0 = L
    if _qr is not None:
        qs = 24 * mm
        c.drawImage(_qr, L, _sy - qs, qs, qs, mask='auto')
        c.setFont('Helvetica', 7.5); c.setFillColor(MUT)
        c.drawCentredString(L + qs / 2, _sy - qs - 9, 'Scan to verify / Xaqiiji')
        _bx0 = L + qs + 10 * mm
    bw = 50 * mm; bh = 12 * mm
    if _draw_barcode(c, ref, _bx0, _sy - 6 - bh, bw, bh):
        c.setFont('Helvetica-Bold', 9); c.setFillColor(colors.HexColor('#1F2933'))
        c.drawString(_bx0, _sy - 10 - bh - 10, ref)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def lab_result_pdf(o, company='Modern Diagnostic Center', currency='$'):
    """Branded, clean Laboratory Result report PDF for a LabOrder, or None if reportlab is missing."""
    if not available():
        return None
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas

    ref = f'LAB-{o.id:04d}'
    PET = colors.HexColor(PETROL)
    INK = colors.HexColor('#1F2933'); MUT = colors.HexColor('#6B7681')
    LINE = colors.HexColor('#E3E8EE'); ZEB = colors.HexColor('#F6F8FA')
    RED = colors.HexColor('#C0392B'); AMBER = colors.HexColor('#B45309')
    GRID = colors.HexColor('#C9D2DC')

    p = o.patient
    vals = list(getattr(o, 'values', []) or [])
    try:
        from .helpers import setting as _st
    except Exception:
        def _st(k, d=''): return d

    buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4); W, H = A4
    top_y, bottom_y = _draw_letterhead(c, W, H, company, ref)
    L = 18 * mm; R = W - 18 * mm; y = top_y

    # title + status pill
    c.setFillColor(PET); c.setFont('Helvetica-Bold', 20)
    c.drawString(L, y - 4, 'Laboratory Report')
    stmap = {'Approved': ('APPROVED', '#1FA66D'), 'Resulted': ('RESULTED', '#E45424'),
             'Received': ('IN PROCESS', '#6B7681'), 'Collected': ('COLLECTED', '#6B7681')}
    st, stc = stmap.get(o.status, (o.status or '—', '#6B7681'))
    c.setFont('Helvetica-Bold', 9)
    pw = c.stringWidth(st, 'Helvetica-Bold', 9) + 16
    c.setFillColor(colors.HexColor(stc)); c.roundRect(R - pw, y - 6, pw, 15, 7, fill=1, stroke=0)
    c.setFillColor(colors.white); c.drawCentredString(R - pw / 2, y - 2, st)

    # patient (left) + meta (right)
    y -= 30
    c.setFont('Helvetica', 8); c.setFillColor(MUT); c.drawString(L, y, 'PATIENT')
    c.setFont('Helvetica-Bold', 12); c.setFillColor(INK)
    c.drawString(L, y - 14, (p.name if p else '—'))
    sub = []
    if p and p.mrn: sub.append(f'MRN {p.mrn}')
    if p and getattr(p, 'gender', None): sub.append(p.gender)
    if p and getattr(p, 'age', None) is not None: sub.append(f'{p.age} yrs')
    c.setFont('Helvetica', 9); c.setFillColor(MUT)
    if sub: c.drawString(L, y - 27, '   ·   '.join(str(s) for s in sub))

    meta = [('Report No', ref), ('Date', str(o.date or '—')), ('Test', (o.service.name if o.service else '—'))]
    if o.sample_no: meta.append(('Sample', f'{o.sample_no} · {o.specimen or "—"}'))
    my = y
    for lbl, val in meta:
        c.setFont('Helvetica', 7.5); c.setFillColor(MUT); c.drawRightString(R - 52 * mm, my, lbl.upper())
        c.setFont('Helvetica-Bold', 9); c.setFillColor(INK); c.drawRightString(R, my, str(val)[:36])
        my -= 13

    # panic banner
    y = min(y - 40, my - 10)
    if getattr(o, 'panic', None):
        c.setFillColor(colors.HexColor('#FDECEC')); c.roundRect(L, y - 16, R - L, 18, 4, fill=1, stroke=0)
        c.setStrokeColor(RED); c.setLineWidth(1); c.roundRect(L, y - 16, R - L, 18, 4, fill=0, stroke=1)
        c.setFillColor(RED); c.setFont('Helvetica-Bold', 9.5)
        c.drawString(L + 8, y - 11, '\u26a0  CRITICAL / PANIC VALUE — clinician notified')
        y -= 26

    if vals:
        # ruled results table: Parameter | Result | Unit | Reference | Flag
        flagW = 16 * mm; refW = 34 * mm; unitW = 20 * mm; resW = 26 * mm
        xRes = L + (R - L - flagW - refW - unitW - resW)
        xUnit = xRes + resW; xRef = xUnit + unitW; xFlag = xRef + refW
        rowh = 15; pad = 4; ttop = y
        c.setFillColor(PET); c.rect(L, y - rowh, R - L, rowh, fill=1, stroke=0)
        c.setFillColor(colors.white); c.setFont('Helvetica-Bold', 8)
        c.drawString(L + 5, y - rowh + 5, 'PARAMETER')
        c.drawString(xRes + pad, y - rowh + 5, 'RESULT')
        c.drawString(xUnit + pad, y - rowh + 5, 'UNIT')
        c.drawString(xRef + pad, y - rowh + 5, 'REFERENCE')
        c.drawCentredString((xFlag + R) / 2, y - rowh + 5, 'FLAG')
        y -= rowh
        i = 0
        for v in vals:
            if y < bottom_y + 55 * mm:
                c.setStrokeColor(GRID); c.setLineWidth(0.8); c.rect(L, y, R - L, ttop - y, fill=0, stroke=1)
                c.showPage(); top_y, bottom_y = _draw_letterhead(c, W, H, company, ref); y = top_y; ttop = y
                c.setFillColor(PET); c.rect(L, y - rowh, R - L, rowh, fill=1, stroke=0)
                c.setFillColor(colors.white); c.setFont('Helvetica-Bold', 8)
                c.drawString(L + 5, y - rowh + 5, 'PARAMETER'); c.drawString(xRes + pad, y - rowh + 5, 'RESULT')
                c.drawString(xUnit + pad, y - rowh + 5, 'UNIT'); c.drawString(xRef + pad, y - rowh + 5, 'REFERENCE')
                c.drawCentredString((xFlag + R) / 2, y - rowh + 5, 'FLAG'); y -= rowh
            if i % 2:
                c.setFillColor(ZEB); c.rect(L, y - rowh, R - L, rowh, fill=1, stroke=0)
            fl = (v.flag or '').strip()
            abn = fl in ('H', 'L', 'HH', 'LL', 'A')
            crit = fl in ('HH', 'LL')
            c.setFillColor(INK); c.setFont('Helvetica', 9)
            c.drawString(L + 5, y - rowh + 5, (v.name or '')[:34])
            c.setFont('Helvetica-Bold' if abn else 'Helvetica', 9)
            c.setFillColor(RED if crit else (AMBER if abn else INK))
            c.drawString(xRes + pad, y - rowh + 5, str(v.value or ''))
            c.setFillColor(INK); c.setFont('Helvetica', 9)
            c.drawString(xUnit + pad, y - rowh + 5, (v.unit or '')[:10])
            if v.ref_low is not None and v.ref_high is not None:
                reftxt = f'{v.ref_low:g} – {v.ref_high:g}'
            else:
                reftxt = v.ref_text or '—'
            c.drawString(xRef + pad, y - rowh + 5, reftxt[:20])
            if fl:
                c.setFillColor(RED if crit else AMBER); c.setFont('Helvetica-Bold', 9)
                c.drawCentredString((xFlag + R) / 2, y - rowh + 5, fl)
            c.setStrokeColor(colors.HexColor("#C9D2DC")); c.setLineWidth(0.8); c.line(L, y - rowh, R, y - rowh)
            y -= rowh; i += 1
        c.setStrokeColor(GRID); c.setLineWidth(0.8); c.rect(L, y, R - L, ttop - y, fill=0, stroke=1)
        for vx in (xRes, xUnit, xRef, xFlag):
            c.setStrokeColor(colors.HexColor("#C9D2DC")); c.setLineWidth(0.8); c.line(vx, y, vx, ttop - rowh)
    else:
        # free-text result box
        c.setFont('Helvetica-Bold', 9); c.setFillColor(MUT); c.drawString(L, y, 'RESULT')
        y -= 6
        c.setStrokeColor(GRID); c.setLineWidth(0.8)
        txt = (o.result or '—')
        import textwrap
        lines = []
        for para in txt.split('\n'):
            lines.extend(textwrap.wrap(para, 96) or [''])
        boxh = max(20, 12 * len(lines) + 12)
        c.rect(L, y - boxh, R - L, boxh, fill=0, stroke=1)
        c.setFillColor(INK); c.setFont('Helvetica', 9)
        ty = y - 14
        for ln in lines:
            c.drawString(L + 6, ty, ln); ty -= 12
        y -= boxh
        sr = o.service
        if sr and (getattr(sr, 'ref_range', None) or getattr(sr, 'unit', None)):
            c.setFont('Helvetica', 8); c.setFillColor(MUT)
            c.drawString(L, y - 12, f'Reference Range: {sr.ref_range or "—"}{(" " + sr.unit) if sr.unit else ""}')
            y -= 12

    # signatures
    y -= 30
    c.setStrokeColor(LINE); c.setLineWidth(0.6)
    c.line(L, y, L + 60 * mm, y); c.line(R - 60 * mm, y, R, y)
    c.setFont('Helvetica-Bold', 9); c.setFillColor(INK)
    c.drawString(L, y - 12, o.result_by or '—')
    c.drawRightString(R, y - 12, o.approved_by or '—')
    c.setFont('Helvetica', 7.5); c.setFillColor(MUT)
    c.drawString(L, y - 22, 'Performed by (Lab Technician)')
    c.drawRightString(R, y - 22, 'Verified & Approved (Authorized Signatory)')

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()


def financial_statement_pdf(data, company='Modern Diagnostic Center', currency='$'):
    """Branded PDF of a financial statement (P&L / Cash Book / Balance Sheet / Trial Balance).
    `data` from accounting.finance_report_rows(): {title, plabel, kind:'stmt'|'tb', ...}."""
    if not available():
        return None
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
    PET = colors.HexColor(PETROL); INK = colors.HexColor('#1F2933'); MUT = colors.HexColor('#6B7681')
    LINE = colors.HexColor('#E3E8EE'); GRID = colors.HexColor('#C9D2DC')
    RED = colors.HexColor('#C0392B'); GRN = colors.HexColor('#1FA66D')
    ref = data.get('title', 'Statement')
    buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4); W, H = A4
    top_y, bottom_y = _draw_letterhead(c, W, H, company, ref)
    L = 18 * mm; Rx = W - 18 * mm; y = top_y

    c.setFillColor(PET); c.setFont('Helvetica-Bold', 20); c.drawString(L, y - 4, str(data.get('title', 'Financial Statement')))
    y -= 20
    c.setFont('Helvetica', 10); c.setFillColor(MUT); c.drawString(L, y, str(data.get('plabel', '')))
    y -= 24

    def page_break(yy):
        nonlocal top_y, bottom_y
        if yy < bottom_y + 30 * mm:
            c.showPage(); top_y, bottom_y = _draw_letterhead(c, W, H, company, ref); return top_y
        return yy

    if data.get('kind') == 'tb':
        dcol = Rx - 40 * mm       # right edge of Debit column
        c.setFillColor(PET); c.rect(L, y - 5, Rx - L, 18, fill=1, stroke=0)
        c.setFillColor(colors.white); c.setFont('Helvetica-Bold', 8.5)
        c.drawString(L + 6, y, 'ACCOUNT'); c.drawRightString(dcol, y, 'DEBIT'); c.drawRightString(Rx - 4, y, 'CREDIT')
        y -= 20
        c.setFont('Helvetica', 9.5)
        for name, dr, cr in data.get('tb', []):
            y = page_break(y)
            c.setFillColor(INK); c.drawString(L + 6, y, str(name)[:58])
            c.drawRightString(dcol, y, dr or '—'); c.drawRightString(Rx - 4, y, cr or '—')
            c.setStrokeColor(LINE); c.setLineWidth(0.3); c.line(L, y - 5, Rx, y - 5)
            y -= 16
        c.setStrokeColor(GRID); c.setLineWidth(0.9); c.line(L, y + 9, Rx, y + 9)
        c.setFont('Helvetica-Bold', 10); c.setFillColor(INK)
        c.drawString(L + 6, y, 'TOTAL'); c.drawRightString(dcol, y, data.get('td_disp', '')); c.drawRightString(Rx - 4, y, data.get('tc_disp', ''))
        y -= 24
        bal = abs(data.get('chk', 0)) <= 0.5
        c.setFillColor(colors.HexColor('#EAF3EC') if bal else colors.HexColor('#FDECEC'))
        c.roundRect(L, y - 7, Rx - L, 22, 4, fill=1, stroke=0)
        c.setFillColor(GRN if bal else RED); c.setFont('Helvetica-Bold', 10)
        c.drawString(L + 8, y, 'Debits = Credits' if bal else 'Out of balance')
        c.drawRightString(Rx - 8, y, data.get('chk_disp', ''))
    else:
        colW = Rx - L
        for kind, label, val, disp in data.get('rows', []):
            y = page_break(y)
            if kind == 'sec':
                y -= 5
                c.setFillColor(PET); c.setFont('Helvetica-Bold', 9.5); c.drawString(L, y, str(label).upper()); y -= 16
            elif kind == 'grand':
                y -= 3
                c.setFillColor(PET); c.roundRect(L, y - 8, colW, 24, 4, fill=1, stroke=0)
                c.setFillColor(colors.white); c.setFont('Helvetica-Bold', 12.5); c.drawString(L + 10, y, str(label))
                c.setFillColor(colors.HexColor('#FFC4B8') if val < 0 else colors.white)
                c.drawRightString(Rx - 10, y, disp); y -= 30
            elif kind == 'tot':
                c.setStrokeColor(GRID); c.setLineWidth(0.8); c.line(L, y + 12, Rx, y + 12)
                c.setFont('Helvetica-Bold', 10.5); c.setFillColor(INK); c.drawString(L, y, str(label))
                c.setFillColor(RED if val < 0 else INK); c.drawRightString(Rx, y, disp); y -= 19
            else:
                c.setFont('Helvetica', 10.5); c.setFillColor(INK); c.drawString(L + 4, y, str(label))
                c.setFillColor(RED if val < 0 else INK); c.drawRightString(Rx, y, disp); y -= 16

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()


def ledger_pdf(title, period, columns, rows, totals=None,
               company='Modern Diagnostic Center', currency='$'):
    """Generic branded table PDF for tabular reports (General Ledger, Trial Balance, …).
    columns = [(header, align 'l'|'r', width_mm), …]; rows = [[cell,…], …]; totals = [cell,…] or None."""
    if not available():
        return None
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
    PET = colors.HexColor(PETROL); INK = colors.HexColor('#1F2933'); MUT = colors.HexColor('#6B7681')
    LINE = colors.HexColor('#E8ECF1'); GRID = colors.HexColor('#C9D2DC')
    ncols = len(columns)
    wide = sum(w for _, _, w in columns) > 165
    pagesize = landscape(A4) if wide else A4
    buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=pagesize); W, H = pagesize
    top_y, bottom_y = _draw_letterhead(c, W, H, company, title)
    L = 16 * mm; Rx = W - 16 * mm
    total_w = sum(w for _, _, w in columns)
    scale = (Rx - L) / (total_w * mm) if total_w * mm > (Rx - L) else 1.0
    xs = []; x = L
    for _, _, w in columns:
        xs.append(x); x += w * mm * scale
    edges = xs + [Rx]

    def draw_header(yy):
        c.setFillColor(PET); c.rect(L, yy - 5, Rx - L, 17, fill=1, stroke=0)
        c.setFillColor(colors.white); c.setFont('Helvetica-Bold', 8)
        for i, (hdr, align, _) in enumerate(columns):
            if align == 'r':
                c.drawRightString(edges[i + 1] - 3, yy, str(hdr).upper())
            else:
                c.drawString(xs[i] + 3, yy, str(hdr).upper())
        return yy - 18

    y = top_y
    c.setFillColor(PET); c.setFont('Helvetica-Bold', 18); c.drawString(L, y - 2, str(title)); y -= 18
    if period:
        c.setFont('Helvetica', 9.5); c.setFillColor(MUT); c.drawString(L, y, str(period)); y -= 16
    y = draw_header(y)
    c.setFont('Helvetica', 8.5)
    for row in rows:
        if y < bottom_y + 26 * mm:
            c.showPage(); top_y, bottom_y = _draw_letterhead(c, W, H, company, title)
            y = draw_header(top_y); c.setFont('Helvetica', 8.5)
        c.setFillColor(INK)
        for i, (_, align, _w) in enumerate(columns):
            cell = str(row[i]) if i < len(row) and row[i] is not None else ''
            if align == 'r':
                c.drawRightString(edges[i + 1] - 3, y, cell)
            else:
                maxchars = int((edges[i + 1] - xs[i]) / 4.6)
                c.drawString(xs[i] + 3, y, cell[:maxchars])
        c.setStrokeColor(LINE); c.setLineWidth(0.3); c.line(L, y - 4, Rx, y - 4)
        y -= 14
    if totals:
        c.setStrokeColor(GRID); c.setLineWidth(0.9); c.line(L, y + 9, Rx, y + 9)
        c.setFont('Helvetica-Bold', 9); c.setFillColor(INK)
        for i, (_, align, _w) in enumerate(columns):
            cell = str(totals[i]) if i < len(totals) and totals[i] is not None else ''
            if align == 'r':
                c.drawRightString(edges[i + 1] - 3, y, cell)
            else:
                c.drawString(xs[i] + 3, y, cell)
    c.showPage(); c.save(); buf.seek(0)
    return buf.read()
