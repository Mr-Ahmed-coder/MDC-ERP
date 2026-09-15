"""Printable A4 document shell.

Header logo, footer, watermark, Code-128 barcode, verification QR code,
print date/time and printed-by line — all driven by System Settings.
"""
import datetime as dt
from flask import request
from markupsafe import escape as h
from .security import setting, doc_sig, cur_user
from .helpers import today
from .barcodes import qr_svg, code128_svg


def _sig_block(signature, doc_ref=None):
    """Professional digital-signature block. `signature` may be a name string or a
    dict {name,title,date}. Ties the signer to the document's verification ref."""
    if not signature:
        return ''
    if isinstance(signature, str):
        signature = {'name': signature}
    name = h(signature.get('name') or '—')
    title = h(signature.get('title') or '')
    date = h(signature.get('date') or dt.datetime.now().strftime('%d-%b-%Y %H:%M'))
    verified = (f"Verified ✓ · ref {h(doc_ref)}" if doc_ref else "Verified ✓")
    return (
        "<div style='margin-top:26px;display:flex;justify-content:flex-end'>"
        "<div style='border:1px solid #d8e0e2;border-radius:10px;padding:12px 16px;min-width:250px;background:#fbfdfd'>"
        "<div style='font-size:10px;color:#7a8a90;letter-spacing:1.5px;text-transform:uppercase'>🔏 Digitally signed by</div>"
        f"<div style='font-size:15px;font-weight:700;color:#103D46;font-family:\"Space Grotesk\"'>{name}</div>"
        + (f"<div style='font-size:11.5px;color:#666'>{title}</div>" if title else '')
        + f"<div style='font-size:10.5px;color:#999;margin-top:5px'>{date} · {verified}</div>"
        "</div></div>")


