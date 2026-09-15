"""Render a print-view HTML page to a PDF that is IDENTICAL to what the browser
shows for Print/Open — so the Download button gives the exact same document.

Uses wkhtmltopdf (via pdfkit) when available. If it is not installed on the
server, callers fall back to the built-in reportlab generator.
"""
import os
import re
import base64
import shutil

_WK = shutil.which('wkhtmltopdf')


def available():
    return _WK is not None


def _inline_static_images(html):
    """Rewrite <img src="/static/..."> to base64 data URIs so the external
    wkhtmltopdf process can render the letterhead/logo without app access."""
    try:
        import mdc_erp
        static_root = os.path.join(os.path.dirname(mdc_erp.__file__), 'static')
    except Exception:
        return html
    _mime = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
             '.gif': 'image/gif', '.svg': 'image/svg+xml', '.webp': 'image/webp'}

    def _repl(mobj):
        rel = mobj.group(1)               # e.g. /static/brand/letterhead-header.jpg
        path = os.path.normpath(os.path.join(static_root, rel[len('/static/'):]))
        if not path.startswith(static_root) or not os.path.exists(path):
            return mobj.group(0)
        ext = os.path.splitext(path)[1].lower()
        try:
            with open(path, 'rb') as fh:
                b64 = base64.b64encode(fh.read()).decode('ascii')
            return f'src="data:{_mime.get(ext, "image/png")};base64,{b64}"'
        except Exception:
            return mobj.group(0)

    return re.sub(r'src="(/static/[^"]+)"', _repl, html)


def _strip_external(html):
    """Remove external <link>/font fetches so wkhtmltopdf never hits the network
    (which it blocks by default → ContentAccessDenied). System fonts render fine."""
    # drop <link ... href="http...">  (Google Fonts etc.)
    html = re.sub(r'<link[^>]+href="https?://[^"]*"[^>]*>', '', html, flags=re.I)
    # drop @import url(http...) inside <style>
    html = re.sub(r'@import\s+url\((["\']?)https?://[^)]*\1\)\s*;?', '', html, flags=re.I)
    return html


_FIT_CSS = """
<style id="pdf-fit">
  /* Pin the branded letterhead header/footer flush to the page edges so a short
     document fills the paper: header at the very top, footer at the very bottom. */
  html, body { height: 100%; }
  .lh-top { top: 0 !important; }
  .lh-bot { bottom: 0 !important; }
  .lh-bot .lh-inner img { margin-bottom: 0 !important; }
</style>
"""


def _inject_fit(html):
    if '</head>' in html:
        return html.replace('</head>', _FIT_CSS + '</head>', 1)
    return _FIT_CSS + html


_FIT_CSS = """
<style id="pdf-fit">
  /* Make the page body exactly one A4 tall so a short document fills the paper
     and the fixed letterhead footer lands flush at the physical page bottom. */
  html { height: 297mm; }
  body { min-height: 297mm; position: relative; box-sizing: border-box; }
  .lh-top { top: 0 !important; }
  .lh-bot { bottom: 0 !important; }
</style>
"""


def _inject_fit(html):
    if '</head>' in html:
        return html.replace('</head>', _FIT_CSS + '</head>', 1)
    return _FIT_CSS + html


_FIT_CSS = """
<style id="pdf-fit">
  /* Fill the A4 page and push the letterhead footer to the bottom so a short
     document does not leave the footer floating near the middle. */
  @page { size: A4; margin: 0; }
  html { height: 100%; }
  body {
    display: flex !important;
    flex-direction: column !important;
    min-height: 1080px;               /* ~ full A4 at the render DPI */
    width: 100%;
    margin: 0 !important;
    box-sizing: border-box;
  }
  .wm, .wm-logo { position: fixed !important; }         /* watermark stays centred */
  .lh-top  { position: static !important; order: 0; width: 100%; }
  .content { position: static !important; order: 1; flex: 1 0 auto !important;
             width: 100%; padding-top: 8px !important; padding-bottom: 8px !important; }
  .lh-bot  { position: static !important; order: 2; width: 100%; margin-top: auto; }
</style>
"""


def _inject_fit(html):
    if '</head>' in html:
        return html.replace('</head>', _FIT_CSS + '</head>', 1)
    return _FIT_CSS + html


def html_to_pdf(html, base_url=None):
    """Return PDF bytes for the given full HTML string, or None if wkhtmltopdf
    is not available / rendering failed (caller should fall back)."""
    if not _WK:
        return None
    try:
        import pdfkit
        html = _inline_static_images(html)
        html = _strip_external(html)
        cfg = pdfkit.configuration(wkhtmltopdf=_WK)
        options = {
            'page-size': 'A4',
            'margin-top': '6mm', 'margin-bottom': '6mm',
            'margin-left': '6mm', 'margin-right': '6mm',
            'encoding': 'UTF-8',
            'print-media-type': None,
            'enable-local-file-access': None,
            'disable-external-links': None,
            'disable-smart-shrinking': None,
            'dpi': '96',
            'zoom': '1.3',            # scale content up so it fills the paper like the browser print
            'quiet': '',
        }
        return pdfkit.from_string(html, False, options=options, configuration=cfg)
    except Exception:
        return None


# --- Chromium print-to-PDF (matches the browser's Print → Save PDF exactly) ----
def chrome_available():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except Exception:
        return False


def chrome_pdf_from_url(url, cookies=None):
    """Render a page with headless Chromium to a PDF that is byte-for-byte what the
    browser produces for Print → Save PDF (fills the page, footer at the bottom).
    `cookies` is a list of Playwright cookie dicts for the logged-in session.
    Returns PDF bytes, or None to fall back."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=['--no-sandbox'])
            ctx = browser.new_context()
            if cookies:
                try:
                    ctx.add_cookies(cookies)
                except Exception:
                    pass
            page = ctx.new_page()
            page.goto(url, wait_until='networkidle', timeout=20000)
            pdf = page.pdf(prefer_css_page_size=True, print_background=True)
            browser.close()
            return pdf
    except Exception:
        return None
