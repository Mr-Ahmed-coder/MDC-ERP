"""Internal staff chat — direct messages between any two users."""
import os
import datetime as dt
from flask import Blueprint, request, redirect, url_for, flash, abort, jsonify, send_file
from markupsafe import escape as h
from werkzeug.utils import secure_filename
from ..extensions import db
from ..models import User, ChatMessage
from ..core.security import cur_user, login_required, log, csrf_token
from ..core.ui import page
from ..config import DATA_DIR

bp = Blueprint('chat', __name__)

CHAT_UPLOAD_DIR = os.path.join(DATA_DIR, 'uploads', 'chat')
# Blocked executable/script types; everything else (images, PDF, office docs, etc.) allowed.
_BLOCKED_EXT = {'exe', 'bat', 'cmd', 'com', 'sh', 'msi', 'scr', 'js', 'jar', 'ps1',
                'vbs', 'apk', 'dll', 'php', 'py', 'pl'}
_IMG_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}


def _ext(fn):
    return (fn.rsplit('.', 1)[-1].lower() if '.' in fn else '')


def _fmt(ts):
    if not ts:
        return ''
    try:
        return ts.strftime('%b %d, %H:%M')
    except Exception:
        return str(ts)


def _unread_count(uid):
    return ChatMessage.query.filter_by(recipient_id=uid, read=False).count()


