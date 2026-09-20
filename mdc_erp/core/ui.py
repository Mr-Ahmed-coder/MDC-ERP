"""Layout engine: CSS theme, navigation, page shell, public shell."""
from flask import request, session, redirect, url_for, get_flashed_messages
from markupsafe import escape as h
from .security import cur_user, can, setting, ROLE_LABEL

CSS = """
/* Brand tokens taken from the centre's own letterhead: navy #004890, orange #E45424.
   Variable names are unchanged so every existing screen re-skins automatically. */
:root{--petrol:#044C8C;--petrol7:#02305A;--amber:#E45424;--amber-dk:#C33F13;--amber-soft:#FDEDE5;
--teal:#1E7FB8;--canvas:#F4F6F8;--surface:#fff;--ink:#15212B;--muted:#66757F;--line:#E1E7EC;
--green:#127A5B;--green-soft:#E3F2EC;--red:#C0392B;--red-soft:#FBE9E7;--blue:#044C8C;--hover:#F3F7FB;--ring:rgba(4,76,140,.28);
--shadow:0 1px 2px rgba(4,42,76,.045),0 4px 14px rgba(4,42,76,.06);--radius:13px;
--fd:'Space Grotesk',system-ui,sans-serif;--fb:'Inter',system-ui,-apple-system,sans-serif;
--fm:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;}
body.dark{--petrol:#0A1A28;--canvas:#0B1520;--surface:#111E2B;--ink:#E6EDF3;--muted:#8B9CA8;--line:#22323F;--hover:#16283A;--ring:rgba(120,170,220,.35);--amber-soft:#3A2314;--green-soft:#10322A;--red-soft:#3A1E1B;--shadow:0 1px 3px rgba(0,0,0,.45)}
*{box-sizing:border-box;margin:0;padding:0}html,body{height:100%}
body{font-family:var(--fb);background:var(--canvas);color:var(--ink);font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}button{font-family:inherit;cursor:pointer}
input,select,textarea{font-family:inherit;font-size:14px}
input:focus-visible,select:focus-visible,textarea:focus-visible{outline:none;border-color:var(--petrol);box-shadow:0 0 0 3px var(--ring)}
.pill{transition:none}
.app{display:flex;min-height:100vh}
.sidebar{width:260px;background:var(--petrol);color:#DCE7E9;display:flex;flex-direction:column;position:fixed;inset:0 auto 0 0;z-index:40;transition:width .2s ease,transform .25s ease}
.brand{padding:14px 16px;border-bottom:1px solid rgba(255,255,255,.08);display:flex;align-items:center;justify-content:space-between;gap:8px}
.brand .logo{font-family:var(--fd);font-weight:700;font-size:15px;color:#fff;display:flex;align-items:center;gap:9px;min-width:0}
.brand .mark{width:28px;height:28px;border-radius:7px;background:linear-gradient(135deg,var(--amber),#F2C063);display:grid;place-items:center;color:var(--petrol7);font-weight:700;flex:none}
.brand .sub{font-size:11px;color:#89A6AB;margin-top:2px}
.brand-text{display:flex;flex-direction:column;min-width:0}
.sb-toggle-btn{background:none;border:none;color:#89A6AB;cursor:pointer;padding:5px;border-radius:6px;display:flex;align-items:center;justify-content:center;transition:color .15s,background .15s;flex:none}
.sb-toggle-btn:hover{color:#fff;background:rgba(255,255,255,.1)}
.sb-toggle-btn svg{transition:transform .2s ease}
.nav{padding:8px 10px;flex:1;overflow-y:auto;overflow-x:hidden}
.nav .g{font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:#8fb0cc;margin:12px 8px 4px;font-weight:700;white-space:nowrap}
.navsec{margin-top:2px}
.navsec .gbtn{width:100%;display:flex;align-items:center;justify-content:space-between;background:none;border:0;cursor:pointer;font-family:inherit;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:#8fb0cc;padding:10px 8px 4px}
.navsec .gbtn:hover{color:#e6eff7}
.navsec .chev{width:14px;height:14px;transition:transform .18s;opacity:.8;flex:none}
.navsec.open .chev{transform:rotate(90deg)}
.navsub{display:none;flex-direction:column;gap:1px}
.navsec.open .navsub{display:flex}
.nav a{display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:8px;color:#cdddea;font-size:13.5px;font-weight:500;transition:background .15s,color .15s;position:relative;white-space:nowrap;text-decoration:none}
.nav a:hover{background:rgba(255,255,255,.08);color:#fff}
.nav a.active{background:rgba(228,84,36,.18);color:#fff;font-weight:600;box-shadow:inset 3px 0 0 var(--amber)}
.nav a.active .ic{color:var(--amber)}
.nav a .ic{width:18px;height:18px;flex:none;color:#9db6cc}
.main{flex:1;margin-left:260px;display:flex;flex-direction:column;min-width:0;transition:margin-left .2s ease}
.sidebar.collapsed{width:68px}
.sidebar.collapsed ~ .main{margin-left:68px}
.sidebar.collapsed .brand{padding:14px 10px;justify-content:center}
.sidebar.collapsed .brand-text,.sidebar.collapsed .brand .sub{display:none}
.sidebar.collapsed .sb-toggle-btn svg{transform:rotate(180deg)}
.sidebar.collapsed .nav{padding:6px 4px}
.sidebar.collapsed .nav .g,.sidebar.collapsed .navsec .gbtn{display:none}
.sidebar.collapsed .navsec .navsub{display:flex!important}
.sidebar.collapsed .nav a{justify-content:center;padding:9px 0;width:44px;margin:2px auto}
.sidebar.collapsed .nav a .nav-text{display:none}
.sidebar.collapsed .nav a:hover::after{content:attr(data-tooltip);position:absolute;left:calc(100% + 10px);top:50%;transform:translateY(-50%);background:#111E2B;color:#fff;padding:5px 10px;border-radius:6px;font-size:12px;font-weight:500;white-space:nowrap;z-index:100;box-shadow:0 4px 12px rgba(0,0,0,.25);pointer-events:none}
.top{height:58px;background:var(--surface);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:14px;padding:0 20px;position:sticky;top:0;z-index:30}
.top h1{font-family:var(--fd);font-size:18px;font-weight:600}
.top .sp{flex:1}
.menu-btn{display:none;background:none;border:none;font-size:22px;color:var(--petrol);cursor:pointer;padding:4px}
.apps-btn{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:var(--surface);color:var(--petrol);border-radius:8px;padding:6px 10px;font-size:13px;font-weight:700;cursor:pointer}.apps-btn:hover{background:var(--canvas);border-color:var(--petrol)}.apps-label{font-size:12px}
.chip{display:flex;align-items:center;gap:9px;border-left:1px solid var(--line);padding-left:12px}
.av{width:32px;height:32px;border-radius:50%;background:var(--petrol);color:#fff;display:grid;place-items:center;font-weight:600;font-size:13px}
.chip small{color:var(--muted);text-transform:capitalize;font-size:11px}
.content{padding:22px;max-width:1180px;width:100%}
.btn{border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:9px 14px;border-radius:9px;font-weight:600;font-size:13px;display:inline-flex;align-items:center;gap:6px;transition:border-color .15s,background .15s,box-shadow .15s,transform .05s}
.btn:hover{border-color:var(--petrol);background:var(--hover)}
.btn:active{transform:translateY(1px)}
.btn:focus-visible{outline:none;box-shadow:0 0 0 3px var(--ring)}
.btn.primary{background:var(--amber);border-color:var(--amber);color:#fff;box-shadow:0 1px 2px rgba(196,63,19,.25)}
.btn.primary:hover{background:var(--amber-dk);border-color:var(--amber-dk)}
.btn.sm{padding:6px 10px;font-size:12px}
.btn.gh{background:none;border:none;color:var(--muted);padding:6px 8px}.btn.gh:hover{color:var(--red)}
.btn.ok{color:var(--green);border-color:var(--green-soft)}
.quick-create{position:relative;display:inline-flex;margin-right:4px}.quick-create-menu{display:none;position:absolute;right:0;top:calc(100% + 7px);width:220px;background:var(--surface);border:1px solid var(--line);border-radius:11px;box-shadow:0 14px 34px rgba(2,48,90,.18);z-index:140;padding:5px}.quick-create.open .quick-create-menu{display:block}.quick-create-menu a{display:block;padding:9px 11px;border-radius:7px;font-size:13px;color:var(--ink)}.quick-create-menu a:hover{background:var(--canvas);color:var(--petrol)}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow);position:relative;overflow:hidden;transition:box-shadow .15s,transform .12s}
.kpi:hover{box-shadow:0 2px 4px rgba(4,42,76,.06),0 10px 24px rgba(4,42,76,.09);transform:translateY(-1px)}
.kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--ac,var(--teal))}
.kpi .l{font-size:10.5px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);font-weight:600}
.kpi .v{font-family:var(--fd);font-size:24px;font-weight:600;margin-top:6px;letter-spacing:-.3px}
.kpi .v.neg{color:var(--red)}.kpi .s{font-size:11px;color:var(--muted);margin-top:2px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);margin-bottom:20px}
.ph{display:flex;align-items:center;gap:12px;padding:15px 18px;border-bottom:1px solid var(--line)}
.ph h2{font-family:var(--fd);font-size:15px;font-weight:600;letter-spacing:-.1px}
.ph .so{font-size:12px;color:var(--muted)}.ph .sp{flex:1}
.pad{padding:16px 18px}
.tw{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
thead th{background:rgba(0,0,0,.015);color:var(--petrol);text-align:left;font-weight:600;font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;padding:12px 16px;border-bottom:1px solid var(--line);white-space:nowrap}
body.dark thead th{background:rgba(255,255,255,.03)}
tbody tr{transition:background .13s}
tbody tr:hover{background:var(--hover)}
tbody td{padding:12px 16px;border-bottom:1px solid var(--line);white-space:nowrap}
tbody tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.empty{padding:34px;text-align:center;color:var(--muted)}
.empty b{display:block;color:var(--ink);font-size:15px;margin-bottom:5px}
.pill{display:inline-block;padding:3px 10px;border-radius:7px;font-size:10.5px;font-weight:600;letter-spacing:.2px;line-height:1.45}
.pill.green{background:var(--green-soft);color:var(--green)}.pill.amber{background:var(--amber-soft);color:var(--amber-dk)}
.pill.grey{background:rgba(0,0,0,.06);color:var(--muted)}.pill.red{background:var(--red-soft);color:var(--red)}.pill.blue{background:#E4ECF7;color:var(--blue)}
body.dark .pill.grey{background:rgba(255,255,255,.08)}body.dark .pill.blue{background:#1E3348;color:#8FB4DA}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
/* ---- modern dashboard: section label ---- */
.sec-lbl{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px}
/* ---- live widget cards ---- */
.wgs{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:18px}
.wg-link{text-decoration:none}
.wg{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:14px;box-shadow:var(--shadow);display:flex;gap:11px;align-items:center;transition:transform .12s,box-shadow .12s;position:relative;overflow:hidden}
.wg::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--ac,var(--teal))}
.wg-link:hover .wg{transform:translateY(-2px);box-shadow:0 6px 18px rgba(26,62,143,.13)}
.wg-ic{font-size:22px;width:42px;height:42px;display:flex;align-items:center;justify-content:center;background:var(--canvas);border-radius:11px;flex-shrink:0}
.wg-v{font-family:var(--fd);font-size:22px;font-weight:700;color:var(--ink);line-height:1.1}
.wg-l{font-size:11.5px;color:var(--muted);font-weight:600;margin-top:2px}
.wg-s{font-size:10.5px;color:var(--muted)}
/* ---- quick actions ---- */
.qa-wrap{margin-bottom:18px}
.qas{display:flex;gap:10px;flex-wrap:wrap}
.qa{display:inline-flex;align-items:center;gap:8px;text-decoration:none;background:var(--canvas);border:1px solid var(--line);border-radius:10px;padding:10px 15px;font-size:13.5px;font-weight:600;color:var(--ink);transition:all .12s}
.qa:hover{background:var(--petrol);color:#fff;border-color:var(--petrol)}
.qa-i{font-size:16px}
/* ---- category cards ---- */
.cats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}
.cat{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:15px;box-shadow:var(--shadow);position:relative;overflow:hidden}
.cat::before{content:"";position:absolute;left:0;top:0;right:0;height:3px;background:var(--ac,var(--petrol))}
.cat-h{display:flex;align-items:center;gap:9px;margin-bottom:11px}
.cat-ic{font-size:19px;width:36px;height:36px;display:flex;align-items:center;justify-content:center;background:var(--canvas);border-radius:9px}
.cat-t{font-weight:700;font-size:14px;color:var(--ink)}
.cat-links{display:flex;flex-direction:column;gap:3px}
.cat-link{text-decoration:none;color:var(--muted);font-size:13px;padding:5px 8px;border-radius:7px;transition:all .1s}
.cat-link:hover{background:var(--canvas);color:var(--petrol);font-weight:600;padding-left:12px}
/* ---- top tests bars ---- */
.tt-row{display:flex;align-items:center;gap:10px;margin:7px 0}
.tt-n{flex:0 0 38%;font-size:12.5px;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tt-bar{flex:1;height:9px;background:var(--canvas);border-radius:5px;overflow:hidden}
.tt-bar span{display:block;height:100%;background:linear-gradient(90deg,var(--petrol),var(--teal));border-radius:5px}
.tt-v{flex:0 0 28px;text-align:right;font-weight:700;font-size:12.5px;color:var(--petrol)}
/* ---- Odoo-style chevron progress bar ---- */
.chev-wrap{display:flex;flex-wrap:wrap;gap:3px;margin:0 0 18px}
.chev{position:relative;flex:1;min-width:96px;text-align:center;padding:9px 14px 9px 22px;background:var(--surface);border:1px solid var(--line);color:var(--muted);font-size:12px;font-weight:600;clip-path:polygon(0 0,calc(100% - 12px) 0,100% 50%,calc(100% - 12px) 100%,0 100%,12px 50%)}
.chev:first-child{clip-path:polygon(0 0,calc(100% - 12px) 0,100% 50%,calc(100% - 12px) 100%,0 100%);padding-left:16px}
.chev.done{background:var(--green-soft);color:var(--green);border-color:transparent}
.chev.active{background:var(--petrol);color:#fff;border-color:transparent}
/* ---- smart buttons (linked records) ---- */
.sbtns{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px}
.sbtn{display:flex;flex-direction:column;text-decoration:none;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 18px;min-width:120px;box-shadow:var(--shadow);transition:all .12s}
.sbtn:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(26,62,143,.13);border-color:var(--petrol)}
.sbtn-v{font-family:var(--fd);font-size:19px;font-weight:700;color:var(--petrol)}
.sbtn-l{font-size:11.5px;color:var(--muted);font-weight:600;margin-top:2px}
.sbtn-cta{background:var(--petrol)}.sbtn-cta .sbtn-v,.sbtn-cta .sbtn-l{color:#fff}
/* ---- timeline ---- */
.tl{position:relative;padding-left:6px}
.tl-row{display:flex;gap:12px;position:relative;padding-bottom:16px}
.tl-row::before{content:"";position:absolute;left:5px;top:14px;bottom:-2px;width:2px;background:var(--line)}
.tl-row:last-child::before{display:none}
.tl-dot{width:12px;height:12px;border-radius:50%;background:var(--petrol);border:2px solid var(--surface);box-shadow:0 0 0 2px var(--petrol);flex-shrink:0;margin-top:3px;z-index:1}
.tl-when{font-size:11px;color:var(--muted);font-weight:600}
.tl-what{font-size:13.5px;color:var(--ink);font-weight:600}
.tl-who{font-size:11.5px;color:var(--muted)}
/* ---- generic list filter toolbar ---- */
.listbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.lb-input{border:1px solid var(--line);border-radius:8px;padding:7px 10px;font-size:13px;background:var(--surface);color:var(--ink)}
.lb-input:focus{outline:none;border-color:var(--petrol)}
.pager{display:flex;align-items:center;gap:6px;padding:11px 16px;border-top:1px solid var(--line);flex-wrap:wrap}
.pg-info{color:var(--muted);font-size:12.5px}
.pg-a{border:1px solid var(--line);border-radius:7px;padding:5px 10px;font-size:12.5px;font-weight:600;background:var(--surface);color:var(--ink)}
.pg-a:hover{border-color:var(--petrol)}
.pg-a.on{background:var(--petrol);border-color:var(--petrol);color:#fff}
.pg-x{color:var(--muted);font-size:12.5px;padding:5px 6px}
.lb-count{font-size:12px;color:var(--muted);margin-left:auto;font-weight:600}
/* ---- app launcher (all modules in one place) ---- */
.app-grp{margin:18px 0}
.app-grp-h{display:flex;align-items:center;gap:9px;font-weight:700;font-size:14px;color:var(--petrol);margin-bottom:10px;text-transform:uppercase;letter-spacing:.4px}
.app-grp-ic{font-size:18px}
.app-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.cat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.cat-tile{display:flex;align-items:center;gap:14px;text-decoration:none;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:18px 18px;box-shadow:var(--shadow);transition:transform .12s,box-shadow .12s,border-color .12s}
.cat-tile:hover{transform:translateY(-2px);box-shadow:0 8px 22px rgba(26,62,143,.14);border-color:var(--petrol)}
.cat-ic{width:52px;height:52px;border-radius:13px;display:grid;place-items:center;font-size:27px;line-height:1;flex-shrink:0}
.cat-tx{display:flex;flex-direction:column;line-height:1.3;min-width:0;flex:1}
.cat-tx b{font-family:var(--fd);font-size:16px;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cat-tx small{font-size:12px;color:var(--muted);margin-top:1px}
.cat-arrow{color:var(--muted);font-size:18px;transition:transform .12s,color .12s}
.cat-tile:hover .cat-arrow{color:var(--petrol);transform:translateX(3px)}
.app-item{display:flex;align-items:center;gap:11px;text-decoration:none;background:var(--surface);border:1px solid var(--line);border-radius:11px;padding:12px 14px;transition:all .12s}
.app-item:hover{transform:translateY(-2px);box-shadow:0 6px 16px rgba(26,62,143,.13);border-color:var(--petrol)}
.app-ic{width:38px;height:38px;border-radius:10px;display:grid;place-items:center;font-size:20px;line-height:1;flex-shrink:0}
.app-txt{display:flex;flex-direction:column;line-height:1.25;min-width:0}
.app-txt b{font-size:13.5px;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.app-txt small{font-size:11px;color:var(--muted)}
@media(max-width:860px){.app-grid{grid-template-columns:1fr 1fr}.cat-grid{grid-template-columns:1fr 1fr}}
@media(max-width:480px){.app-grid{grid-template-columns:1fr}.cat-grid{grid-template-columns:1fr}}
/* ---- app launcher (one place for everything) ---- */
.apps-btn{background:none;border:1px solid var(--line);border-radius:9px;width:38px;height:38px;font-size:18px;color:var(--petrol);cursor:pointer;display:flex;align-items:center;justify-content:center;margin-right:4px}
.apps-btn:hover{background:var(--petrol);color:#fff;border-color:var(--petrol)}
.launcher{position:fixed;inset:0;background:rgba(10,25,30,.55);backdrop-filter:blur(3px);z-index:100;display:none;align-items:flex-start;justify-content:center;padding:60px 16px}
.launcher.show{display:flex}
.lc-box{background:var(--surface);border-radius:16px;width:100%;max-width:760px;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.35);overflow:hidden}
.lc-head{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--line)}
#lc-search{flex:1;border:none;background:var(--canvas);border-radius:10px;padding:12px 15px;font-size:15px;color:var(--ink);font-family:var(--fb)}
#lc-search:focus{outline:2px solid var(--petrol)}
.lc-x{background:none;border:none;font-size:18px;color:var(--muted);cursor:pointer;padding:6px 10px}
.lc-body{overflow-y:auto;padding:14px 18px 20px}
.lc-grp{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin:14px 0 8px}
.lc-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.lt{display:flex;flex-direction:column;align-items:center;gap:6px;text-decoration:none;padding:14px 8px;border-radius:11px;border:1px solid var(--line);background:var(--surface);color:var(--ink);text-align:center;transition:all .12s}
.lt:hover{background:var(--petrol);color:#fff;border-color:var(--petrol);transform:translateY(-2px)}
.lt-ic{width:26px;height:26px}
.lt-ic svg{width:26px;height:26px}
.lt-l{font-size:12px;font-weight:600;line-height:1.2}
.lc-empty{text-align:center;color:var(--muted);padding:30px;font-size:14px}
@media(max-width:600px){.lc-grid{grid-template-columns:repeat(3,1fr)}.launcher{padding:20px 10px}}
.fg{display:grid;grid-template-columns:1fr 1fr;gap:13px}
.fld{display:flex;flex-direction:column;gap:5px}.fld.full{grid-column:1/-1}
.fld label{font-size:12px;font-weight:600;color:var(--petrol)}body.dark .fld label{color:var(--teal)}
.fld input,.fld select,.fld textarea{border:1px solid var(--line);border-radius:8px;padding:9px 11px;background:var(--surface);color:var(--ink);outline:none;width:100%}
.fld input:focus,.fld select:focus,.fld textarea:focus{border-color:var(--amber);box-shadow:0 0 0 3px var(--amber-soft)}
.fa{display:flex;gap:10px;justify-content:flex-end;margin-top:16px}
.flash{background:var(--green-soft);color:var(--green);padding:11px 16px;border-radius:9px;margin-bottom:16px;font-weight:600;font-size:13px}
.stmt .r{display:flex;justify-content:space-between;padding:8px 4px;border-bottom:1px solid var(--line)}
.stmt .r.tot{border-top:2px solid var(--petrol);font-weight:700}
.stmt .r.grand{background:var(--petrol);color:#fff;border-radius:9px;padding:11px 12px;margin-top:6px;border:none}
.stmt .sec{font-family:var(--fd);font-weight:600;color:var(--petrol);font-size:12px;text-transform:uppercase;letter-spacing:.5px;padding:12px 4px 4px}
body.dark .stmt .sec{color:var(--teal)}
.stmt .amt{font-variant-numeric:tabular-nums;font-weight:500}
.check{background:var(--green-soft);color:var(--green);border-radius:8px;padding:9px 12px;font-weight:600;margin-top:6px;display:flex;justify-content:space-between}
.tabs{display:flex;gap:6px;margin-bottom:18px;flex-wrap:wrap}
.tabs a{border:1px solid var(--line);background:var(--surface);padding:8px 14px;border-radius:9px;font-weight:600;font-size:13px;color:var(--muted)}
.tabs a.active{background:var(--petrol);border-color:var(--petrol);color:#fff}
.subnav{display:flex;align-items:center;gap:4px;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:7px 8px;margin-bottom:18px;flex-wrap:wrap;box-shadow:var(--shadow)}
.subnav-t{font-family:var(--fd);font-weight:600;color:var(--petrol);font-size:13px;padding:0 12px 0 8px;border-right:1px solid var(--line);margin-right:6px}
.subnav a{padding:8px 15px;border-radius:8px;font-weight:600;font-size:13px;color:var(--muted);text-decoration:none}
.subnav a:hover{background:var(--canvas);color:var(--ink)}
.subnav a.on{background:var(--petrol);color:#fff}
/* ---- Accounting 8-Group Menubar ---- */
.mbar-desktop{display:flex;align-items:center;gap:4px;background:var(--petrol);border-radius:12px;padding:5px 10px;margin-bottom:18px;flex-wrap:nowrap;box-shadow:var(--shadow);position:relative;z-index:50}
.mb-top{display:inline-flex;align-items:center;gap:5px;padding:8px 12px;color:#CFE0E4;font-weight:600;font-size:13px;border-radius:8px;cursor:pointer;text-decoration:none;white-space:nowrap;background:transparent;border:none;transition:all .15s ease}
.mb-item{position:relative}
.mb-item:hover .mb-top,.mb-item.open .mb-top,.mb-top:hover{background:rgba(255,255,255,.14);color:#fff}
.mb-top.on{background:var(--amber);color:var(--petrol-700,#0B2E35)!important;font-weight:700}
.mb-top.on:hover{background:var(--amber);color:var(--petrol-700,#0B2E35)}
.mb-chev{transition:transform .15s ease;opacity:.85}
.mb-item.open .mb-chev{transform:rotate(180deg)}
.mb-drop{display:none;position:absolute;top:calc(100% + 4px);left:0;min-width:210px;background:var(--surface);border:1px solid var(--line);border-radius:10px;box-shadow:0 12px 28px rgba(11,46,53,.22);padding:6px;z-index:60;max-height:70vh;overflow-y:auto}
.mb-item:hover .mb-drop,.mb-item.open .mb-drop{display:block}
.mb-drop a{display:block;padding:8px 12px;border-radius:7px;color:var(--ink);font-size:13px;font-weight:500;text-decoration:none;white-space:nowrap;transition:background .15s ease}
.mb-drop a:hover{background:var(--canvas);color:var(--petrol)}
.mb-drop a.on{background:var(--petrol);color:#fff;font-weight:600}

/* Mobile Accounting Selector (<860px) */
.mbar-mobile-wrap{display:none;margin-bottom:18px;position:relative;z-index:50}
.mbar-mobile-btn{width:100%;display:flex;align-items:center;justify-content:space-between;background:var(--petrol);color:#fff;padding:10px 14px;border-radius:10px;font-weight:600;font-size:13.5px;border:none;cursor:pointer}
.mbar-mobile-drawer{display:none;background:var(--surface);border:1px solid var(--line);border-radius:10px;margin-top:6px;padding:8px;box-shadow:var(--shadow)}
.mbar-mobile-drawer.open{display:block}
.mbar-mobile-group-ttl{font-size:11px;font-weight:700;color:var(--petrol);text-transform:uppercase;letter-spacing:.5px;padding:8px 10px 4px;margin-top:4px}
.mbar-mobile-group-ttl:first-child{margin-top:0}
.mbar-mobile-drawer a{display:block;padding:8px 12px;border-radius:6px;color:var(--ink);font-size:13px;text-decoration:none;font-weight:500}
.mbar-mobile-drawer a.on{background:var(--petrol);color:#fff;font-weight:600}

@media(max-width:860px){
  .mbar-desktop{display:none!important}
  .mbar-mobile-wrap{display:block!important}
}
.chart{width:100%;height:190px}.chart text{font-size:10px;fill:var(--muted)}
.scrim{position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:35;display:none}
@media(max-width:860px){.sidebar{transform:translateX(-100%)}.sidebar.open{transform:none}.main{margin-left:0}.menu-btn{display:block}.kpis{grid-template-columns:1fr 1fr}.grid2,.fg{grid-template-columns:1fr}.chip small{display:none}.scrim.show{display:block}.wgs{grid-template-columns:repeat(3,1fr)}.cats{grid-template-columns:1fr 1fr}.top{padding:0 12px;gap:8px}.top h1{font-size:16px}.top input{width:140px!important}.apps-label{display:none}.quick-create-menu{position:fixed;right:12px;top:58px}}
@media(max-width:480px){.kpis{grid-template-columns:1fr}.content{padding:15px}.wgs{grid-template-columns:1fr 1fr}.cats{grid-template-columns:1fr}.qa{flex:1;justify-content:center}}
@media print{.sidebar,.top,.tabs,.subnav,.btn{display:none!important}.main{margin:0}.content{padding:0}.panel{box-shadow:none;border:none}}

/* ======================= standard-grade refinements ======================= */

/* Money, IDs and results are read down a column, so they are set in a mono face
   with tabular figures. This one change is what makes the tables look engineered. */
.num,td.num,th.num,.amt,.kpi .v,.stmt .amt,.mrn,.pg-info{
  font-family:var(--fm);font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1;
  letter-spacing:-.01em}

/* Cards: the hairline carries the structure, the shadow only lifts it slightly. */
.panel{border:1px solid var(--line);box-shadow:var(--shadow);border-radius:var(--radius)}
.panel .ph{border-bottom:1px solid var(--line);padding:13px 16px}
.panel .ph h2{font-size:14.5px;letter-spacing:-.012em}
.panel .ph .so{font-size:12px;color:var(--muted)}

/* Tables: quieter headers, tighter rules, a calm hover. */
table th{font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);
  font-weight:600;background:var(--canvas);border-bottom:1px solid var(--line);padding:9px 14px}
table td{padding:10px 14px;border-bottom:1px solid var(--line);font-size:13.5px}
table tbody tr:last-child td{border-bottom:none}
table tbody tr:hover td{background:rgba(4,76,140,.028)}

/* Buttons: one primary weight, everything else recedes. */
.btn{border:1px solid var(--line);background:var(--surface);border-radius:9px;
  padding:8px 13px;font-weight:600;font-size:13px;transition:border-color .15s,background .15s}
.btn:hover{border-color:var(--petrol)}
.btn.primary{background:var(--amber);border-color:var(--amber);color:#fff}
.btn.primary:hover{background:var(--amber-dk);border-color:var(--amber-dk)}
.btn.sm{padding:6px 11px;font-size:12.5px;border-radius:8px}
.btn.gh{background:transparent;border-color:transparent;color:var(--petrol)}
.btn.gh:hover{background:rgba(4,76,140,.06);border-color:transparent}

/* Status pills: colour states a fact, it never decorates. */
.pill{font-size:11px;font-weight:700;letter-spacing:.02em;padding:3px 9px;border-radius:6px;
  border:1px solid transparent}
.pill.green{background:var(--green-soft);color:var(--green);border-color:rgba(18,122,91,.18)}
.pill.amber{background:var(--amber-soft);color:var(--amber-dk);border-color:rgba(228,84,36,.2)}
.pill.red{background:var(--red-soft);color:var(--red);border-color:rgba(192,57,43,.18)}
.pill.grey{background:var(--canvas);color:var(--muted);border-color:var(--line)}

/* Sidebar: brand navy, with the active item marked in the brand orange. */
.nav a{border-radius:8px;font-size:13.5px}
.nav a.active{background:var(--amber);color:#fff;font-weight:600}
.nav .g{letter-spacing:.11em;font-size:9.5px;color:rgba(255,255,255,.45)}
.brand .mark{background:var(--amber);color:#fff}

/* Inputs: a visible, brand-coloured focus ring - keyboard users need it. */
input,select,textarea{border:1px solid var(--line);border-radius:9px;padding:9px 11px;
  background:var(--surface);color:var(--ink);transition:border-color .15s,box-shadow .15s}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--petrol);
  box-shadow:0 0 0 3px rgba(4,76,140,.14)}
a:focus-visible,button:focus-visible,.btn:focus-visible{outline:2px solid var(--petrol);
  outline-offset:2px;border-radius:8px}

/* KPI cards: the number leads, the label supports it. */
.kpi{border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}
.kpi .l{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:600}
.kpi .v{font-size:25px;font-weight:600;letter-spacing:-.02em;margin-top:4px}
.kpi .s{font-size:11.5px;color:var(--muted)}

/* Menubar */
.mbar{background:var(--petrol);border-radius:10px}
.mb-top{font-size:13px;font-weight:600;border-radius:7px}
.mb-top.on{background:var(--amber);color:#fff}

h1,h2,h3{letter-spacing:-.015em}

@media print{.sidebar,.topbar,.mbar,.pager,.listbar{display:none}
  .main{margin-left:0}.panel{box-shadow:none;border-color:#ccc}}

/* ============================================================
   ODOO SKIN — global reskin of the whole backend to match Odoo's
   look (light grey canvas, flat white sheets, control-panel header,
   list/form views, square buttons). Brand petrol/amber kept as
   accents. Appended last so it overrides the base theme; HTML is
   unchanged, so every screen re-skins automatically.
   ============================================================ */
:root{
  --canvas:#f5f6f8;        /* Odoo grey app background */
  --surface:#ffffff;
  --line:#dcdfe4;          /* Odoo hairline */
  --ink:#1f2933; --muted:#6b7681;
  --hover:#f1f3f5;
  --radius:6px;            /* Odoo sheets are near-square */
  --shadow:0 1px 2px rgba(24,39,54,.05);
  --ring:rgba(4,76,140,.25);
  --fd:'Inter',system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; /* Odoo uses a plain sans for titles too */
}
body.dark{--canvas:#0b1520;--surface:#111e2b;--line:#22323f;--hover:#16283a}
body{font-size:13px}

/* ---- Sidebar → brand logo color (petrol), Odoo structure kept ---- */
.sidebar{background:var(--petrol);color:#dbe6ef;border-right:1px solid rgba(0,0,0,.12)}
.brand{border-bottom:1px solid rgba(255,255,255,.10)}
.brand .logo{color:#fff}
.brand .mark{background:linear-gradient(135deg,var(--amber),#F2C063);color:#03294f}
.brand .sub{color:#9db6cc}
.nav .g,.navsec .gbtn{color:#8fb0cc!important}
.navsec .gbtn:hover{color:#e6eff7}
.nav a{color:#cdddea;border-radius:6px;font-size:13px}
.nav a:hover{background:rgba(255,255,255,.08);color:#fff}
.nav a.active{background:rgba(228,84,36,.18);color:#fff;font-weight:600;box-shadow:inset 3px 0 0 var(--amber)}
.nav a.active .ic{color:var(--amber)}
.nav a .ic{color:#9db6cc}

/* ---- Control panel (top bar) ---- */
.top{height:52px;box-shadow:0 1px 0 var(--line);border-bottom:1px solid var(--line)}
.top h1{font-size:16px;font-weight:600;letter-spacing:-.01em}
.apps-btn{border-radius:5px}

/* ---- Sheets / panels / cards → flat Odoo ---- */
.panel,.kpi,.wg,.cat,.sbtn,.qa,.o-sheet,.o-stat,.mdcpay-box{border-radius:var(--radius)}
.panel{box-shadow:var(--shadow);border-color:var(--line)}
.kpi,.wg,.cat,.sbtn{box-shadow:none;border-color:var(--line)}
.kpi:hover,.wg:hover,.sbtn:hover,.cat:hover{box-shadow:0 2px 8px rgba(24,39,54,.09)}
.ph{padding:12px 16px}
.ph h2{font-family:var(--fd);font-size:15px;font-weight:600;letter-spacing:-.01em}
.pad{padding:14px 16px}

/* ---- Buttons → Odoo (squarer, lighter) ---- */
.btn{border-radius:5px;padding:6px 12px;font-weight:500;font-size:13px;border-color:#ced2d8;background:#fff;color:#374151}
.btn:hover{background:#f3f4f6;border-color:#b6bcc4}
.btn.sm{padding:4px 9px;font-size:12px}
.btn.primary{background:var(--amber);border-color:var(--amber);color:#fff;font-weight:600;box-shadow:none}
.btn.primary:hover{background:var(--amber-dk);border-color:var(--amber-dk)}
/* a petrol variant for confirm-type primaries reads very Odoo */
.btn.pblue{background:var(--petrol);border-color:var(--petrol);color:#fff}
.btn.pblue:hover{filter:brightness(1.08)}

/* ---- List views → Odoo table ---- */
table{font-size:13px}
thead th{background:#fbfbfc;color:#6b7681;text-transform:none;letter-spacing:0;font-weight:600;font-size:12px;padding:9px 14px;border-bottom:1px solid var(--line)}
tbody td{padding:9px 14px;border-bottom:1px solid #eef0f2}
tbody tr:hover{background:#f6f7f9}

/* ---- Badges / pills → Odoo ---- */
.pill{border-radius:4px;font-size:11px;padding:2px 7px;font-weight:600}

/* ---- Inputs → Odoo ---- */
input,select,textarea{border-radius:5px!important;border-color:#ced2d8}

/* ---- Chevron workflow → flatter ---- */
.chev{border-radius:0}
.chev.active{background:var(--petrol)}

/* ---- Thin scrollbars (Odoo) ---- */
*{scrollbar-width:thin;scrollbar-color:#c4c9d0 transparent}
*::-webkit-scrollbar{width:9px;height:9px}
*::-webkit-scrollbar-thumb{background:#c4c9d0;border-radius:6px}
*::-webkit-scrollbar-thumb:hover{background:#a7adb6}

/* ================= READABILITY PASS ================= */
/* Larger, higher-contrast, more breathing room across the app. */
:root{--ink:#111C24;--muted:#57646E}
body{font-size:15px;line-height:1.58;letter-spacing:.1px}
input,select,textarea,.btn{font-size:14px}
/* tables: bigger text + more row height */
table{font-size:14px}
thead th{font-size:12.5px;color:#4A5760;padding:12px 16px}
tbody td{padding:12px 16px;line-height:1.5}
/* headings a touch larger */
.top h1{font-size:19px}
.ph h2{font-size:16px}
.panel .ph{padding:14px 16px}
/* small uppercase labels were tiny — bump for legibility */
.kpi .l,.sec-lbl,.xx-stat .l,.iv-stat .l,.pu-stat .l,.hr-stat .l,.lr-stat .l,.ph-stat .l{font-size:11.5px;letter-spacing:.4px}
.kpi .v,.wg-v{font-size:25px}
/* stat-card numbers a bit bigger everywhere */
.iv-stat .v,.pu-stat .v,.hr-stat .v,.lr-stat .v,.ph-stat .v,.xx-stat .v{font-size:23px}
/* status pills legible */
.pill{font-size:11.5px;padding:3px 9px}
/* sidebar nav links slightly larger */
.nav a{font-size:14px}
/* form fields taller/roomier */
input,select,textarea{padding:9px 12px}
/* muted helper text never below 12px */
small,.chip small,.kpi .s,.ph .so{font-size:12px}
/* links inside content get clearer weight */
.idlink,a.idlink{font-weight:600}
@media(max-width:640px){body{font-size:15.5px}}

/* ================= ODOO FORM VIEW ================= */
.o-form{max-width:1040px;margin:0 auto}
.o-formbar{position:sticky;top:58px;z-index:20;display:flex;align-items:center;gap:14px;
  background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:9px 14px;margin-bottom:16px;box-shadow:var(--shadow)}
.o-formbar-actions{display:flex;gap:8px}
.o-formbar-crumb{color:var(--muted);font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.o-sheet{background:var(--surface);border:1px solid var(--line);border-radius:12px;
  box-shadow:0 1px 3px rgba(2,48,90,.08);padding:26px 30px}
.o-sheet-title{font-family:var(--fd);font-size:22px;font-weight:600;color:var(--ink);
  margin-bottom:20px;padding-bottom:14px;border-bottom:1px solid var(--line)}
.o-sheet .fg{gap:16px 24px}
.o-sheet .fld label{color:var(--muted);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
body.dark .o-sheet .fld label{color:var(--teal)}
.o-sheet .fld input,.o-sheet .fld select,.o-sheet .fld textarea{padding:10px 12px;font-size:14px}
.o-sheet .fld textarea{min-height:64px}
@media(max-width:860px){.o-formbar{top:0}.o-sheet{padding:18px 16px}}

/* ================= ODOO RECORD (detail) VIEW ================= */
.o-record{padding-top:16px}
.o-statusbar{display:flex;justify-content:flex-end;margin-bottom:12px}
.o-stat{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;color:var(--muted);border:1px solid var(--line);padding:5px 13px}
.o-stat:first-child{border-radius:6px 0 0 6px}
.o-stat:last-child{border-radius:0 6px 6px 0;border-left:0}
.o-stat.on{background:var(--petrol);color:#fff;border-color:var(--petrol)}
.o-rec-head{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding-bottom:16px;border-bottom:1px solid var(--line);margin-bottom:16px}
.o-rec-title{font-family:var(--fd);font-size:24px;font-weight:600;color:var(--ink);line-height:1.15}
.o-rec-sub{color:var(--muted);font-size:13px;margin-top:3px}
.o-kpis{display:flex;gap:24px;margin-left:auto;text-align:right}
.o-kpi span{display:block;font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}
.o-kpi b{font-size:18px;font-family:var(--fd)}
.o-fields{display:grid;grid-template-columns:repeat(3,1fr);gap:14px 26px}
.o-fld{display:flex;flex-direction:column;gap:3px}
.o-fl{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}
.o-fv{font-size:14px;color:var(--ink);font-weight:500}
.o-alert{background:var(--red-soft);color:var(--red);border-radius:8px;padding:9px 13px;font-size:13px;font-weight:600;margin-bottom:16px}
@media(max-width:700px){.o-fields{grid-template-columns:1fr 1fr}.o-kpis{margin-left:0;width:100%;justify-content:space-between;gap:12px}}

/* ================= STANDARDIZATION PASS (final — one consistent look) ================= */
/* Buttons — single canonical style across every page */
.btn{border:1px solid var(--line);background:var(--surface);color:var(--ink);
  padding:8px 14px;border-radius:8px;font-weight:600;font-size:13.5px;line-height:1.1;
  display:inline-flex;align-items:center;gap:6px;cursor:pointer;text-decoration:none;
  transition:background .15s,border-color .15s,box-shadow .15s,transform .05s}
.btn:hover{background:#eef2f6;border-color:#cfd6de}
.btn:active{transform:translateY(.5px)}
.btn.sm{padding:5px 10px;font-size:12.5px;border-radius:7px}
.btn.primary{background:var(--amber);border-color:var(--amber);color:#fff;box-shadow:0 1px 2px rgba(196,63,19,.22)}
.btn.primary:hover{background:var(--amber-dk);border-color:var(--amber-dk);filter:none}
.btn.pblue{background:var(--petrol);border-color:var(--petrol);color:#fff;box-shadow:none}
.btn.pblue:hover{background:var(--petrol);filter:brightness(1.08)}
.btn.ok{color:var(--green);border-color:var(--green-soft);background:var(--surface)}
.btn.ok:hover{background:rgba(31,166,109,.08);border-color:var(--green)}
.btn.gh{background:transparent;border-color:transparent;color:var(--petrol);padding:6px 9px}
.btn.gh:hover{background:rgba(4,76,140,.07);border-color:transparent;color:var(--petrol)}
.btn.danger{color:var(--red);border-color:#eab8b2;background:var(--surface)}
.btn.danger:hover{background:#fdecec;border-color:var(--red)}
/* Panels & headers — consistent spacing everywhere */
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:var(--shadow);margin-bottom:16px}
.panel .ph,.ph{display:flex;align-items:center;gap:12px;padding:14px 16px;border-bottom:1px solid var(--line)}
.panel .ph h2,.ph h2{font-family:var(--fd);font-size:15px;font-weight:600;letter-spacing:-.01em;margin:0}
.ph .so,.panel .ph .so{font-size:12px;color:var(--muted)} .ph .sp{flex:1}
.pad{padding:16px}
.tw{padding:2px}
/* Pills — one shape/size */
.pill{display:inline-block;padding:3px 9px;border-radius:6px;font-size:11px;font-weight:700;
  letter-spacing:.02em;line-height:1.5}
/* Stat cards — unify every module's band to identical metrics */
.iv-stat,.pu-stat,.hr-stat,.lr-stat,.ph-stat,.cc-stat,.coa-stat,.xx-stat,.fa-stat,.kpi{
  border-radius:10px;padding:12px 14px;border:1px solid var(--line);box-shadow:var(--shadow)}
.iv-stat .l,.pu-stat .l,.hr-stat .l,.lr-stat .l,.ph-stat .l,.cc-stat .l,.coa-stat .l,.xx-stat .l{
  font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}
.iv-stat .v,.pu-stat .v,.hr-stat .v,.lr-stat .v,.ph-stat .v,.cc-stat .v,.coa-stat .v,.xx-stat .v{
  font-size:22px;font-weight:800;font-family:var(--fd);line-height:1.15;margin-top:2px}
/* Section labels + form grid gaps consistent */
.sec-lbl{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px}
.fg{gap:14px 20px}
/* Consistent page gutter */
.content{padding:20px 22px}
@media(max-width:860px){.content{padding:14px}}
/* Inputs — one field look */
input,select,textarea{border:1px solid var(--line);border-radius:8px;padding:9px 12px;font-size:14px;background:var(--surface);color:var(--ink)}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--petrol);box-shadow:0 0 0 3px rgba(4,76,140,.10)}
"""

