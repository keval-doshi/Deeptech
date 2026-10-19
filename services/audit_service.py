import json

from flask import has_request_context, request

from extensions import db
from models import AuditLog


def audit(action, entity_type, entity_id=None, actor=None, **data):
    """Queue an audit record in the current transaction (caller commits)."""
    ip = None
    if has_request_context():
        ip = (request.access_route[0] if request.access_route else request.remote_addr) or None
    entry = AuditLog(
        actor_id=getattr(actor, "id", actor),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        data=json.dumps(data, default=str, sort_keys=True),
        ip_address=ip[:45] if ip else None,
    )
    db.session.add(entry)
    return entry