def chat_view():
    """Conversation list on the left, the open thread on the right."""
    me = cur_user()
    if not me:
        abort(403)
    peer_id = request.args.get('u', type=int)
    users = (User.query.filter(User.active == True, User.id != me.id)
             .order_by(User.name).all())

    # Build the conversation sidebar: everyone, with unread badge + last message.
    def _last_between(other_id):
        return (ChatMessage.query
                .filter(db.or_(
                    db.and_(ChatMessage.sender_id == me.id, ChatMessage.recipient_id == other_id),
                    db.and_(ChatMessage.sender_id == other_id, ChatMessage.recipient_id == me.id)))
                .order_by(ChatMessage.id.desc()).first())

    def _unread_from(other_id):
        return ChatMessage.query.filter_by(sender_id=other_id, recipient_id=me.id, read=False).count()

    rows = []
    for u in users:
        last = _last_between(u.id)
        un = _unread_from(u.id)
        active = ' chat-active' if peer_id == u.id else ''
        if last and last.attachment and not (last.body or '').strip():
            preview = '📎 Attachment'
        elif last:
            preview = h((last.body or '')[:38])
        else:
            preview = '<span style="color:var(--muted)">Start a conversation</span>'
        badge = f"<span class='chat-badge'>{un}</span>" if un else ''
        sort_key = last.id if last else -1
        rows.append((sort_key, un,
                     f"<a class='chat-peer{active}' href='{url_for('modules.module', mod='chat', u=u.id)}'>"
                     f"<div class='chat-ava'>{h((u.name or u.username or '?')[:1].upper())}</div>"
                     f"<div class='chat-peer-main'><div class='chat-peer-top'><b>{h(u.name or u.username)}</b>{badge}</div>"
                     f"<div class='chat-peer-sub'>{h(u.role or '')} · {preview}</div></div></a>"))
    # unread first, then most-recent conversation
    rows.sort(key=lambda r: (-r[1], -r[0]))
    sidebar = ''.join(r[2] for r in rows) or "<div class='pad' style='color:var(--muted)'>No other users yet.</div>"

    # The open thread
    if peer_id:
        peer = User.query.get_or_404(peer_id)
        # mark their messages to me as read
        ChatMessage.query.filter_by(sender_id=peer_id, recipient_id=me.id, read=False)\
            .update({'read': True}); db.session.commit()
        msgs = (ChatMessage.query
                .filter(db.or_(
                    db.and_(ChatMessage.sender_id == me.id, ChatMessage.recipient_id == peer_id),
                    db.and_(ChatMessage.sender_id == peer_id, ChatMessage.recipient_id == me.id)))
                .order_by(ChatMessage.id.asc()).all())
        bubbles = ''
        for m in msgs:
            mine = (m.sender_id == me.id)
            side = 'me' if mine else 'them'
            att = ''
            if m.attachment:
                _url = url_for('chat.chat_file', mid=m.id)
                if _ext(m.attachment) in _IMG_EXT:
                    att = (f"<a href='{_url}' target='_blank'>"
                           f"<img src='{_url}' class='chat-img' alt='{h(m.attachment_name or 'image')}'></a>")
                else:
                    att = (f"<a class='chat-file' href='{_url}' target='_blank'>"
                           f"<span class='chat-file-ic'>📎</span>"
                           f"<span class='chat-file-nm'>{h(m.attachment_name or 'file')}</span></a>")
            txt = f"<div>{h(m.body)}</div>" if (m.body or '').strip() else ''
            bubbles += (f"<div class='chat-msg {side}'><div class='chat-bubble'>{att}{txt}"
                        f"<span class='chat-time'>{_fmt(m.ts)}{' ✓' if (mine and m.read) else ''}</span></div></div>")
        if not msgs:
            bubbles = "<div class='chat-empty'>No messages yet — say hello 👋</div>"
        thread = f"""
        <div class="chat-thread-head">
          <div class="chat-ava lg">{h((peer.name or peer.username or '?')[:1].upper())}</div>
          <div><b>{h(peer.name or peer.username)}</b><div class="chat-peer-sub">{h(peer.role or '')}</div></div>
        </div>
        <div class="chat-scroll" id="chatScroll">{bubbles}</div>
        <form class="chat-compose" method="post" action="{url_for('chat.chat_send')}" enctype="multipart/form-data">
          <input type="hidden" name="_csrf" value="{csrf_token()}">
          <input type="hidden" name="to" value="{peer.id}">
          <label class="chat-clip" title="Attach a file">📎<input type="file" name="file" style="display:none" onchange="var n=this.files[0]?this.files[0].name:''; document.getElementById('chatFileName').textContent=n;"></label>
          <input class="chat-input" name="body" placeholder="Type a message…" autocomplete="off" autofocus>
          <button class="btn primary">Send</button>
          <div id="chatFileName" class="chat-fname"></div>
        </form>"""
    else:
        thread = "<div class='chat-empty' style='margin:auto'>Select a conversation to start chatting.</div>"

    css = """<style>
      .chat-wrap{display:flex;gap:0;height:calc(100vh - 190px);min-height:460px;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#fff}
      .chat-side{width:300px;border-right:1px solid var(--line);overflow-y:auto;background:#FAFBFC}
      .chat-peer{display:flex;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--line);text-decoration:none;color:var(--ink)}
      .chat-peer:hover{background:#F0F4F8}.chat-active{background:#E8F0FA}
      .chat-ava{width:38px;height:38px;border-radius:50%;background:var(--petrol);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;flex:0 0 auto}
      .chat-ava.lg{width:44px;height:44px;font-size:18px}
      .chat-peer-main{flex:1;min-width:0}.chat-peer-top{display:flex;justify-content:space-between;align-items:center}
      .chat-peer-sub{font-size:11.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .chat-badge{background:var(--amber);color:#fff;border-radius:10px;font-size:11px;font-weight:700;padding:1px 7px;min-width:18px;text-align:center}
      .chat-main{flex:1;display:flex;flex-direction:column;min-width:0}
      .chat-thread-head{display:flex;gap:10px;align-items:center;padding:11px 16px;border-bottom:1px solid var(--line);background:#fff}
      .chat-scroll{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:8px;background:#F7F9FB}
      .chat-msg{display:flex}.chat-msg.me{justify-content:flex-end}
      .chat-bubble{max-width:70%;padding:8px 12px;border-radius:14px;font-size:14px;line-height:1.45;position:relative;word-wrap:break-word}
      .chat-msg.them .chat-bubble{background:#fff;border:1px solid var(--line);border-bottom-left-radius:4px}
      .chat-msg.me .chat-bubble{background:var(--petrol);color:#fff;border-bottom-right-radius:4px}
      .chat-time{display:block;font-size:10px;opacity:.7;margin-top:3px;text-align:right}
      .chat-compose{display:flex;gap:8px;padding:12px 14px;border-top:1px solid var(--line);background:#fff;align-items:center;flex-wrap:wrap}
      .chat-clip{cursor:pointer;font-size:20px;padding:6px 8px;border-radius:50%;line-height:1}
      .chat-clip:hover{background:#EEF3F8}
      .chat-fname{flex-basis:100%;font-size:11.5px;color:var(--muted);padding-left:6px}
      .chat-fname:empty{display:none}
      .chat-img{max-width:220px;max-height:220px;border-radius:8px;display:block;margin-bottom:4px}
      .chat-file{display:flex;align-items:center;gap:8px;text-decoration:none;color:inherit;background:rgba(0,0,0,.06);border-radius:8px;padding:8px 10px;margin-bottom:4px;max-width:230px}
      .chat-msg.me .chat-file{background:rgba(255,255,255,.18)}
      .chat-file-ic{font-size:18px}.chat-file-nm{font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .chat-input{flex:1;padding:10px 14px;border:1px solid var(--line);border-radius:22px;font-size:14px;outline:none}
      .chat-input:focus{border-color:var(--petrol)}
      .chat-empty{color:var(--muted);text-align:center;padding:30px;font-size:14px}
      @media(max-width:820px){.chat-side{width:120px}.chat-peer-sub{display:none}}
    </style>
    <script>var s=document.getElementById('chatScroll'); if(s){s.scrollTop=s.scrollHeight;}</script>"""

    body = f"{css}<div class='chat-wrap'><div class='chat-side'>{sidebar}</div><div class='chat-main'>{thread}</div></div>"
    return page('Chat', body, 'chat')