NAVDEF = [
 ("Overview", [
    ("dashboard", "Dashboard", "M3 13h8V3H3zM13 21h8V3h-8zM3 21h8v-6H3z"),
    ("apps", "All Modules", "M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z"),
    ("chat", "Chat", "M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"),
 ]),
 ("Clinical", [
    ("patients", "Patients", "M12 8a4 4 0 100-8 4 4 0 000 8zM4 21c0-4 4-6 8-6s8 2 8 6"),
    ("queue", "Reception Queue", "M4 6h16M4 12h10M4 18h7M19 15l3 3-3 3"),
    ("referrals", "Doctor Request", "M22 2L11 13M22 2l-7 20-4-9-9-4z"),
    ("consult", "Consultation", "M8 2h8a2 2 0 012 2v16l-6-3-6 3V4a2 2 0 012-2z"),
    ("doctors", "Referring Doctors", "M12 8a4 4 0 100-8 4 4 0 000 8zM4 21c0-4 4-6 8-6s8 2 8 6"),
    ("donors", "Blood Bank", "M12 21C7 17 4 13 4 9a8 8 0 0116 0c0 4-3 8-8 12z"),
    ("vaccinations", "Vaccination", "M19 5l-2-2m1 3l-7 7m-4 8l-3-3 8-8 3 3-8 8zM14 4l6 6"),
 ]),
 ("Diagnostics", [
    ("lab", "Laboratory", "M9 2v6l-5 9a2 2 0 002 3h12a2 2 0 002-3l-5-9V2M8 2h8"),
    ("radiology", "Radiology", "M12 2a10 10 0 100 20 10 10 0 000-20zM12 6v6l4 2"),
 ]),
 ("Billing", [
    ("invoices", "Billing & Cashier", "M6 2h9l5 5v15H6zM9 12h6M9 16h6M9 8h2"),
    ("dailytx", "Daily Transactions", "M4 4v16h16M8 16l3-4 3 3 4-6"),
    ("payables", "Commission Payables", "M3 6h18v12H3zM3 10h18M7 15h4"),
 ]),
 ("Accounting", [
    ("acctdash", "Accounting Center", "M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M6 2h12a2 2 0 012 2v16a2 2 0 01-2 2H6a2 2 0 01-2-2V4a2 2 0 012-2z"),
    ("genledger", "General Ledger", "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"),
    ("coa", "Chart of Accounts", "M4 6h16M4 10h16M4 14h16M4 18h16"),
    ("jentries", "Journal Entries", "M8 2h8a2 2 0 012 2v16l-6-3-6 3V4a2 2 0 012-2z"),
    ("finance", "Financial Statements", "M4 4v16h16M8 16l3-4 3 3 4-6"),
    ("bankrec", "Bank Reconciliation", "M3 10h18M7 15h4M4 4h16v16H4z"),
 ]),
 ("Pharmacy & Inventory", [
    ("pharmacy", "Pharmacy", "M10 3H6a2 2 0 00-2 2v4l8 8 6-6-8-8zM3 21h18"),
    ("suppliers", "Inventory", "M20 7H4l1 13h14zM9 7V4h6v3M3 9h18"),
 ]),
 ("Management", [
    ("employees", "Human Resources", "M9 8a3 3 0 100-6 3 3 0 000 6zM2 21c0-3 3-5 7-5s7 2 7 5"),
    ("assets", "Assets & Maintenance", "M14.7 6.3a5 5 0 00-6.6 6.6L3 18v3h3l5.1-5.1a5 5 0 006.6-6.6l-3 3-2.6-2.6 3-3z"),
    ("fa_dash", "Fixed Assets", "M3 21h18M5 21V7l7-4 7 4v14M9 9h.01M15 9h.01M9 13h.01"),
    ("logistics", "Logistics", "M1 3h15v13H1zM16 8h4l3 3v5h-7M5.5 19a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM18.5 19a1.5 1.5 0 100-3 1.5 1.5 0 000 3z"),
    ("sops", "SOPs & Documents", "M6 2h9l5 5v15H6zM9 12h6M9 16h6"),
    ("incidents", "Incidents", "M12 2L2 20h20L12 2zm0 7v5m0 3v.1"),
 ]),
 ("Administration", [
    ("reports", "Reports", "M4 4v16h16M8 16l3-4 3 3 4-6"),
    ("record_options", "Record Options", "M4 4h16v16H4zM8 9h8M8 13h5M8 17h8"),
    ("users", "Users", "M9 8a3 3 0 100-6 3 3 0 000 6zM2 21c0-3 3-5 7-5M16 4a3 3 0 010 7M22 21c0-3-2-5-5-5"),
    ("branches", "Branches", "M3 21h18M5 21V7l7-4 7 4v14M9 21v-6h6v6"),
    ("audit", "Audit Log", "M9 12h6M9 16h6M6 2h9l5 5v13H6zM9 8h2"),
    ("errorlog", "Error Log", "M12 2L2 20h20L12 2zm0 7v5m0 3v.1"),
    ("syshealth", "System Health", "M3 12h4l3 8 4-16 3 8h4"),
    ("svcmgmt", "Service Management", "M20 7h-9M14 17H5M17 17a3 3 0 100-6 3 3 0 000 6zM7 7a3 3 0 100 6 3 3 0 000-6z"),
    ("settings", "Settings", "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 13a7.6 7.6 0 000-2l2-1.5-2-3.5-2.4 1a7 7 0 00-1.7-1L14 2h-4l-.8 2.5a7 7 0 00-1.7 1l-2.4-1-2 3.5L3.6 11a7.6 7.6 0 000 2L1.6 14.5l2 3.5 2.4-1a7 7 0 001.7 1L10 22h4l.8-2.5a7 7 0 001.7-1l2.4 1 2-3.5z"),
 ]),
]

