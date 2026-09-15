"""Outbound messaging (SMS / WhatsApp) via a generic HTTP gateway.

Configure in Admin → Messages: gateway URL, API key, sender ID.
Works with any gateway accepting JSON POST {sender, to, message, key}
(Hormuud, Twilio-proxy, or a local bridge). Without configuration the
messages queue as Pending and can be retried once a gateway is added.
"""
import json
import urllib.request

from ..extensions import db


def queue_msg(to, body, channel='SMS', ref=''):
    """Queue a message and attempt immediate delivery. Never raises."""
    from ..models import OutMsg
    if not to:
        return None
    m = OutMsg(to=to.strip(), body=(body or '')[:480], channel=channel, ref=ref)
    db.session.add(m)
    db.session.commit()
    try_send(m)
    return m


def try_send(m):
    from ..core.security import setting
    url = (setting('sms_url', '') or '').strip()
    if not url:
        m.status, m.info = 'Pending', 'gateway not configured'
        db.session.commit()
        return False
    payload = json.dumps({'sender': setting('sms_sender', 'MDC'),
                          'to': m.to, 'message': m.body,
                          'channel': m.channel,
                          'key': setting('sms_key', '')}).encode()
    try:
        req = urllib.request.Request(url, data=payload,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = 200 <= resp.status < 300
        m.status = 'Sent' if ok else 'Failed'
        m.info = f'HTTP {resp.status}'
    except Exception as e:
        m.status, m.info = 'Failed', str(e)[:160]
    db.session.commit()
    return m.status == 'Sent'
