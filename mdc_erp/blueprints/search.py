"""Universal Global Search — API  (Phase 16, v8.0).

Session-authenticated JSON endpoints under /api/gsearch:
  GET  /api/gsearch?q=...     grouped autocomplete results (permission-filtered)
  GET  /api/gsearch/context   recent + frequent + pinned for the empty palette
  POST /api/gsearch/pin       pin a record  {url,title,icon,module}

Every query is written to the audit log and a per-user search log (which powers
recent & frequent). Results are produced by core.search, which enforces
per-module permissions and branch scope.
"""
from flask import Blueprint, request, jsonify
from ..extensions import db
from ..models import SearchLog, PinnedRecord
from ..core.security import cur_user, log
from ..core.search import run_search

bp = Blueprint('search', __name__)


def _u():
    return cur_user()


@bp.route('/api/gsearch')
def api_search():
    u = _u()
    if not u:
        return jsonify({'error': 'auth'}), 401
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'groups': [], 'took_ms': 0})
    groups, took = run_search(q)
    # log (recent/frequent + audit) — keep the search log lean
    try:
        db.session.add(SearchLog(username=u.username, q=q[:120]))
        db.session.commit()
        log(f'Global search: "{q[:80]}"', action_type='search', entity='Search')
    except Exception:
        db.session.rollback()
    total = sum(len(g['hits']) for g in groups)
    return jsonify({'groups': groups, 'took_ms': took, 'total': total})


@bp.route('/api/gsearch/context')
def api_context():
    u = _u()
    if not u:
        return jsonify({'error': 'auth'}), 401
    # recent distinct queries (most recent first)
    recent, seen = [], set()
    for r in (SearchLog.query.filter_by(username=u.username)
              .order_by(SearchLog.id.desc()).limit(40).all()):
        key = (r.q or '').lower()
        if key and key not in seen:
            seen.add(key)
            recent.append({'q': r.q})
        if len(recent) >= 6:
            break
    # frequent queries (top by count)
    freq = (db.session.query(SearchLog.q, db.func.count(SearchLog.id).label('n'))
            .filter(SearchLog.username == u.username)
            .group_by(SearchLog.q).order_by(db.text('n DESC')).limit(6).all())
    frequent = [{'q': q} for q, n in freq if q]
    # pinned records
    pinned = [{'url': p.url, 'title': p.title, 'icon': p.icon or '📌', 'module': p.module or ''}
              for p in PinnedRecord.query.filter_by(username=u.username)
              .order_by(PinnedRecord.id.desc()).limit(8).all()]
    return jsonify({'recent': recent, 'frequent': frequent, 'pinned': pinned})


@bp.route('/api/gsearch/pin', methods=['POST'])
def api_pin():
    u = _u()
    if not u:
        return jsonify({'error': 'auth'}), 401
    d = request.get_json(silent=True) or {}
    url = (d.get('url') or '').strip()
    if not url:
        return jsonify({'ok': False, 'error': 'url required'}), 400
    existing = PinnedRecord.query.filter_by(username=u.username, url=url).first()
    if existing:
        db.session.delete(existing)          # toggle off
        db.session.commit()
        return jsonify({'ok': True, 'pinned': False})
    db.session.add(PinnedRecord(username=u.username, url=url[:300],
                                title=(d.get('title') or url)[:200],
                                icon=(d.get('icon') or '📌')[:8],
                                module=(d.get('module') or '')[:40]))
    db.session.commit()
    log(f'Pinned record: {(d.get("title") or url)[:80]}', action_type='pin', entity='Search')
    return jsonify({'ok': True, 'pinned': True})