GROUPS = {
 'billing':    ('Billing & Cashier', [('invoices','Invoices'),('dailytx','Daily Transactions'),('payalloc','Receive Payment'),('dailytx','Daily Transactions'),('creditnotes','Credit Notes'),('cashclose','Daily Cash Closing'),('commission','Doctor Commission'),('services','Service Catalog')]),
 'inventory':  ('Inventory',  [('suppliers','Suppliers'),('inventory','Supplies'),('purchases','Purchase Orders'),('debitnotes','Debit Notes'),('warehouses','Warehouses'),('transfers','Stock Transfers'),('stockadj','Stock Adjustments'),('consumption','Consumption Report')]),
 'accounting': ('Accounting', [('acct','Dashboard'),('findash','Financial Dashboard'),('payables','Commission Payables'),('accounts','Chart of Accounts'),('journal','Journal Entries'),('recurjournals','Recurring Journals'),('genledger','General Ledger'),('partnerledger','Partner Ledger'),('expenses','Expenses'),('cashflow','Cash Flow'),('araging','AR Aging'),('apaging','AP Aging'),('banks','Bank Accounts'),('bankrecon','Bank Reconciliation'),('budgets','Budgets'),('budgetreport','Budget vs Actual'),('costcenters','Cost Centers'),('ccreport','Cost Center Report'),('ratios','Financial Ratios'),('revreport','Revenue Analysis'),('taxreport','Tax Report'),('fiscal','Fiscal Periods'),('currencies','Currencies'),('finance','Financial Statements')]),
 'hr':         ('Human Resources', [('employees','Employees'),('attendance','Attendance'),('leave','Leave'),('payroll','Payroll'),('advances','Salary Advances'),('loans','Employee Loans')]),
 'assets':     ('Assets & Maintenance', [('maintdash','Overview'),('assets','Asset Register'),('maintenance','Maintenance Jobs')]),
 'reports':    ('Reports', [('reports','Overview'),('summary','Summary (date range)'),('revenue','Revenue Analysis'),('radfees','Radiologist Fees'),('branchcmp','Branch Comparison')]),
}
GROUPS['fixedassets'] = ('Fixed Assets', [('fa_dash','Dashboard'),('fa_register','Asset Register'),('fa_purchase','Purchase Assets'),('fa_categories','Asset Categories'),('fa_depreciation','Depreciation Schedule'),('fa_depjournal','Depreciation Journal'),('fa_transfer','Asset Transfer'),('fa_maintenance','Asset Maintenance'),('fa_disposal','Asset Disposal'),('fa_revaluation','Asset Revaluation'),('fa_reports','Reports'),('fa_settings','Settings')])
KEY2GROUP = {k:g for g,(lb,its) in GROUPS.items() for k,_ in its}
GROUPS['donors']=[('donors','Donors'),('bloodunits','Blood Units')]
GROUPS['bloodunits']=GROUPS['donors']
GROUPS['findash']=[('findash','Dashboard'),('revreport','Revenue Analysis'),('recurjournals','Recurring')]
GROUPS['revreport']=GROUPS['findash']; GROUPS['recurjournals']=GROUPS['findash']
GROUPS['sops']=[('sops','SOPs'),('incidents','Incidents'),('audits','Internal Audits'),('feedback','Patient Feedback')]
GROUPS['incidents']=GROUPS['sops']; GROUPS['audits']=GROUPS['sops']; GROUPS['feedback']=GROUPS['sops']

