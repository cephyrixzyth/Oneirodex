"""Shared support normalization and account/content/destination-bound previews."""
from __future__ import annotations

import hashlib
import hmac
import json
from uuid import uuid4

from itsdangerous import BadSignature, URLSafeTimedSerializer

from .github_issues import build_issue_body, support_github_config, valid_support_repository
from .role_catalog import normalize_role
from .support_privacy import redact_support_text

PREVIEW_MAX_AGE = 15 * 60
AREAS = frozenset({'auth', 'library', 'download', 'webretro', 'companion', 'acquire',
                  'social', 'themes', 'admin', 'oidc', 'security', 'other'})


def support_fields(body: dict) -> dict:
    """Preserve existing aliases, normalization and local storage caps."""
    area = (body.get('area') or 'other').strip().lower()
    kind = (body.get('kind') or 'issue').strip().lower()
    severity = (body.get('severity') or 'P2').strip().upper()
    return {
        'title': body['title'][:200],
        'body': (body.get('body') or body.get('symptom') or '').strip()[:2000],
        'area': area if area in AREAS else 'other',
        'kind': kind if kind in {'issue', 'enhancement'} else 'issue',
        'severity': severity if severity in {'P0', 'P1', 'P2', 'P3'} else 'P2',
        'deploy_hint': (body.get('deploy_hint') or body.get('deploy') or '')[:64] or None,
        'client_hint': (body.get('client_hint') or body.get('client') or '')[:120] or None,
        'url_hint': (body.get('url_hint') or body.get('url') or '')[:512] or None,
        'logs': (body.get('logs') or '').strip()[:4000] or None,
    }


def support_destination() -> dict:
    token, repo = support_github_config()
    valid = valid_support_repository(repo)
    return {'available': bool(token and valid), 'destination': repo if valid else None,
            'visibility': 'unknown', 'redaction': 'mandatory'}


def support_external_payload(user, body: dict) -> dict:
    fields = support_fields(body)
    token, _ = support_github_config()
    payload = {
        'title': redact_support_text(
            f"[{fields['kind']}] {fields['severity']} {fields['area']}: {fields['title']}",
            secrets=(token or '',),
        )[:200],
        'body': build_issue_body({**fields, 'id': str(body['request_id']),
                                  'user_id': user.id,
                                  'role_at_submit': normalize_role(getattr(user, 'role', None))}),
        'labels': ['support', fields['kind'], fields['severity'].lower(), fields['area']],
    }
    if body.get('_approved_repository'):
        payload['expected_repository'] = body['_approved_repository']
    return payload


def _digest(user, body: dict) -> str:
    token, repo = support_github_config()
    # Sign hashes only: the browser approval token must not contain raw diagnostics.
    data = {'user_id': user.id, 'fields': support_fields(body), 'destination': repo,
            'operator_key': hashlib.sha256((token or '').encode()).hexdigest(),
            'payload': support_external_payload(user, body)}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _signer(secret_key):
    return URLSafeTimedSerializer(secret_key, salt='support-preview-v1',
                                 signer_kwargs={'digest_method': hashlib.sha256})


def preview_support_report(user, body: dict, secret_key) -> dict:
    metadata = support_destination()
    if not metadata['available']:
        return {**metadata, 'preview_token': None}
    body = {**body, 'request_id': str(body.get('request_id') or uuid4())}
    return {**metadata, **support_external_payload(user, body),
            'request_id': body['request_id'],
            'preview_token': _signer(secret_key).dumps({
                'digest': _digest(user, body), 'destination': metadata['destination'],
            })}


def valid_support_preview(user, body: dict, secret_key) -> dict | None:
    if not body.get('request_id') or not body.get('preview_token') or not support_destination()['available']:
        return None
    try:
        approved = _signer(secret_key).loads(body['preview_token'], max_age=PREVIEW_MAX_AGE)
        if isinstance(approved, dict) and isinstance(approved.get('digest'), str) and hmac.compare_digest(approved['digest'], _digest(user, body)):
            return approved
        return None
    except (BadSignature, ValueError, TypeError):
        return None
