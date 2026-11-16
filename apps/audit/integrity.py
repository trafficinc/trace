"""Versioned canonical SHA-256 commitments; no claim against a privileged DB operator."""
import hashlib
import json

ZERO='0'*64


def payload(event):
    return {'schema':1,'sequence':event.chain_sequence,'previous_hash':event.previous_hash,
        'action':event.action,'actor_ref':event.actor_ref,'engagement_ref':str(event.engagement_ref) if event.engagement_ref else None,
        'entity_kind':event.entity_kind,'subject_id':event.subject_id,'subject_hash':event.subject_hash,'source_hash':event.source_hash,
        'request_id':event.request_id,'metadata':event.metadata,'before':event.before,'after':event.after,
        'legacy':event.legacy,'created_at':event.created_at.isoformat()}


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode()


def digest(event):
    return hashlib.sha256(canonical(payload(event))).hexdigest()