# --- Odoo-style navigation: human labels for keys/groups (built defensively,
#     because GROUPS holds a mix of (label, items) tuples and plain item-lists) --
MODULE_LABEL = {}
for _grp, _items in NAVDEF:
    for _t in _items:
        if len(_t) >= 2:
            MODULE_LABEL.setdefault(_t[0], _t[1])
for _g, _v in GROUPS.items():
    _its = _v[1] if (isinstance(_v, tuple) and len(_v) == 2 and isinstance(_v[1], list)) else (_v if isinstance(_v, list) else [])
    for _it in _its:
        if isinstance(_it, (list, tuple)) and len(_it) >= 2:
            MODULE_LABEL.setdefault(_it[0], _it[1])
GROUP_LABEL = {_g: _v[0] for _g, _v in GROUPS.items()
               if isinstance(_v, tuple) and len(_v) == 2 and isinstance(_v[0], str)}

def _group_home(g):
    """First module in group g the current user may open (for breadcrumb link)."""
    _v = GROUPS.get(g)
    _its = _v[1] if (isinstance(_v, tuple) and len(_v) == 2) else (_v if isinstance(_v, list) else [])
    for _it in _its:
        if isinstance(_it, (list, tuple)) and _it and can(_it[0]):
            return url_for('modules.module', mod=_it[0])
    return url_for('dash.dashboard')

