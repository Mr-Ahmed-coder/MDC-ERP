"""Odoo-style document action dialog  (v8.1).

A single reusable "What do you want to do?" modal offering three DISTINCT actions
for any generated document (invoice, receipt, report, lab/imaging result):

  • Print    — opens the document in a new tab and starts the print dialog.
  • Download — saves the document as a file (a real PDF/Excel/CSV when the page
               provides one via data-pdf/data-file, otherwise the formatted
               document is saved as a standalone .html you can keep, e-mail or
               print later — works offline).
  • Open     — opens the document in a new tab to read or share (no auto-print).

Trigger from any button:

    <button onclick="MDCDoc.open({print:'/invoice/1/print?auto=1',
                                  download:'/invoice/1/pdf',   // real file (optional)
                                  open:'/invoice/1/print',
                                  title:'Invoice INV-0001'})">Print</button>

Any <a> whose href looks like a document (/print, /receipt/, /card, /label,
/statement, /voucher, /report, /payslip) is auto-intercepted; add data-pdf="…"
(or data-file="…") to give Download a real file to save.
"""


def doc_actions_html():
    return r"""
<div id="mdcdoc" class="mdcdoc" hidden aria-hidden="true">
  <div class="mdcdoc-back" onclick="MDCDoc.close()"></div>
  <div class="mdcdoc-box" role="dialog" aria-label="Document actions">
    <div class="mdcdoc-hd"><span id="mdcdoc-title">Document</span>
      <button class="mdcdoc-x" onclick="MDCDoc.close()" aria-label="Close">&times;</button></div>
    <div class="mdcdoc-actions">
      <a id="mdcdoc-print" class="mdcdoc-b" href="#"><span class="i">&#128424;</span>Print</a>
      <a id="mdcdoc-open" class="mdcdoc-b gh" href="#"><span class="i">&#128462;</span>Open</a>
      <a id="mdcdoc-dl" class="mdcdoc-b alt" href="#"><span class="i">&#11015;</span>Download</a>
    </div>
  </div>
</div>
<style>
.mdcdoc{position:fixed;inset:0;z-index:10000;display:flex;align-items:flex-start;justify-content:center}
.mdcdoc[hidden]{display:none}
.mdcdoc-back{position:absolute;inset:0;background:rgba(15,23,42,.40)}
.mdcdoc-box{position:relative;margin-top:22vh;width:min(340px,92vw);background:var(--surface,#fff);color:var(--ink,#0f172a);
  border:1px solid var(--line,#e5e7eb);border-radius:10px;box-shadow:0 16px 44px rgba(0,0,0,.26);overflow:hidden}
.mdcdoc-hd{display:flex;align-items:center;justify-content:space-between;padding:9px 14px;border-bottom:1px solid var(--line,#e5e7eb);font-size:13.5px;font-weight:600;color:var(--muted,#64748b)}
.mdcdoc-x{border:0;background:transparent;color:var(--muted,#64748b);font-size:19px;line-height:1;cursor:pointer;padding:0 2px}
.mdcdoc-actions{display:flex;gap:8px;padding:12px 14px}
.mdcdoc-b{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;padding:10px 6px;border-radius:8px;
  background:var(--petrol,#044C8C);color:#fff;text-decoration:none;font-size:12.5px;font-weight:600;border:1px solid transparent;cursor:pointer;transition:.12s}
.mdcdoc-b .i{font-size:17px}
.mdcdoc-b.alt{background:var(--green,#1FA66D)}
.mdcdoc-b.gh{background:var(--surface,#fff);color:var(--petrol,#044C8C);border-color:var(--line,#e5e7eb)}
.mdcdoc-b:hover{filter:brightness(.95)}
@media(max-width:420px){.mdcdoc-box{width:94vw}}
</style>
<script>
(function(){
  function el(id){return document.getElementById(id)}
  function fname(t){return String(t||'document').replace(/[^\w.\-]+/g,'_').replace(/_+/g,'_').slice(0,80)||'document';}
  // Save a real server file (PDF/Excel/CSV — sent with Content-Disposition: attachment).
  function realDownload(url){
    var a=document.createElement('a'); a.href=url; a.setAttribute('download',''); a.style.display='none';
    document.body.appendChild(a); a.click(); setTimeout(function(){a.remove();},1500);
  }
  // Fallback: fetch the formatted document HTML and save it as a standalone file.
  function htmlDownload(url,title){
    fetch(url,{credentials:'same-origin'}).then(function(r){return r.text();}).then(function(html){
      var blob=new Blob(['\ufeff'+html],{type:'text/html;charset=utf-8'});
      var u=URL.createObjectURL(blob); var a=document.createElement('a');
      a.href=u; a.download=fname(title)+'.html'; a.style.display='none';
      document.body.appendChild(a); a.click();
      setTimeout(function(){a.remove();URL.revokeObjectURL(u);},2000);
    }).catch(function(){ window.open(url,'_blank'); });
  }
  // Print a PDF WITHOUT opening a visible tab: load it into a hidden iframe on
  // the current page, then call print() once it has loaded. Falls back to a new
  // tab only if the browser blocks scripted printing of the framed PDF.
  function printPdf(url,title){
    var old=document.getElementById('mdcPrintFrame');
    if(old){ try{old.remove();}catch(e){} }
    var f=document.createElement('iframe');
    f.id='mdcPrintFrame';
    f.style.position='fixed'; f.style.right='0'; f.style.bottom='0';
    f.style.width='0'; f.style.height='0'; f.style.border='0'; f.style.visibility='hidden';
    var done=false;
    f.onload=function(){
      setTimeout(function(){
        try{ f.contentWindow.focus(); f.contentWindow.print(); done=true; }
        catch(e){ if(!done){ window.open(url,'_blank'); } }
      },400);
    };
    f.src=url;
    document.body.appendChild(f);
  }
  function show(){var m=el('mdcdoc'); m.hidden=false; m.setAttribute('aria-hidden','false');}

  window.MDCDoc={
    open:function(o){
      o=o||{};
      el('mdcdoc-title').textContent=o.title||'What do you want to do?';
      var pdfUrl=o.download||'';                   // real PDF (if the page declared one)
      var viewUrl=o.open||o.print||o.html;         // HTML fallback (letterhead paper)
      var printUrl=o.print||viewUrl;               // HTML auto-print fallback
      var pr=el('mdcdoc-print'), dl=el('mdcdoc-dl'), op=el('mdcdoc-open');
      // When a real PDF is available, all three actions use it:
      //   Print    → open PDF in new tab + auto-trigger print
      //   Open     → view PDF inline in new tab
      //   Download → save PDF (Content-Disposition: attachment)
      // Otherwise fall back to the HTML letterhead paper.
      if(pdfUrl){
        var sep=pdfUrl.indexOf('?')>=0?'&':'?';
        pr.onclick=function(e){e.preventDefault(); printPdf(pdfUrl, o.title); MDCDoc.close();};
        op.onclick=function(e){e.preventDefault(); window.open(pdfUrl,'_blank'); MDCDoc.close();};
        dl.onclick=function(e){e.preventDefault(); realDownload(pdfUrl+sep+'dl=1'); MDCDoc.close();};
      } else {
        pr.onclick=function(e){e.preventDefault(); if(printUrl)window.open(printUrl,'_blank'); MDCDoc.close();};
        op.onclick=function(e){e.preventDefault(); if(viewUrl)window.open(viewUrl,'_blank'); MDCDoc.close();};
        dl.onclick=function(e){e.preventDefault(); htmlDownload(o.html||viewUrl, o.title); MDCDoc.close();};
      }
      pr.style.display=(pdfUrl||printUrl)?'':'none';
      op.style.display=(pdfUrl||viewUrl)?'':'none';
      dl.style.display=(pdfUrl||o.html||viewUrl)?'':'none';
      show();
    },
    close:function(){var m=el('mdcdoc');if(m){m.hidden=true;m.setAttribute('aria-hidden','true');}},

    // Current-page reports. Three distinct actions:
    //   Print    — browser print dialog (also lets you "Save as PDF")
    //   Open     — open the document (a real PDF when a docUrl is given → "paper" view; else this page in a new tab)
    //   Download — save the document as a PDF file (when docUrl given); else save this page as .html
    openSelf:function(title, docUrl){
      el('mdcdoc-title').textContent=title||'Print document';
      var pr=el('mdcdoc-print'), dl=el('mdcdoc-dl'), op=el('mdcdoc-open');
      pr.onclick=function(e){e.preventDefault();MDCDoc.close();setTimeout(function(){window.print();},80);};
      if(docUrl){
        var sep=docUrl.indexOf('?')>=0?'&':'?';
        op.onclick=function(e){e.preventDefault();window.open(docUrl,'_blank');MDCDoc.close();};
        dl.onclick=function(e){e.preventDefault();realDownload(docUrl+sep+'dl=1');MDCDoc.close();};
      } else {
        op.onclick=function(e){e.preventDefault();window.open(location.href,'_blank');MDCDoc.close();};
        dl.onclick=function(e){e.preventDefault();htmlDownload(location.href,title||document.title);MDCDoc.close();};
      }
      pr.style.display=''; op.style.display=''; dl.style.display='';
      show();
    }
  };

  // Auto-intercept clicks on printable-document links → open the dialog.
  // Matches: /print, /receipt/, /card, /label, /statement, /voucher, /report, /payslip
  document.addEventListener('click',function(e){
    var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if(!a) return;
    if(a.hasAttribute('data-nodoc')) return;
    var href = a.getAttribute('href') || '';
    var isDoc = /(\/print|\/receipt\/|\/card|\/label|\/statement|\/voucher|\/report|\/payslip)(\/|\?|#|$)/.test(href);
    if(!isDoc) return;
    if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||e.button===1) return; // keep native new-tab
    e.preventDefault();
    var sep = href.indexOf('?')>=0 ? '&' : '?';
    var file = a.getAttribute('data-pdf') || a.getAttribute('data-file') || '';
    var title = a.getAttribute('data-title') || (a.textContent||'').trim() || 'Document';
    MDCDoc.open({
      print: href + sep + 'auto=1',   // Print: open + auto-print
      open:  href,                    // Open: view only
      download: file,                 // real file if the link declares one
      html:  href,                    // else save the formatted document as .html
      title: title
    });
  }, true);
  document.addEventListener('keydown',function(e){
    if((e.key||'').toLowerCase()==='escape'){var m=el('mdcdoc');if(m&&!m.hidden)MDCDoc.close();}
  });
})();
</script>
"""