@bp.route('/chat/send', methods=['POST'])
@login_required
def chat_send():
    me = cur_user()
    to = request.form.get('to', type=int)
    body = (request.form.get('body') or '').strip()
    peer = User.query.get(to) if to else None
    if not peer or not peer.active:
        flash('Recipient not found'); return redirect(url_for('modules.module', mod='chat'))
    # optional file attachment
    stored = orig = None
    f = request.files.get('file')
    if f and f.filename:
        if _ext(f.filename) in _BLOCKED_EXT:
            flash('That file type is not allowed for security reasons.')
            return redirect(url_for('modules.module', mod='chat', u=to))
        os.makedirs(CHAT_UPLOAD_DIR, exist_ok=True)
        orig = f.filename[:255]
        stored = secure_filename(f'c{me.id}_{to}_{int(dt.datetime.now().timestamp())}_{f.filename}')[:200]
        f.save(os.path.join(CHAT_UPLOAD_DIR, stored))
    if not body and not stored:
        return redirect(url_for('modules.module', mod='chat', u=to))
    m = ChatMessage(sender_id=me.id, recipient_id=to, body=body[:4000],
                    attachment=stored, attachment_name=orig)
    db.session.add(m); db.session.commit()
    log(f'Chat to {peer.username}' + (' (+file)' if stored else ''), entity=f'chat:{to}')
    return redirect(url_for('modules.module', mod='chat', u=to))


@bp.route('/chat/file/<int:mid>')
@login_required
def chat_file(mid):
    """Serve a chat attachment — only the sender or recipient may fetch it."""
    me = cur_user()
    m = ChatMessage.query.get_or_404(mid)
    if not m.attachment or me.id not in (m.sender_id, m.recipient_id):
        abort(403)
    path = os.path.join(CHAT_UPLOAD_DIR, m.attachment)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, download_name=(m.attachment_name or m.attachment),
                     as_attachment=(_ext(m.attachment) not in _IMG_EXT))


@bp.route('/chat/unread')
@login_required
def chat_unread():
    """Small JSON endpoint the header can poll for an unread badge."""
    me = cur_user()
    return jsonify({'unread': _unread_count(me.id) if me else 0})