def _crumbbar(active, title, crumbs=None):
    """Odoo-style breadcrumb + Back button shown at the top of every page.
    Pass `crumbs` as a list of (label, url_or_None) for a rich trail on detail
    pages; otherwise a trail is derived from the active module and its group."""
    parts = [f"<a href='{url_for('dash.dashboard')}'>Home</a>"]
    if crumbs:
        for lb, href in crumbs:
            parts.append(f"<a href='{h(href)}'>{h(lb)}</a>" if href else f"<span>{h(lb)}</span>")
    else:
        g = KEY2GROUP.get(active)
        if g and g in GROUP_LABEL:
            parts.append(f"<a href='{_group_home(g)}'>{h(GROUP_LABEL[g])}</a>")
        parts.append(f"<span>{h(MODULE_LABEL.get(active) or title)}</span>")
    trail = "<span class='sep'>›</span>".join(parts)
    home = url_for('dash.dashboard')
    back = (f"<a class='nav-back' title='Back'"
            f" href=\"javascript:if(history.length>1){{history.back()}}else{{location.assign('{home}')}}\">← Back</a>")
    return f"<div class='navbar noprint'><nav class='crumbs'>{trail}</nav><div class='sp'></div>{back}</div>"

NAV_CSS = """
.navbar{display:flex;align-items:center;gap:10px;margin:0 0 14px;flex-wrap:wrap}
.crumbs{display:flex;align-items:center;gap:6px;font-size:12.5px;flex-wrap:wrap;line-height:1.4}
.crumbs a{color:var(--muted);text-decoration:none;padding:2px 5px;border-radius:6px;transition:.12s}
.crumbs a:hover{color:var(--petrol);background:var(--canvas)}
.crumbs>span{color:var(--ink);font-weight:600;padding:2px 3px}
.crumbs .sep{color:var(--line);font-weight:400;padding:0}
.navbar .sp{flex:1}
.nav-back{display:inline-flex;align-items:center;gap:5px;font-size:12.5px;font-weight:600;color:var(--petrol);text-decoration:none;border:1px solid var(--line);background:var(--surface);padding:6px 12px;border-radius:9px;transition:.15s;white-space:nowrap}
.nav-back:hover{border-color:var(--petrol);background:var(--canvas)}
/* client-side record tabs (patient hub etc.) */
.rtabs{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid var(--line);margin:0 0 14px}
.rtabs button{border:none;background:none;font-family:var(--fb);font-size:13px;font-weight:600;color:var(--muted);padding:9px 14px;cursor:pointer;border-bottom:2.5px solid transparent;margin-bottom:-1px;border-radius:7px 7px 0 0}
.rtabs button:hover{color:var(--petrol);background:var(--canvas)}
.rtabs button.on{color:var(--petrol);border-bottom-color:var(--amber)}
.tabpane[hidden]{display:none}
/* vertical timeline */
.tl{position:relative;margin:4px 0 4px 6px;padding-left:22px}
.tl::before{content:"";position:absolute;left:5px;top:4px;bottom:4px;width:2px;background:var(--line)}
.tl-i{position:relative;padding:0 0 15px 4px}
.tl-i::before{content:"";position:absolute;left:-22px;top:2px;width:11px;height:11px;border-radius:50%;background:var(--surface);border:2.5px solid var(--petrol)}
.tl-i.amber::before{border-color:var(--amber)}.tl-i.green::before{border-color:var(--green)}
.tl-d{font-size:11px;color:var(--muted);font-weight:600}
.tl-t{font-size:13.5px;color:var(--ink);font-weight:600;margin-top:1px}
.tl-t a{color:var(--petrol);text-decoration:none}.tl-t a:hover{text-decoration:underline}
.tl-s{font-size:12px;color:var(--muted)}
@media print{.navbar,.rtabs{display:none!important}.tabpane[hidden]{display:block!important}}
.idlink{color:var(--petrol);text-decoration:none;font-weight:600;border-bottom:1px dotted var(--petrol)}
.idlink:hover{color:var(--amber-dk);border-bottom-color:var(--amber)}
.rr-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:10px}
.rr-tile{display:flex;align-items:center;gap:11px;padding:12px 14px;border:1px solid var(--line);border-radius:11px;text-decoration:none;background:var(--surface);transition:.15s}
.rr-tile:hover{border-color:var(--petrol);background:var(--canvas);transform:translateY(-1px);box-shadow:0 4px 12px rgba(2,48,90,.07)}
.rr-tile .rr-ic{font-size:21px;flex:none}
.rr-tile .rr-c{font-size:19px;font-weight:700;color:var(--ink);font-family:var(--fd)}
.rr-tile .rr-l{font-size:12px;color:var(--muted);font-weight:600}
.smartbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.recent-wrap{position:relative;display:inline-block;margin-right:4px}
.recent-menu{display:none;position:absolute;right:0;top:calc(100% + 6px);width:274px;background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:0 12px 34px rgba(2,48,90,.16);z-index:120;padding:5px}
.recent-wrap.open .recent-menu{display:block}
.recent-h{font-size:10.5px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:var(--muted);padding:8px 10px 6px}
.recent-menu a{display:flex;align-items:center;gap:9px;padding:8px 10px;border-radius:8px;color:var(--ink);text-decoration:none;font-size:13px}
.recent-menu a:hover{background:var(--canvas);color:var(--petrol)}
.recent-menu .ri{width:20px;text-align:center;flex:none}
.pvw-back{display:none;position:fixed;inset:0;background:rgba(4,20,40,.30);z-index:200;align-items:center;justify-content:center;padding:16px}
.pvw-back.show{display:flex}
.pvw{background:var(--surface);width:346px;max-width:94vw;border-radius:14px;box-shadow:0 22px 60px rgba(2,48,90,.32);overflow:hidden;animation:pvwIn .14s ease}
@keyframes pvwIn{from{transform:translateY(8px);opacity:.4}to{transform:none;opacity:1}}
.pvw h4{margin:0;padding:13px 16px;background:var(--petrol);color:#fff;font-family:var(--fd);font-size:15px;display:flex;justify-content:space-between;align-items:center}
.pvw .pb{padding:10px 16px}
.pvw .pr{display:flex;justify-content:space-between;gap:12px;padding:6px 0;border-bottom:1px solid var(--line);font-size:13.5px}
.pvw .pr:last-child{border-bottom:none}
.pvw .pf{display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--line);background:var(--canvas)}
.pvw .x{cursor:pointer;background:none;border:none;color:#fff;font-size:19px;line-height:1}
@media print{.recent-wrap,.pvw-back{display:none!important}}
"""

def track_view(kind, rid, label, url):
    """Remember a viewed record for the 'Recently viewed' menu (best-effort)."""
    try:
        rec = [x for x in session.get('recent', []) if not (x.get('k') == kind and x.get('i') == rid)]
        rec.insert(0, {'k': kind, 'i': rid, 'l': (str(label) or '')[:46], 'u': url})
        session['recent'] = rec[:12]
        session.modified = True
    except Exception:
        pass

def recent_list():
    return session.get('recent', []) or []

_REC_ICON = {'patient': '•', 'invoice': '•', 'receipt': '•', 'lab': '•', 'radiology': '•', 'report': '•'}

def _fav_menu(u, title=''):
    """Favorites dropdown: a star toggle for the current page + the user's pinned pages."""
    from ..models import Favorite
    favs = Favorite.query.filter_by(username=u.username).order_by(Favorite.id.desc()).limit(25).all() if u else []
    cur_url = (request.full_path.rstrip('?') if request else '') or '/'
    is_fav = any(f.url == cur_url for f in favs)
    star_ic = "<svg width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' style='vertical-align:middle'><polygon points='12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2'></polygon></svg>"
    star_filled = "<svg width='14' height='14' viewBox='0 0 24 24' fill='currentColor' stroke='currentColor' stroke-width='2' style='vertical-align:middle'><polygon points='12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2'></polygon></svg>"
    items = ''.join(
        f"<a href='{h(f.url)}'><span class='ri'>{star_filled}</span><span>{h(f.label)}</span></a>" for f in favs
    ) or "<div style='padding:12px 14px;color:var(--muted);font-size:12.5px'>No favorites yet — star a page to pin it here.</div>"
    toggle = (
        f"<form method='post' action='{url_for('dash.favorite_toggle')}' style='padding:8px 10px;border-bottom:1px solid var(--line)'>"
        f"<input type='hidden' name='url' value=\"{h(cur_url)}\"><input type='hidden' name='label' value=\"{h(title)}\">"
        f"<input type='hidden' name='next' value=\"{h(cur_url)}\">"
        f"<button class='btn sm' style='width:100%'>{'Remove from favorites' if is_fav else 'Add this page'}</button></form>")
    return ("<div class='recent-wrap'><button type='button' class='btn sm' title='Favorites' "
            f"onclick=\"this.parentNode.classList.toggle('open')\">{star_filled if is_fav else star_ic}</button>"
            f"<div class='recent-menu'><div class='recent-h'>Favorites</div>{toggle}{items}</div></div>")


def next_step(url, label, hint=''):
    """A prominent 'Next Step' call-to-action banner shown after a completed task,
    so users advance through the workflow without hunting for the next page."""
    if not url:
        return ''
    hint_html = f"<div style='font-size:12px;color:var(--muted)'>{h(hint)}</div>" if hint else ''
    return (
        "<div class='panel' style='border-left:4px solid var(--green);background:linear-gradient(90deg,rgba(31,166,109,.06),transparent)'>"
        "<div class='pad' style='display:flex;align-items:center;gap:14px;flex-wrap:wrap'>"
        "<div style='flex:1;min-width:180px'>"
        "<div style='font-size:11px;color:var(--green);font-weight:700;letter-spacing:1px;text-transform:uppercase'>✓ Next step</div>"
        f"<div style='font-size:15px;font-weight:600;color:var(--ink)'>{h(label)}</div>{hint_html}</div>"
        f"<a class='btn primary' href='{h(url)}' style='font-size:14px;padding:10px 20px'>{h(label)} →</a>"
        "</div></div>")


def _recent_menu():
    items = recent_list()
    clock_ic = "<svg width='15' height='15' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' style='vertical-align:middle'><circle cx='12' cy='12' r='10'></circle><polyline points='12 6 12 12 16 14'></polyline></svg>"
    if not items:
        inner = "<div style='padding:12px 14px;color:var(--muted);font-size:12.5px'>No recent records yet.</div>"
    else:
        inner = ''.join(f"<a href='{h(x['u'])}'><span class='ri'>{_REC_ICON.get(x['k'],'•')}</span><span>{h(x['l'])}</span></a>" for x in items)
    return ("<div class='recent-wrap'><button type='button' class='btn sm' title='Recently viewed' "
            f"onclick=\"this.parentNode.classList.toggle('open')\">{clock_ic}</button>"
            f"<div class='recent-menu'><div class='recent-h'>Recently viewed</div>{inner}</div></div>")

def id_link(kind, rid, text=None):
    """Clickable record ID — resolves kind+id to its detail page when one exists."""
    routes = {'patient': ('patients.patient_detail', 'pid'),
              'invoice': ('billing.invoice_view', 'iid'),
              'receipt': ('billing.receipt_view', 'rid')}
    txt = str(text if text is not None else rid)
    if kind in routes and rid:
        ep, arg = routes[kind]
        try:
            return f"<a class='idlink' href='{url_for(ep, **{arg: rid})}'>{h(txt)}</a>"
        except Exception:
            pass
    return h(txt)

def smartbar(buttons):
    """Odoo-style quick-navigation bar. buttons: list of (label, url, style, new_tab)."""
    bs = ''.join(
        f"<a class='btn sm {sty}' href='{u}'{' target=\"_blank\"' if blank else ''}>{lb}</a>"
        for lb, u, sty, blank in buttons if u)
    return f"<div class='panel'><div class='pad smartbar'>{bs}</div></div>" if bs else ''

PVW_HTML = ("<div class='pvw-back' id='pvwBack' onclick=\"if(event.target===this)this.classList.remove('show')\">"
            "<div class='pvw' id='pvwBox'></div></div>"
            "<script>function closePvw(){document.getElementById('pvwBack').classList.remove('show');}"
            "async function openPvw(k,i){try{var r=await fetch('/preview/'+k+'/'+i);if(!r.ok)throw 0;var d=await r.json();"
            "var rows=(d.rows||[]).map(function(x){return \"<div class='pr'><span>\"+x[0]+\"</span><b>\"+x[1]+\"</b></div>\";}).join('');"
            "var btns=(d.actions||[]).map(function(a){return \"<a class='btn sm \"+(a[2]||'')+\"' href='\"+a[1]+\"'\"+(a[3]?\" target='_blank'\":\"\")+\">\"+a[0]+\"</a>\";}).join('');"
            "document.getElementById('pvwBox').innerHTML=\"<h4>\"+d.title+\"<button class='x' onclick='closePvw()'>&times;</button></h4><div class='pb'>\"+rows+\"</div><div class='pf'>\"+btns+\"</div>\";"
            "document.getElementById('pvwBack').classList.add('show');}catch(e){location.assign('/'+k+'/'+i);}}"
            "document.addEventListener('click',function(e){var el=e.target.closest('[data-prev]');if(el){e.preventDefault();var v=el.getAttribute('data-prev').split(':');openPvw(v[0],v[1]);}});"
            "document.addEventListener('keydown',function(e){if(e.key==='Escape')closePvw();});</script>")