def printable(title, body, doc_ref=None, barcode_text=None, signature=None):
    company=h(setting('company','Modern Diagnostic Center'))
    logo=(setting('logo','') or '').strip()
    wm_logo=(setting('logo','') or '').strip() or '/static/brand/mdc-logo.png'
    header=setting('print_header','') if setting('ph_on','1')=='1' else ''
    footer=setting('print_footer','') if setting('pf_on','1')=='1' else ''
    wm_txt=h(setting('wm_text','') or '') or company
    wm_on=setting('wm_on','1')=='1'
    paper=setting('paper','A4') or 'A4'; brand=(setting('brand','') or '').strip() or '#103D46'
    logo_html=f'<img src="{h(logo)}" style="height:52px;object-fit:contain">' if logo else ''
    header_html=f'<div style="text-align:center;color:#555;font-size:12px;margin:2px 0 10px">{h(header)}</div>' if header else ''
    footer_html=f'<div class="ft">{h(footer)}</div>' if footer else ''
    # --- Phase 2: barcode (top-right) + verification QR + print meta -------
    # QR code + barcode restored. Barcode renders top-right, QR bottom — matching
    # the vendor-bill layout. Print-meta footer and action buttons stay removed.
    bc_html = ''
    if barcode_text:
        bc_html = f"<div style='text-align:right;margin:-4px 0 6px'>{code128_svg(barcode_text)}<div style='font-size:10px;color:#777;letter-spacing:2px'>{h(barcode_text)}</div></div>"
    qr_html = ''
    if doc_ref:
        vurl = request.host_url.rstrip('/') + f"/verify?ref={doc_ref}&sig={doc_sig(doc_ref)}"
        qr_html = (f"<div style='display:flex;justify-content:space-between;align-items:flex-end;margin-top:18px'>"
                   f"<div style='font-size:10.5px;color:#888'>Document Ref: <b>{h(doc_ref)}</b><br>"
                   f"Scan QR si aad u xaqiijiso / scan to verify authenticity</div>{qr_svg(vurl)}</div>")
    u = cur_user()
    meta_html = (f"<div style='margin-top:8px;text-align:center;color:#999;font-size:10.5px'>"
                 f"Printed {dt.datetime.now().strftime('%d-%b-%Y %H:%M')}"
                 f"{(' · by ' + h(u.name or u.username)) if u else ''}</div>")
    # --- branded contact header/footer from company settings ---
    _addr = h(setting('company_address', '') or '')
    _phone = h(setting('company_phone', '') or '')
    _email = h(setting('company_email', '') or '')
    _web = h(setting('company_web', '') or '')
    _arabic = h(setting('company_arabic', '') or '')
    contact_bits = ' · '.join(x for x in [_addr, _phone, _email, _web] if x)
    brand_header = ''
    if _arabic or contact_bits:
        brand_header = (f"<div style='text-align:center;margin:-4px 0 8px'>"
                        f"{f'<div style=font-size:15px;color:#555;font-weight:600>{_arabic}</div>' if _arabic else ''}"
                        f"{f'<div style=font-size:11px;color:#777>{contact_bits}</div>' if contact_bits else ''}</div>")
    brand_footer = ''
    if contact_bits:
        brand_footer = (f"<div style='text-align:center;color:#888;font-size:10.5px;margin-top:4px'>{contact_bits}</div>")
    # --- letterhead: branded header/footer on every printed page -------------
    # On by default. If the user has uploaded custom letterhead artwork
    # (letterhead_header / letterhead_footer settings) we use that image;
    # otherwise we render a crisp HTML letterhead built around the MDC logo
    # and the company contact settings.
    lh_on = setting('letterhead', '1') == '1'
    custom_head = (setting('letterhead_header', '') or '/static/brand/letterhead-header.jpg').strip()
    custom_foot = (setting('letterhead_footer', '') or '/static/brand/letterhead-footer.jpg').strip()
    lh_logo = (setting('logo', '') or '/static/brand/mdc-logo.png').strip()
    _tag = h(setting('company_tagline', '') or 'Diagnostic · Laboratory · Radiology · Consultation')
    _pay = h(setting('receipt_wallets', '') or 'Cash · Sahal · EVC · E. Dahab · MyCash · Premier Wallet · Bank · Card')
    amber = '#E45424'
    lh_top = lh_bot = ''
    if lh_on:
        if custom_head:
            lh_top = (f'<div class="lh-top"><div class="lh-inner">'
                      f'<img src="{h(custom_head)}" alt=""></div></div>')
        else:
            contact_top = ' &nbsp;·&nbsp; '.join(x for x in [_phone, _web] if x)
            lh_top = (
                f'<div class="lh-top"><div class="lh-inner"><div class="lh-hdr">'
                f'<img class="lh-logo" src="{h(lh_logo)}" alt="">'
                f'<div class="lh-co"><div class="lh-name">{company}</div>'
                + (f'<div class="lh-ar">{_arabic}</div>' if _arabic else '')
                + f'<div class="lh-tag">{_tag}</div></div>'
                + (f'<div class="lh-ct">{contact_top}</div>' if contact_top else '')
                + f'</div><div class="lh-bar"></div></div></div>')
        if custom_foot:
            lh_bot = (f'<div class="lh-bot"><div class="lh-inner">'
                      f'<img src="{h(custom_foot)}" alt=""></div></div>')
        else:
            contact_bot = ' &nbsp;·&nbsp; '.join(x for x in [_addr, _phone, _email, _web] if x)
            lh_bot = (
                f'<div class="lh-bot"><div class="lh-inner"><div class="lh-barb"></div>'
                + (f'<div class="lh-ftr">{contact_bot}</div>' if contact_bot else '')
                + f'<div class="lh-pay">Payments accepted: {_pay}</div>'
                + f'</div></div></div>')
        brand_header = ''
        brand_footer = ''
    wide='max-width:760px;margin:20px auto;padding:0 20px' if paper=='A4' else 'max-width:540px;margin:16px auto;padding:0 16px'
    # document title strip used instead of the big company row when letterhead is on
    if lh_on:
        head_block = (f'<div class="doc-head"><div class="doc-t">{h(title)}</div>'
                      f'<div class="doc-d">{today()}</div></div>')
    else:
        head_block = (f'<div class="head"><div class="co">{logo_html}<span>{company}</span></div>'
                      f'<div style="text-align:right">{h(title)}<br><small>{today()}</small></div></div>')
    css = f"""@page{{size:{paper};margin:{'8mm 12mm' if lh_on else '14mm'}}}
    body{{font-family:Inter,system-ui,sans-serif;color:#17272C;position:relative;{wide}}}
    h1,h3{{font-family:'Space Grotesk',sans-serif}}
    .head{{display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid {brand};padding-bottom:12px;margin-bottom:10px}}
    .head .co{{font-size:20px;font-weight:700;color:{brand};display:flex;align-items:center;gap:12px}}
    /* letterhead artwork: fixed so it repeats on every printed page */
    .lh-top,.lh-bot{{position:fixed;left:0;right:0;background:#fff;z-index:2}}
    .lh-top{{top:0}} .lh-bot{{bottom:0}}
    .lh-inner{{max-width:760px;margin:0 auto;padding:0 20px}}
    .lh-inner img{{width:100%;display:block}}
    /* HTML letterhead header */
    .lh-hdr{{display:flex;align-items:center;gap:14px;padding:8px 0 6px}}
    .lh-hdr .lh-logo{{width:auto;height:50px;object-fit:contain;flex:none}}
    .lh-co{{flex:1;line-height:1.15}}
    .lh-name{{font-family:'Space Grotesk',sans-serif;font-size:20px;font-weight:800;color:{brand};letter-spacing:-.2px}}
    .lh-ar{{font-size:13px;color:{amber};font-weight:600;direction:rtl}}
    .lh-tag{{font-size:11px;color:#667;letter-spacing:.3px;text-transform:uppercase}}
    .lh-ct{{text-align:right;font-size:11px;color:#556;line-height:1.5;flex:none}}
    .lh-bar{{height:3px;border-radius:3px;background:linear-gradient(90deg,{brand} 0 62%,{amber} 62% 100%)}}
    /* HTML letterhead footer */
    .lh-barb{{height:2.5px;border-radius:3px;background:linear-gradient(90deg,{amber} 0 38%,{brand} 38% 100%);margin-bottom:5px}}
    .lh-ftr{{text-align:center;font-size:10.5px;color:#556}}
    .lh-pay{{text-align:center;font-size:9.5px;color:#8a97a0;margin-top:2px}}
    .doc-head{{display:flex;justify-content:space-between;align-items:baseline;
      border-bottom:2px solid {brand};padding-bottom:7px;margin-bottom:12px}}
    .doc-t{{font-family:'Space Grotesk',sans-serif;font-size:17px;font-weight:700;color:{brand}}}
    .doc-d{{font-size:12px;color:#777}}
    .wm{{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%) rotate(-30deg);font-size:74px;font-weight:800;color:{brand};opacity:.06;z-index:0;white-space:nowrap;pointer-events:none;font-family:'Space Grotesk'}}
    .wm-logo{{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);width:96%;max-width:760px;opacity:.075;z-index:0;pointer-events:none}}
    .ft{{margin-top:22px;padding-top:10px;border-top:1px solid #ddd;text-align:center;color:#777;font-size:11.5px}}
    .content{{position:relative;z-index:1{';padding-top:118px;padding-bottom:110px' if lh_on else ''}}}
    @media print{{.noprint{{display:none !important}} body{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
      @page{{size:{paper};margin:6mm}}
      .lh-inner{{max-width:none;padding:0}}
      {'.content{padding-top:38mm;padding-bottom:20mm}' if lh_on else ''}}}"""
    wm = f'<img class="wm-logo" src="{h(wm_logo)}" alt="">' if wm_on else ''
    # Print / Email / WhatsApp / Back action buttons removed by request.
    toolbar = ""
    from flask import render_template
    # Odoo-style "Print" action opens this page with ?auto=1 → print dialog on load
    if request.args.get('auto'):
        body = body + ('<script>window.addEventListener("load",function(){'
                       'setTimeout(function(){window.print()},300)});</script>')
    return render_template('print_page.html', title=title, css=css, wm=wm,
                           lh_top=lh_top, lh_bot=lh_bot, head_block=head_block,
                           brand_header=brand_header, bc_html=bc_html, header_html=header_html,
                           body=body, signature=_sig_block(signature, doc_ref),
                           qr_html=qr_html, footer_html=footer_html,
                           brand_footer=brand_footer, meta_html=meta_html, toolbar=toolbar)