def _app_launcher(active=''):
    """One place for everything — a searchable grid of every module the user can open."""
    # flatten NAVDEF + GROUPS subitems into a single searchable list of (label, href, icon-path, group)
    seen = set()
    cats = []
    for group, items in NAVDEF:
        entries = []
        for key, label, path in items:
            g = KEY2GROUP.get(key)
            if g:
                for k, lb in GROUPS[g][1]:
                    if not can(k) or k in seen:
                        continue
                    seen.add(k)
                    href = url_for('modules.module', mod=k)
                    entries.append((lb, href, path))
            else:
                if not can(key) or key in seen:
                    continue
                seen.add(key)
                href = url_for('dash.dashboard') if key == 'dashboard' else url_for('modules.module', mod=key)
                entries.append((label, href, path))
        if entries:
            cats.append((group, entries))
    # also surface a few common quick actions
    actions = []
    if can('patients'): actions.append(('Register Patient', url_for('modules.module_new', mod='patients')))
    if can('invoices'): actions.append(('Create Invoice', url_for('billing.invoice_new')))
    if can('lab'): actions.append(('New Lab Order', url_for('lab.lab_new')))
    if can('radiology'): actions.append(('New Study', url_for('rad.rad_new')))

    def tile(label, href, path=None):
        ic = (f"<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='{path}'/></svg>"
              if path else "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M12 5v14M5 12h14'/></svg>")
        return (f"<a class='lt' href='{href}' data-name='{h(label.lower())}'>"
                f"<span class='lt-ic'>{ic}</span><span class='lt-l'>{h(label)}</span></a>")

    sections = ''
    if actions:
        sections += ("<div class='lc-grp'>Quick Actions</div><div class='lc-grid'>"
                     + ''.join(tile(lb, hr, 'M12 5v14M5 12h14') for lb, hr in actions) + "</div>")
    for group, entries in cats:
        sections += (f"<div class='lc-grp'>{h(group)}</div><div class='lc-grid'>"
                     + ''.join(tile(lb, hr, pt) for lb, hr, pt in entries) + "</div>")

    return f"""
    <div class="launcher" id="launcher" onclick="if(event.target===this)closeLauncher()">
      <div class="lc-box">
        <div class="lc-head">
          <input id="lc-search" placeholder="Type to find any module or action…" oninput="filterLauncher(this.value)" autocomplete="off">
          <button class="lc-x" onclick="closeLauncher()">✕</button>
        </div>
        <div class="lc-body" id="lc-body">{sections}
          <div class="lc-empty" id="lc-empty" style="display:none">No match. Try another word.</div>
        </div>
      </div>
    </div>
    <script>
      function openLauncher(){{var l=document.getElementById('launcher');l.classList.add('show');
        var s=document.getElementById('lc-search');s.value='';filterLauncher('');setTimeout(function(){{s.focus()}},50);}}
      function closeLauncher(){{document.getElementById('launcher').classList.remove('show');}}
      function filterLauncher(q){{q=(q||'').toLowerCase().trim();var any=false;
        document.querySelectorAll('#lc-body .lt').forEach(function(a){{
          var m=a.getAttribute('data-name').indexOf(q)>=0;a.style.display=m?'':'none';if(m)any=true;}});
        document.querySelectorAll('#lc-body .lc-grp').forEach(function(g){{
          var n=g.nextElementSibling,vis=n&&n.querySelectorAll('.lt:not([style*="none"])').length>0;
          g.style.display=vis?'':'none';if(n)n.style.display=vis?'':'none';}});
        document.getElementById('lc-empty').style.display=any?'none':'block';}}
      document.addEventListener('keydown',function(e){{
        if((e.ctrlKey||e.metaKey)&&e.shiftKey&&e.key.toLowerCase()==='k'){{e.preventDefault();openLauncher();}}
        if(e.key==='Escape')closeLauncher();}});
    </script>"""


def nav_html(active):
    ag = KEY2GROUP.get(active)
    is_acct_active = (active in ('acctdash', 'acct', 'findash', 'genledger', 'coa', 'accounts', 'jentries', 'journal', 'finance', 'pnl', 'balance_sheet', 'cashflow', 'bankrec')
                      or ag == 'accounting'
                      or (request and (request.path.startswith('/acctdash') or request.path.startswith('/gl') or request.path.startswith('/journal') or request.path.startswith('/coa'))))
    first_group = NAVDEF[0][0] if NAVDEF else None
    out = []
    for group, items in NAVDEF:
        rendered = []
        sec_active = False
        for key,label,path in items:
            if key == 'acctdash':
                if not (can('acctdash') or can('accounting')):
                    continue
                href = url_for('acctdash.acct_dashboard')
                is_active = (active in ('acctdash', 'acct', 'findash') or (request and request.path == '/acctdash'))
            elif group == "Accounting":
                if not can(key):
                    continue
                href = url_for('dash.dashboard') if key=='dashboard' else url_for('modules.module', mod=key)
                is_active = (key == active or (key == 'coa' and active == 'accounts') or (key == 'jentries' and active == 'journal'))
            elif g := KEY2GROUP.get(key):
                subs = [k for k,_ in GROUPS[g][1] if can(k)]
                if not subs: continue
                href = url_for('modules.module', mod=subs[0]); is_active = (ag==g)
            else:
                if not can(key): continue
                href = url_for('dash.dashboard') if key=='dashboard' else url_for('modules.module', mod=key)
                is_active = (key==active)
            if is_active: sec_active = True
            cls = 'active' if is_active else ''
            rendered.append(f"<a class='{cls}' href='{href}' data-tooltip='{h(label)}'><svg class='ic' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='{path}'/></svg><span class='nav-text'>{h(label)}</span></a>")
        if not rendered:
            continue
        chev_svg = "<svg class='chev' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='9 18 15 12 9 6'></polyline></svg>"
        if group == first_group:                     # Overview stays open (short, always handy)
            out.append(f"<div class='g g-static'><span>{h(group)}</span></div>")
            out.extend(rendered)
        else:                                        # other sections collapse (open only if active)
            opencls = ' open' if (sec_active or (group == "Accounting" and is_acct_active)) else ''
            out.append(f"<div class='navsec{opencls}'>"
                       f"<button type='button' class='gbtn' onclick='this.parentNode.classList.toggle(\"open\")'>"
                       f"<span>{h(group)}</span>{chev_svg}</button>"
                       f"<div class='navsub'>{''.join(rendered)}</div></div>")
    return ''.join(out)

ACCT_MENUBAR = [
    ("Overview", "acctdash", [
        ("acctdash", "Accounting Center"),
    ]),
    ("Transactions", "jentries", [
        ("jentries", "Journal Entries"),
        ("recurjournals", "Recurring Journals"),
        ("expenses", "Expenses"),
        ("payables", "Commission Payables"),
    ]),
    ("Ledgers", "genledger", [
        ("genledger", "General Ledger"),
        ("partnerledger", "Partner Ledger"),
        ("coa", "Chart of Accounts"),
    ]),
    ("Receivables & Payables", "araging", [
        ("araging", "AR Aging"),
        ("apaging", "AP Aging"),
    ]),
    ("Banking", "banks", [
        ("banks", "Bank Accounts"),
        ("bankrec", "Bank Reconciliation"),
        ("cashflow", "Cash Flow"),
    ]),
    ("Planning & Analysis", "budgets", [
        ("budgets", "Budgets"),
        ("budgetreport", "Budget vs Actual"),
        ("costcenters", "Cost Centers"),
        ("ccreport", "Cost Center Report"),
        ("ratios", "Financial Ratios"),
        ("revreport", "Revenue Analysis"),
    ]),
    ("Reports", "finance", [
        ("finance", "Financial Statements"),
        ("taxreport", "Tax Report"),
    ]),
    ("Configuration", "fiscal", [
        ("fiscal", "Fiscal Periods"),
        ("currencies", "Currencies"),
    ]),
]

ACCT_KEYS = {
    'acctdash', 'acct', 'findash', 'jentries', 'journal', 'jitems', 'recurjournals',
    'expenses', 'payables', 'paycenter', 'genledger', 'ledger', 'gldash', 'partnerledger',
    'coa', 'accounts', 'acctbal', 'trialbal', 'araging', 'apaging', 'banks', 'bankrec',
    'bankrecon', 'cashflow', 'budgets', 'budgetreport', 'costcenters', 'ccreport',
    'ratios', 'revreport', 'finance', 'pnl', 'balance_sheet', 'taxreport', 'fiscal', 'currencies'
}

ACCT_BAR_TRIGGER = ACCT_KEYS


def _can_acct(key):
    perm_map = {
        'acctdash': ('acctdash', 'accounting', 'findash', 'acct'),
        'jentries': ('jentries', 'journal', 'accounting', 'genledger'),
        'recurjournals': ('recurjournals', 'journal', 'accounting'),
        'expenses': ('expenses', 'accounting', 'purchases'),
        'payables': ('payables', 'accounting', 'commission'),
        'genledger': ('genledger', 'ledger', 'accounting'),
        'partnerledger': ('partnerledger', 'accounting', 'genledger'),
        'coa': ('coa', 'accounts', 'accounting'),
        'araging': ('araging', 'accounting', 'invoices'),
        'apaging': ('apaging', 'accounting', 'purchases'),
        'banks': ('banks', 'bankrec', 'accounting'),
        'bankrec': ('bankrec', 'bankrecon', 'accounting'),
        'cashflow': ('cashflow', 'accounting', 'finance'),
        'budgets': ('budgets', 'accounting'),
        'budgetreport': ('budgetreport', 'budgets', 'accounting'),
        'costcenters': ('costcenters', 'accounting'),
        'ccreport': ('ccreport', 'costcenters', 'accounting'),
        'ratios': ('ratios', 'accounting', 'finance'),
        'revreport': ('revreport', 'accounting', 'revenue'),
        'finance': ('finance', 'accounting', 'genledger'),
        'taxreport': ('taxreport', 'accounting'),
        'fiscal': ('fiscal', 'accounting', 'settings'),
        'currencies': ('currencies', 'accounting', 'settings'),
    }
    aliases = perm_map.get(key, (key, 'accounting'))
    return any(can(p) for p in aliases)


def _is_active_key(item_key, active):
    if item_key == active:
        return True
    aliases = {
        'acctdash': {'acctdash', 'acct', 'findash'},
        'genledger': {'genledger', 'ledger', 'gldash'},
        'coa': {'coa', 'accounts'},
        'jentries': {'jentries', 'journal', 'jitems'},
        'bankrec': {'bankrec', 'bankrecon'},
        'finance': {'finance', 'pnl', 'balance_sheet', 'trialbal', 'acctbal'},
    }
    return active in aliases.get(item_key, set())


def _acct_url(key):
    try:
        if key in ('acctdash', 'findash', 'acct'):
            return url_for('acctdash.acct_dashboard')
        if key in ('genledger', 'ledger', 'gldash'):
            return url_for('modules.module', mod='genledger')
        if key in ('coa', 'accounts'):
            return url_for('modules.module', mod='accounts')
        if key in ('jentries', 'journal', 'jitems'):
            return url_for('modules.module', mod='jentries')
        if key in ('bankrec', 'bankrecon'):
            return url_for('modules.module', mod='bankrec')
        return url_for('modules.module', mod=key)
    except Exception:
        return f"/{key}"


def _acct_menubar(active):
    desktop_items = []
    mobile_groups = []
    active_label = "Accounting Center"

    chev_svg = ('<svg class="mb-chev" width="12" height="12" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
                '<polyline points="6 9 12 15 18 9"></polyline></svg>')

    for top_label, default_key, subs in ACCT_MENUBAR:
        vis_subs = [(k, lbl) for k, lbl in subs if _can_acct(k)]
        if not vis_subs:
            continue

        group_is_on = any(_is_active_key(k, active) for k, _ in vis_subs)

        if top_label == "Overview" or (len(subs) == 1 and subs[0][0] == 'acctdash'):
            k, lbl = vis_subs[0]
            if group_is_on:
                active_label = lbl
            is_on = "on" if group_is_on else ""
            desktop_items.append(f'<a class="mb-top {is_on}" href="{_acct_url(k)}">{h(top_label)}</a>')
            mobile_groups.append(f'<div class="mbar-mobile-group"><a class="mbar-mobile-link {is_on}" href="{_acct_url(k)}">{h(lbl)}</a></div>')
        else:
            drop_links = []
            mobile_links = []
            for k, lbl in vis_subs:
                item_is_on = _is_active_key(k, active)
                if item_is_on:
                    active_label = lbl
                on_cls = "on" if item_is_on else ""
                drop_links.append(f'<a class="{on_cls}" href="{_acct_url(k)}">{h(lbl)}</a>')
                mobile_links.append(f'<a class="mbar-mobile-link {on_cls}" href="{_acct_url(k)}">{h(lbl)}</a>')

            group_on_cls = "on" if group_is_on else ""
            desktop_items.append(
                f'<div class="mb-item">'
                f'<button type="button" class="mb-top {group_on_cls}">{h(top_label)} {chev_svg}</button>'
                f'<div class="mb-drop">{"".join(drop_links)}</div>'
                f'</div>'
            )
            mobile_groups.append(
                f'<div class="mbar-mobile-group">'
                f'<div class="mbar-mobile-group-ttl">{h(top_label)}</div>'
                f'{"".join(mobile_links)}'
                f'</div>'
            )

    if not desktop_items:
        return ""

    js_script = (
        "<script>\n"
        "(function(){\n"
        "  document.addEventListener('click', function(e){\n"
        "    var mbar = document.querySelector('.mbar-desktop');\n"
        "    if(!mbar) return;\n"
        "    var item = e.target.closest('.mb-item');\n"
        "    if(item && mbar.contains(item)){\n"
        "      var topBtn = e.target.closest('.mb-top');\n"
        "      if(topBtn){\n"
        "        var isOpen = item.classList.contains('open');\n"
        "        mbar.querySelectorAll('.mb-item').forEach(function(i){ i.classList.remove('open'); });\n"
        "        if(!isOpen) item.classList.add('open');\n"
        "        e.stopPropagation();\n"
        "      }\n"
        "    }else{\n"
        "      mbar.querySelectorAll('.mb-item').forEach(function(i){ i.classList.remove('open'); });\n"
        "    }\n"
        "    var mwrap = document.querySelector('.mbar-mobile-wrap');\n"
        "    if(mwrap && !mwrap.contains(e.target)){\n"
        "      var mdrawer = mwrap.querySelector('.mbar-mobile-drawer');\n"
        "      if(mdrawer) mdrawer.classList.remove('open');\n"
        "    }\n"
        "  });\n"
        "  document.addEventListener('keydown', function(e){\n"
        "    if(e.key === 'Escape'){\n"
        "      document.querySelectorAll('.mb-item.open').forEach(function(i){ i.classList.remove('open'); });\n"
        "      var mdrawer = document.querySelector('.mbar-mobile-drawer.open');\n"
        "      if(mdrawer) mdrawer.classList.remove('open');\n"
        "    }\n"
        "  });\n"
        "})();\n"
        "</script>"
    )

    desktop_html = f'<div class="mbar-desktop">{"".join(desktop_items)}</div>'
    mobile_html = (
        f'<div class="mbar-mobile-wrap">'
        f'<button type="button" class="mbar-mobile-btn" onclick="this.nextElementSibling.classList.toggle(\'open\')">'
        f'<span>Accounting: {h(active_label)}</span>'
        f'{chev_svg}'
        f'</button>'
        f'<div class="mbar-mobile-drawer">{"".join(mobile_groups)}</div>'
        f'</div>'
    )

    return f'{desktop_html}{mobile_html}{js_script}'


def _menubar(active, structure):
    """Odoo-style horizontal dropdown menubar for one app area."""
    items = ''
    for top, _icon, subs in structure:
        vis = [(k, lb) for k, lb in subs if k.startswith('_') or can(k)]
        real = [k for k, _ in vis if not k.startswith('_')]
        if not real:
            continue
        is_on = active in real
        if len(real) == 1:
            items += (f"<a class='mb-top {'on' if is_on else ''}' "
                      f"href='{url_for('modules.module', mod=real[0])}'>{h(top)}</a>")
            continue
        drop = ''
        for k, lb in vis:
            if k.startswith('_'):
                drop += f"<div class='mb-hd'>{h(lb.strip('— '))}</div>"
            else:
                drop += (f"<a class='{'on' if k==active else ''}' "
                         f"href='{url_for('modules.module', mod=k)}'>{h(lb)}</a>")
        items += (f"<div class='mb-item'><span class='mb-top {'on' if is_on else ''}'>{h(top)} ▾</span>"
                  f"<div class='mb-drop'>{drop}</div></div>")
    return f"<div class='mbar'>{items}</div>"

# ---- Odoo-style menubars for every other app area ----
CLINICAL_MENUBAR = [
    ("Patients", None, [
        ("patients", "Patient Registration"),
        ("queue", "Reception Queue"),
        ("consult", "Consultation"),
    ]),
    ("Doctor Requests", None, [
        ("referrals", "Requests (List)"),
        ("reqboard", "Request Board"),
    ]),
    ("Referral Management", None, [
        ("doctors", "Referring Doctors"),
        ("radiologists", "Radiologists"),
    ]),
    ("Blood Bank", None, [
        ("donors", "Donors"),
        ("bloodunits", "Blood Units"),
    ]),
    ("Vaccination", None, [("vaccinations", "Vaccination")]),
]

DIAG_MENUBAR = [
    ("Laboratory", None, [
        ("lab", "Lab Requests"),
        ("labqc", "Quality Control"),
    ]),
    ("Radiology", None, [
        ("radiology", "Radiology / Imaging"),
        ("radiologists", "Radiologists"),
    ]),
]

INV_MENUBAR = [
    ("Pharmacy", None, [
        ("pharmacy", "Pharmacy Sales"),
        ("batches", "Batches (FEFO)"),
    ]),
    ("Inventory", None, [
        ("inventory", "Supplies / Stock"),
        ("warehouses", "Warehouses"),
        ("transfers", "Stock Transfers"),
        ("stockadj", "Stock Adjustments"),
        ("stockvalue", "Inventory Valuation"),
        ("consumption", "Consumption Report"),
    ]),
    ("Procurement", None, [
        ("purchases", "Purchase Orders"),
        ("suppliers", "Suppliers"),
    ]),
]

HR_MENUBAR = [
    ("Employees", None, [
        ("employees", "Employees"),
        ("contracts", "Contracts"),
    ]),
    ("Time", None, [
        ("attendance", "Attendance"),
        ("leave", "Leave"),
    ]),
    ("Payroll", None, [("payroll", "Payroll")]),
]

QUALITY_MENUBAR = [
    ("Quality", None, [
        ("sops", "SOPs & Documents"),
        ("incidents", "Incidents"),
        ("audits", "Internal Audits"),
        ("feedback", "Patient Feedback"),
    ]),
]

ASSETS_MENUBAR = [
    ("Assets", None, [
        ("maintdash", "Maintenance Overview"),
        ("assets", "Asset Register"),
        ("maintenance", "Maintenance Jobs"),
    ]),
    ("Logistics", None, [("logistics", "Logistics")]),
]

REPORTS_MENUBAR = [
    ("Reports", None, [
        ("reports", "Reports Overview"),
        ("summary", "Summary (Date Range)"),
        ("revenue", "Revenue Analysis"),
        ("productivity", "Productivity"),
        ("branchcmp", "Branch Comparison"),
    ]),
]

ADMIN_MENUBAR = [
    ("Users & Access", None, [
        ("users", "User Management"),
        ("branches", "Branches"),
    ]),
    ("System", None, [
        ("settings", "Settings"),
        ("svcmgmt", "Service Management"),
        ("backup", "Backup & Restore"),
        ("messages", "Messages / SMS"),
    ]),
    ("Logs", None, [
        ("audit", "Audit Log"),
        ("errorlog", "Error Log"),
        ("syshealth", "System Health"),
        ("loginhistory", "Login Security"),
    ]),
]

APP_BARS = {
    'clinical': CLINICAL_MENUBAR,
    'diag': DIAG_MENUBAR,
    'inv': INV_MENUBAR,
    'hr': HR_MENUBAR,
    'quality': QUALITY_MENUBAR,
    'assets': ASSETS_MENUBAR,
    'reports': REPORTS_MENUBAR,
    'admin': ADMIN_MENUBAR,
}
# module key -> app bar (accounting handled first via ACCT_BAR_TRIGGER)
BAR_TRIGGER = {k: app for app, bar in APP_BARS.items()
               for _t, _i, subs in bar for k, _l in subs if not k.startswith('_')}


def subnav_html(active):
    """Compact page-level tabs for module-specific sub-navigation."""
    if active in ACCT_BAR_TRIGGER or active in ACCT_KEYS or KEY2GROUP.get(active) == 'accounting':
        return _acct_menubar(active)
    app = BAR_TRIGGER.get(active)
    if app and app in APP_BARS:
        return _menubar(active, APP_BARS[app])
    g = KEY2GROUP.get(active)
    if not g:
        return ''
    val = GROUPS.get(g)
    if isinstance(val, tuple) and len(val) == 2 and isinstance(val[1], list):
        label, items = val
    elif isinstance(val, list):
        label, items = GROUP_LABEL.get(g, 'Navigation'), val
    else:
        return ''
    vis = [(k, lb) for k, lb in items if isinstance(k, str) and not k.startswith('_') and can(k)]
    if len(vis) <= 1:
        return ''
    tabs = ''.join(f"<a class='{'on' if k==active else ''}' href='{url_for('modules.module',mod=k)}'>{h(lb)}</a>" for k, lb in vis)
    return f"<div class='subnav'><span class='subnav-t'>{h(label)}</span>{tabs}</div>"

def _darken(hexc, f=0.72):
    hexc=(hexc or '').lstrip('#')
    if len(hexc)!=6: return '#0B2E35'
    try: r,g,b=int(hexc[0:2],16),int(hexc[2:4],16),int(hexc[4:6],16)
    except Exception: return '#0B2E35'
    return '#%02X%02X%02X'%(int(r*f),int(g*f),int(b*f))
def brand_style():
    b=(setting('brand','') or '').strip()
    return f"<style>:root{{--petrol:{b};--petrol7:{_darken(b)};}}</style>" if b else ''
def _logo_mark():
    lg = (setting('logo', '') or '').strip() or '/static/brand/mdc-mark.png'
    return (f'<img src="{h(lg)}" alt="logo" style="width:30px;height:30px;border-radius:7px;'
            f'object-fit:contain;background:#fff;padding:2px;flex:none">')

def _bell(u):
    """Top-bar notification bell with unread badge."""
    try:
        from .notify import unseen_count
        n = unseen_count(u)
    except Exception:
        n = 0
    badge = (f"<span style='font-size:0;line-height:0;width:0;height:0;display:inline-block;overflow:hidden'>🔔"
             f"<span style='position:absolute;top:-4px;right:-4px;background:var(--red);color:#fff;"
             f"border-radius:10px;font-size:10px;font-weight:700;padding:1px 5px'>{n}</span></span>") if n else ''
    bell_ic = "<svg width='15' height='15' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' style='vertical-align:middle'><path d='M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9'></path><path d='M13.73 21a2 2 0 0 1-3.46 0'></path></svg>"
    return (f"<a class='btn sm' href='/notifications' title='Notifications' "
            f"style='position:relative'>{bell_ic}{badge}</a>")


PRINT_CSS = """
.print-lh,.print-foot{display:none}
@media print{
 body{-webkit-print-color-adjust:exact;print-color-adjust:exact}
 .print-lh{display:block;position:fixed;top:0;left:0;right:0;background:#fff;padding:7px 16px 8px;border-bottom:2.5px solid var(--petrol);z-index:9999}
 .print-lh .co{display:flex;align-items:center;gap:11px}
 .print-lh img{height:44px;width:auto;object-fit:contain}
 .print-lh .mk{width:40px;height:40px;border-radius:10px;background:linear-gradient(135deg,var(--amber),#F2A25B);display:grid;place-items:center;color:var(--petrol7);font-weight:700;font-size:21px;font-family:var(--fd);flex:none}
 .print-lh .nm{font-family:var(--fd);font-weight:700;font-size:16px;color:var(--petrol);line-height:1.15}
 .print-lh .ar{font-size:12.5px;color:#555;font-weight:600}
 .print-lh .ct{font-size:9.5px;color:#666;margin-top:1px}
 .print-foot{display:block;position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid #bbb;padding:5px 16px;text-align:center;font-size:9px;color:#888;z-index:9999}
 /* real letterhead artwork — identical branding to vouchers & receipts */
 .print-lh.art,.print-foot.art{padding:0;border:none;background:#fff}
 .print-lh.art img,.print-foot.art img{width:100%;height:auto;display:block;object-fit:contain}
 .content{padding-top:72px!important;padding-bottom:34px!important}
 .subnav,.flash{display:none!important}
}
"""


def _print_letterhead():
    """Hidden on screen; a branded running header + footer on every printed page.

    When the letterhead artwork is enabled (the same setting the payment voucher
    and cash-payment receipts use), every printed screen — including all financial
    statements — carries the identical header/footer artwork. Falls back to a clean
    text header (logo + company name + contacts) when artwork is switched off.
    """
    company = h(setting('company', 'Modern Diagnostic Center'))
    appname = h(setting('appname', 'MDC ERP'))
    # --- letterhead artwork (matches core.printing.printable) ---------------
    lh_on = setting('letterhead', '1') == '1'
    lh_head = (setting('letterhead_header', '') or '/static/brand/letterhead-header.jpg').strip()
    lh_foot = (setting('letterhead_footer', '') or '/static/brand/letterhead-footer.jpg').strip()
    if lh_on and lh_head:
        head = f'<div class="print-lh art"><img src="{h(lh_head)}" alt=""></div>'
        foot = (f'<div class="print-foot art"><img src="{h(lh_foot)}" alt=""></div>'
                if lh_foot
                else f'<div class="print-foot">{company} &middot; Printed via {appname}</div>')
        # taller running header/footer for the artwork — same allowance as vouchers
        pad = ('<style media="print">.content{padding-top:38mm!important;'
               'padding-bottom:27mm!important}</style>')
        return pad + head + foot
    # --- text fallback: logo + company name + contact line -------------------
    logo = (setting('logo', '') or '').strip()
    addr = h(setting('company_address', '') or '')
    phone = h(setting('company_phone', '') or '')
    email = h(setting('company_email', '') or '')
    web = h(setting('company_web', '') or '')
    arabic = h(setting('company_arabic', '') or '')
    contact = ' · '.join(x for x in [addr, phone, email, web] if x)
    mark = f'<img src="{h(logo)}" alt="">' if logo else '<span class="mk">M</span>'
    ar = f'<div class="ar">{arabic}</div>' if arabic else ''
    ct = f'<div class="ct">{contact}</div>' if contact else ''
    head = (f'<div class="print-lh"><div class="co">{mark}'
            f'<div><div class="nm">{company}</div>{ar}{ct}</div></div></div>')
    foot = (f'<div class="print-foot">{company}'
            f'{(" · " + contact) if contact else ""} · Printed via {appname} · Developed by Kulmiye</div>')
    return head + foot


def _quick_create():
    """Compact global create menu with only actions allowed for the user."""
    actions = []
    if can('patients'):
        actions.append(('Register patient', url_for('modules.module_new', mod='patients')))
    if can('invoices'):
        actions.append(('Create invoice', url_for('billing.invoice_new')))
    if can('lab'):
        actions.append(('New laboratory order', url_for('lab.lab_new')))
    if can('radiology'):
        actions.append(('New radiology study', url_for('rad.rad_new')))
    if can('record_options'):
        actions.append(('Record options', url_for('record_options.index')))
    if not actions:
        return ''
    links = ''.join(f"<a href='{h(href)}'>{h(label)}</a>" for label, href in actions)
    return ("<div class='quick-create'><button type='button' class='btn sm primary' aria-haspopup='menu' "
            "onclick=\"this.parentNode.classList.toggle('open')\">＋ New</button>"
            f"<div class='quick-create-menu' role='menu'>{links}</div></div>")


def _watermark_html():
    """Faint MDC logo watermark behind the content on every screen (toggle: wm_on)."""
    if (setting('wm_on', '1') or '1').strip() != '1':
        return ''
    return '<div class="mdc-wm" aria-hidden="true"></div>'


def _brand_footer_html():
    """Branded footer shown on every page: MDC mark + company + year."""
    from datetime import date as _d
    company = setting('company', 'Modern Diagnostic Center')
    appname = setting('appname', 'MDC ERP')
    dev = setting('developer', 'Kulmiye')
    wm_on = (setting('wm_on', '1') or '1').strip() == '1'
    wm_css = ('.mdc-wm{position:fixed;inset:0;z-index:0;pointer-events:none;'
              'background:url("/static/brand/mdc-logo.png") no-repeat center 46%;'
              'background-size:min(540px,56vw);opacity:.05}'
              'body.dark .mdc-wm{opacity:.08}.content{position:relative;z-index:1}') if wm_on else ''
    return (
        '<style>' + wm_css +
        '.mdc-foot{margin:30px 2px 8px;padding:14px 2px 0;border-top:1px solid var(--line);'
        'display:flex;align-items:center;gap:10px;color:var(--muted);font-size:12.5px;'
        'flex-wrap:wrap;position:relative;z-index:1}'
        '.mdc-foot img{width:26px;height:26px;border-radius:6px;flex:none}'
        '.mdc-foot b{color:var(--petrol)}.mdc-foot .yr{margin-left:auto}'
        '@media print{.mdc-wm,.mdc-foot{display:none!important}}'
        '</style>'
        '<footer class="mdc-foot">'
        '<img src="/static/brand/mdc-mark.png" alt="MDC logo">'
        f'<span><b>{h(company)}</b> · {h(appname)}</span>'
        f'<span class="yr">© {_d.today().year} {h(company)} · All rights reserved · Developed by <b>{h(dev)}</b></span>'
        '</footer>')


SEARCH_SELECT_HTML = r"""<style>
.ss-wrap{position:relative;display:block}
.ss-native{position:absolute!important;width:1px;height:1px;opacity:0;pointer-events:none;left:0;top:0;margin:0}
.ss-input{width:100%;cursor:text}
.ss-wrap.open .ss-input{border-color:var(--petrol);box-shadow:0 0 0 3px rgba(4,76,140,.10)}
.ss-panel{display:none;position:absolute;z-index:9000;left:0;right:0;top:calc(100% + 3px);background:var(--surface);border:1px solid var(--line);border-radius:8px;box-shadow:0 10px 28px rgba(0,0,0,.16);max-height:270px;overflow:auto}
.ss-wrap.open .ss-panel{display:block}
.ss-opt{padding:8px 12px;font-size:14px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ss-opt:hover,.ss-opt.hl{background:rgba(4,76,140,.09)}
.ss-opt.sel{font-weight:600;color:var(--petrol)}
.ss-empty{padding:10px 12px;color:var(--muted);font-size:13px}
</style>
<script>
(function(){
  function enhance(sel){
    if(sel.dataset.ssDone) return; sel.dataset.ssDone='1';
    var wrap=document.createElement('div'); wrap.className='ss-wrap';
    sel.parentNode.insertBefore(wrap, sel); wrap.appendChild(sel); sel.classList.add('ss-native');
    var inp=document.createElement('input'); inp.type='text'; inp.className='ss-input';
    inp.autocomplete='off'; inp.placeholder='Search\u2026'; if(sel.disabled) inp.disabled=true;
    wrap.appendChild(inp);
    var panel=document.createElement('div'); panel.className='ss-panel'; wrap.appendChild(panel);
    function label(){ var o=sel.options[sel.selectedIndex]; return o?o.text:''; }
    function sync(){ inp.value=label(); }
    sync();
    function build(filter){
      panel.innerHTML=''; var f=(filter||'').trim().toLowerCase(); var any=false;
      for(var i=0;i<sel.options.length;i++){
        var o=sel.options[i], txt=o.text;
        if(f && txt.toLowerCase().indexOf(f)<0) continue;
        any=true;
        var d=document.createElement('div');
        d.className='ss-opt'+(i===sel.selectedIndex?' sel':''); d.textContent=txt; d.dataset.i=i;
        panel.appendChild(d);
      }
      if(!any){ var e=document.createElement('div'); e.className='ss-empty'; e.textContent='No matches'; panel.appendChild(e); }
    }
    function open(){ build(''); wrap.classList.add('open'); setTimeout(function(){inp.select();},0); }
    function close(){ wrap.classList.remove('open'); sync(); }
    inp.addEventListener('focus', open);
    inp.addEventListener('input', function(){ build(inp.value); wrap.classList.add('open'); });
    panel.addEventListener('mousedown', function(e){
      var d=e.target.closest('.ss-opt'); if(!d) return; e.preventDefault();
      sel.selectedIndex=parseInt(d.dataset.i,10);
      sel.dispatchEvent(new Event('change',{bubbles:true})); close();
    });
    inp.addEventListener('keydown', function(e){
      if(e.key==='Escape'){ close(); inp.blur(); return; }
      if(e.key==='ArrowDown'||e.key==='ArrowUp'){
        e.preventDefault(); if(!wrap.classList.contains('open')) open();
        var opts=[].slice.call(panel.querySelectorAll('.ss-opt')); if(!opts.length) return;
        var cur=panel.querySelector('.ss-opt.hl'); var idx=cur?opts.indexOf(cur):-1;
        idx += (e.key==='ArrowDown'?1:-1); if(idx<0)idx=0; if(idx>=opts.length)idx=opts.length-1;
        opts.forEach(function(o){o.classList.remove('hl');}); opts[idx].classList.add('hl');
        opts[idx].scrollIntoView({block:'nearest'});
      } else if(e.key==='Enter'){
        var hl=panel.querySelector('.ss-opt.hl');
        if(hl){ e.preventDefault(); sel.selectedIndex=parseInt(hl.dataset.i,10);
          sel.dispatchEvent(new Event('change',{bubbles:true})); close(); }
      }
    });
    document.addEventListener('mousedown', function(e){ if(!wrap.contains(e.target)) close(); });
    sel.addEventListener('change', sync);
  }
  function run(root){
    (root||document).querySelectorAll('select:not([multiple]):not([data-nosearch])').forEach(function(sel){
      if(sel.dataset.ssDone) return;
      if(sel.hasAttribute('data-search') || sel.options.length>=8) enhance(sel);
    });
  }
  window.MDCEnhanceSelects=run;
  function boot(){
    run();
    var t; var mo=new MutationObserver(function(){ clearTimeout(t); t=setTimeout(function(){run();},120); });
    try{ mo.observe(document.body,{childList:true,subtree:true}); }catch(_){}
  }
  if(document.readyState!=='loading') boot(); else document.addEventListener('DOMContentLoaded', boot);
})();
</script>"""


def plink(p, name=None, dash='—'):
    """Render a patient's name as a link to their full record (/patient/<id>).
    p = a Patient (or anything with .id/.name) or None. Use everywhere a patient
    name is shown so staff can click through to the full profile."""
    nm = name if name is not None else (getattr(p, 'name', None) if p is not None else None)
    if p is not None and getattr(p, 'id', None):
        return f"<a href='/patient/{p.id}' style='color:var(--petrol);font-weight:600'>{h(nm or dash)}</a>"
    return h(nm or dash)


def pnamelink(name, dash='—'):
    """Link a free-text patient name (Doctor Request / referral, which has no
    patient record yet) to the patient search so a click still finds them."""
    if not name:
        return dash
    from urllib.parse import quote
    return (f"<a href='/m/patients?q={quote(str(name))}' style='color:var(--petrol);font-weight:600' "
            f"title='Find this patient'>{h(name)}</a>")


def page(title, body, active='', crumbs=None):
    u = cur_user()
    if not u: return redirect(url_for('auth.login'))
    from flask import render_template
    import json as _json
    flashes = ''.join(f"<div class='flash'>{h(m)}</div>" for m in get_flashed_messages())
    # Alt+P/I/L/R/A/H global navigation shortcuts (Ctrl+K launcher already exists)
    sc = {'p': url_for('modules.module', mod='patients'),
          'i': url_for('modules.module', mod='invoices'),
          'l': url_for('modules.module', mod='lab'),
          'r': url_for('modules.module', mod='radiology'),
          'a': url_for('modules.module', mod='acct'),
          'h': url_for('dash.dashboard')}
    kbd = (f"<script>document.addEventListener('keydown',function(e){{"
           f"if(!e.altKey||e.ctrlKey||e.metaKey)return;"
           f"var t=(e.target.tagName||'').toLowerCase();if(t=='input'||t=='textarea'||e.target.isContentEditable)return;"
           f"var m={_json.dumps(sc)},k=(e.key||'').toLowerCase();"
           f"if(m[k]){{e.preventDefault();location.assign(m[k]);}}}});</script>")
    # Phase 2: the page shell now lives in templates/base.html. All logic stays
    # here in Python; the template only assembles pre-rendered fragments, keeping
    # page()'s signature and output byte-compatible with the old f-string version.
    # Universal Global Search palette (Ctrl/Cmd+K) — Phase 16
    try:
        from .search import palette_html
        global_search = palette_html()
    except Exception:
        global_search = ''
    # Odoo-style document action dialog (Print/Download/Open)
    try:
        from .docactions import doc_actions_html
        doc_actions = doc_actions_html()
    except Exception:
        doc_actions = ''
    return render_template(
        'base.html',
        title=title,
        global_search=global_search,
        doc_actions=doc_actions,
        search_select=SEARCH_SELECT_HTML,
        css=CSS, print_css=PRINT_CSS, nav_css=NAV_CSS,
        brand_style=brand_style(),
        dark='dark' if session.get('dark') else '',
        print_letterhead=_print_letterhead(),
        logo_mark=_logo_mark(),
        watermark=_watermark_html(),
        brand_footer=_brand_footer_html(),
        appname=setting('appname', 'MDC ERP'),
        company=setting('company', 'Modern Diagnostic Center'),
        nav_html=nav_html(active),
        search_action=url_for('dash.search'),
        search_value=(request.args.get('q', '') if request.endpoint == 'dash.search' else ''),
        quick_create=_quick_create(),
        dev_mode=(setting('dev_mode') == '1'),
        bell=_bell(u),
        fav_menu=_fav_menu(u, title),
        recent_menu=_recent_menu(),
        toggle_dark_url=url_for('auth.toggle_dark'),
        initial=(u.name or u.username)[:1].upper(),
        uname=(u.name or u.username),
        role_label=ROLE_LABEL.get(u.role, u.role),
        logout_url=url_for('auth.logout'),
        flashes=flashes,
        subnav=subnav_html(active),
        crumbbar=_crumbbar(active, title, crumbs),
        body=body,
        app_launcher=_app_launcher(active),
        pvw=PVW_HTML,
        kbd=kbd,
    )


PUBLIC_CSS = """
.pubwrap{max-width:760px;margin:26px auto;padding:0 16px}
.pubhead{display:flex;align-items:center;gap:12px;margin-bottom:18px}
.pubhead .mk{width:46px;height:46px;border-radius:12px;background:linear-gradient(135deg,var(--amber),#F2C063);display:grid;place-items:center;color:var(--petrol-700);font-weight:700;font-size:22px;font-family:'Space Grotesk';flex:none}
.pubhead h1{font-family:'Space Grotesk';font-size:21px;color:var(--petrol);margin:0}
.pubhead .s{font-size:12.5px;color:var(--muted)}
.secttl{font-family:'Space Grotesk';font-weight:700;color:var(--petrol);margin:16px 0 8px;font-size:14px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.chk{display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;font-size:13px;cursor:pointer}
.chk input{width:auto}
.chkgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
@media(max-width:560px){.g2,.chkgrid{grid-template-columns:1fr}}
"""


def public_shell(title, inner):
    """Standalone page shell for public/unauthenticated pages (e.g. /refer).
    Phase 2/3 refactor: layout now lives in templates/public.html."""
    from flask import render_template
    return render_template('public.html', title=title, inner=inner,
                           css=CSS, public_css=PUBLIC_CSS,
                           company=setting('company', 'Modern Diagnostic Center'))
