"""BYO challenge / captcha solver sidecar (FlareSolverr-compatible TRAWL, optional token API)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests
from oneirodex.utils.runtime_config import get_runtime_config
from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings
from oneirodex.utils.security import validate_connector_http_url

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 20
_LAST_ERROR: str | None = None

_CHALLENGE_MARKERS = (
    'just a moment',
    'cf-browser-verification',
    'challenge-platform',
    'checking your browser',
    'attention required',
    'cloudflare',
    'cf-challenge',
    'turnstile',
    'recaptcha',
    'hcaptcha',
)

_CHALLENGE_TITLE = re.compile(
    r'<title[^>]*>\s*(?:just a moment|attention required|access denied|403 forbidden)',
    re.IGNORECASE,
)

_VALID_PROVIDERS = frozenset({'flaresolverr_compat', 'trawl', 'token_api'})


@dataclass
class SolverSolution:
    url: str
    status_code: int
    body: str
    headers: dict[str, str]
    cookies: list[dict[str, Any]]
    user_agent: str | None = None

    def cookie_header(self) -> str:
        parts = []
        for item in self.cookies:
            name = item.get('name')
            value = item.get('value')
            if name and value is not None:
                parts.append(f'{name}={value}')
        return '; '.join(parts)


def _settings_row() -> GlobalSettings | None:
    return db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()


def _arr_cfg() -> dict[str, Any]:
    row = _settings_row()
    cfg = getattr(row, 'arr_settings', None) if row else None
    return dict(cfg) if isinstance(cfg, dict) else {}


def _set_last_error(message: str | None) -> None:
    global _LAST_ERROR
    _LAST_ERROR = message


def _safe_solver_error(exc: Exception) -> str:
    """Return an operator-useful failure class without retaining request data."""
    return f'Challenge solver request failed ({type(exc).__name__}).'


def _config_values(config=None):
    return get_runtime_config() if config is None else config


def challenge_solver_enabled(config=None) -> bool:
    """Opt-in: env flag OR admin Features DB toggle (either enables)."""
    values = _config_values(config)
    raw = values.get('ENABLE_CHALLENGE_SOLVER', False)
    if isinstance(raw, bool):
        env_on = raw
    else:
        env_on = str(raw).lower() in ('1', 'true', 'yes', 'on')
    if env_on:
        return True
    cfg = _arr_cfg()
    return bool(cfg.get('challenge_solver_enabled'))


def get_challenge_config(config=None) -> dict[str, Any]:
    values = _config_values(config)
    cfg = _arr_cfg()
    url = (
        (cfg.get('challenge_solver_url') or '').strip().rstrip('/')
        or str(values.get('CHALLENGE_SOLVER_URL') or '').strip().rstrip('/')
    )
    provider = (
        cfg.get('challenge_solver_provider')
        or values.get('CHALLENGE_SOLVER_PROVIDER')
        or 'flaresolverr_compat'
    )
    if provider not in _VALID_PROVIDERS:
        provider = 'flaresolverr_compat'
    max_tier = cfg.get('challenge_solver_max_tier')
    if max_tier is None:
        max_tier = values.get('CHALLENGE_SOLVER_MAX_TIER', 5)
    try:
        max_tier = int(max_tier)
    except (TypeError, ValueError):
        max_tier = 5
    timeout_ms = values.get('CHALLENGE_SOLVER_TIMEOUT_MS', 60000)
    try:
        timeout_ms = int(timeout_ms)
    except (TypeError, ValueError):
        timeout_ms = 60000
    token_url = (
        (cfg.get('challenge_token_api_url') or '').strip().rstrip('/')
        or str(values.get('CHALLENGE_TOKEN_API_URL') or '').strip().rstrip('/')
    )
    token_key = (
        cfg.get('challenge_token_api_key')
        or values.get('CHALLENGE_TOKEN_API_KEY')
        or ''
    )
    return {
        'enabled': challenge_solver_enabled(values),
        'env_enabled': (
            values.get('ENABLE_CHALLENGE_SOLVER')
            if isinstance(values.get('ENABLE_CHALLENGE_SOLVER'), bool)
            else str(values.get('ENABLE_CHALLENGE_SOLVER', '')).lower() in (
                '1', 'true', 'yes', 'on',
            )
        ),
        'db_enabled': bool(cfg.get('challenge_solver_enabled')),
        'url': url,
        'provider': provider,
        'max_tier': max_tier,
        'timeout_ms': timeout_ms,
        'token_api_url': token_url,
        'token_api_configured': bool(token_key),
    }


def save_challenge_config(payload: dict[str, Any], config=None) -> dict[str, Any]:
    row = _settings_row()
    if row is None:
        row = GlobalSettings()
        db.session.add(row)
    current = _arr_cfg()
    if 'enabled' in payload or 'challenge_solver_enabled' in payload:
        current['challenge_solver_enabled'] = bool(
            payload.get('enabled', payload.get('challenge_solver_enabled')),
        )
    if 'url' in payload or 'challenge_solver_url' in payload:
        raw = payload.get('url', payload.get('challenge_solver_url'))
        url = str(raw or '').strip().rstrip('/')
        if url:
            ok, result = validate_connector_http_url(url)
            if not ok:
                raise ValueError(result)
            url = result.rstrip('/')
        current['challenge_solver_url'] = url
    if 'provider' in payload or 'challenge_solver_provider' in payload:
        provider = str(
            payload.get('provider', payload.get('challenge_solver_provider')) or 'flaresolverr_compat',
        ).strip()
        if provider not in _VALID_PROVIDERS:
            raise ValueError(f'Invalid provider: {provider}')
        current['challenge_solver_provider'] = provider
    if 'max_tier' in payload or 'challenge_solver_max_tier' in payload:
        raw = payload.get('max_tier', payload.get('challenge_solver_max_tier'))
        try:
            tier = int(raw)
        except (TypeError, ValueError):
            raise ValueError('max_tier must be an integer') from None
        if tier < 1:
            raise ValueError('max_tier must be at least 1')
        current['challenge_solver_max_tier'] = tier
    if 'token_api_url' in payload or 'challenge_token_api_url' in payload:
        raw = payload.get('token_api_url', payload.get('challenge_token_api_url'))
        token_url = str(raw or '').strip().rstrip('/')
        if token_url:
            ok, result = validate_connector_http_url(token_url)
            if not ok:
                raise ValueError(result)
            token_url = result.rstrip('/')
        current['challenge_token_api_url'] = token_url
    if 'token_api_key' in payload or 'challenge_token_api_key' in payload:
        key = str(payload.get('token_api_key', payload.get('challenge_token_api_key')) or '').strip()
        if key and key != '***':
            current['challenge_token_api_key'] = key
    row.arr_settings = current
    db.session.commit()
    return get_challenge_config(config)


def is_challenge_response(response: requests.Response) -> bool:
    """Conservative challenge detection — false positives should not loop."""
    status = response.status_code
    if status not in (403, 503, 429):
        if status < 400:
            return False
        if status != 401:
            return False
    body = (response.text or '')[:8192].lower()
    if not body:
        return status in (403, 503)
    if _CHALLENGE_TITLE.search(body):
        return True
    hits = sum(1 for marker in _CHALLENGE_MARKERS if marker in body)
    return hits >= 2 or (status in (403, 503) and hits >= 1)


class ChallengeSolverClient:
    """FlareSolverr-compatible POST /v1 client (TRAWL, FlareSolverr, Byparr)."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_ms: int = 60000,
        provider: str = 'flaresolverr_compat',
        max_tier: int = 5,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self.timeout_ms = max(1000, int(timeout_ms))
        self.provider = provider if provider in _VALID_PROVIDERS else 'flaresolverr_compat'
        self.max_tier = max(1, int(max_tier))
        self._session = session or requests.Session()

    def request_get(self, url: str, *, max_timeout_ms: int | None = None) -> SolverSolution:
        if self.provider == 'trawl':
            try:
                return self._request_trawl_scrape(url, max_timeout_ms=max_timeout_ms)
            except RuntimeError as exc:
                logger.debug(
                    'TRAWL /scrape failed; falling back to /v1 (error_type=%s)',
                    type(exc).__name__,
                )
        return self._request_flaresolverr_get(url, max_timeout_ms=max_timeout_ms)

    def _request_flaresolverr_get(self, url: str, *, max_timeout_ms: int | None = None) -> SolverSolution:
        endpoint = urljoin(self.base_url + '/', 'v1')
        timeout = max_timeout_ms or self.timeout_ms
        payload = {
            'cmd': 'request.get',
            'url': url,
            'maxTimeout': timeout,
        }
        http_timeout = (timeout / 1000.0) + 10.0
        resp = self._session.post(
            endpoint, json=payload, timeout=http_timeout, allow_redirects=False,
        )
        if 300 <= resp.status_code < 400:
            raise RuntimeError('Challenge solver redirect refused')
        if resp.status_code >= 400:
            raise RuntimeError(f'Challenge solver HTTP {resp.status_code}')
        data = resp.json() if resp.content else {}
        if data.get('status') != 'ok':
            message = str(data.get('message') or 'solver error')
            raise RuntimeError(message)
        solution = data.get('solution') or {}
        return self._parse_solution(url, solution)

    def _request_trawl_scrape(self, url: str, *, max_timeout_ms: int | None = None) -> SolverSolution:
        endpoint = urljoin(self.base_url + '/', 'scrape')
        timeout = max_timeout_ms or self.timeout_ms
        payload = {
            'url': url,
            'maxTimeout': timeout,
            'maxTier': min(self.max_tier, 4),
        }
        http_timeout = (timeout / 1000.0) + 10.0
        resp = self._session.post(
            endpoint, json=payload, timeout=http_timeout, allow_redirects=False,
        )
        if 300 <= resp.status_code < 400:
            raise RuntimeError('Challenge solver redirect refused')
        if resp.status_code >= 400:
            raise RuntimeError(f'TRAWL scrape HTTP {resp.status_code}')
        data = resp.json() if resp.content else {}
        tier = data.get('tier')
        timings = data.get('timings')
        if tier is not None or timings is not None:
            logger.debug('TRAWL scrape returned tier/timing metadata')
        solution = data.get('solution') or data
        if isinstance(solution, dict) and solution.get('status') == 'error':
            raise RuntimeError(str(solution.get('message') or 'TRAWL scrape failed'))
        if data.get('status') == 'error':
            raise RuntimeError(str(data.get('message') or 'TRAWL scrape failed'))
        parsed = solution if isinstance(solution, dict) and 'response' in solution else data
        return self._parse_solution(url, parsed)

    @staticmethod
    def _parse_solution(fallback_url: str, solution: dict[str, Any]) -> SolverSolution:
        response_body = solution.get('response')
        if response_body is None:
            response_body = ''
        headers_raw = solution.get('headers') or {}
        headers = {str(k): str(v) for k, v in headers_raw.items()} if isinstance(headers_raw, dict) else {}
        cookies = solution.get('cookies') or []
        if not isinstance(cookies, list):
            cookies = []
        status_code = solution.get('status')
        try:
            status_code = int(status_code)
        except (TypeError, ValueError):
            status_code = 200
        return SolverSolution(
            url=str(solution.get('url') or fallback_url),
            status_code=status_code,
            body=str(response_body),
            headers=headers,
            cookies=cookies,
            user_agent=solution.get('userAgent') or solution.get('user_agent'),
        )


class TokenCaptchaClient:
    """CapSolver-compatible token task adapter (CH-4 stub)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self._session = session or requests.Session()

    def create_task(
        self,
        task_type: str,
        *,
        website_url: str,
        website_key: str,
        **extra: Any,
    ) -> str:
        payload: dict[str, Any] = {
            'clientKey': self.api_key,
            'task': {
                'type': task_type,
                'websiteURL': website_url,
                'websiteKey': website_key,
                **extra,
            },
        }
        resp = self._session.post(
            urljoin(self.base_url + '/', 'createTask'),
            json=payload,
            timeout=30,
            allow_redirects=False,
        )
        if 300 <= resp.status_code < 400:
            raise RuntimeError('Token API redirect refused')
        if resp.status_code >= 400:
            raise RuntimeError(f'Token API HTTP {resp.status_code}')
        data = resp.json() if resp.content else {}
        if data.get('errorId'):
            err = str(data.get('errorDescription') or data.get('errorCode') or 'createTask failed')
            raise RuntimeError(err)
        task_id = data.get('taskId')
        if not task_id:
            raise RuntimeError('Token API did not return taskId')
        return str(task_id)

    def get_task_result(self, task_id: str, *, timeout_sec: float = 120.0) -> dict[str, Any]:
        import time

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            resp = self._session.post(
                urljoin(self.base_url + '/', 'getTaskResult'),
                json={'clientKey': self.api_key, 'taskId': task_id},
                timeout=30,
                allow_redirects=False,
            )
            if 300 <= resp.status_code < 400:
                raise RuntimeError('Token API redirect refused')
            if resp.status_code >= 400:
                raise RuntimeError(f'Token API HTTP {resp.status_code}')
            data = resp.json() if resp.content else {}
            if data.get('errorId'):
                err = str(data.get('errorDescription') or data.get('errorCode') or 'getTaskResult failed')
                raise RuntimeError(err)
            status = str(data.get('status') or '').lower()
            if status == 'ready':
                return data.get('solution') or {}
            if status == 'failed':
                raise RuntimeError('Token task failed')
            time.sleep(2.0)
        raise RuntimeError('Token task timed out')


def _solver_client(config=None) -> ChallengeSolverClient | None:
    if not challenge_solver_enabled(config):
        return None
    cfg = get_challenge_config(config)
    url = cfg.get('url') or ''
    if not url:
        return None
    ok, cleaned = validate_connector_http_url(url)
    if not ok:
        _set_last_error(cleaned)
        return None
    provider = cfg.get('provider') or 'flaresolverr_compat'
    if provider == 'token_api':
        return None
    return ChallengeSolverClient(
        cleaned,
        timeout_ms=int(cfg.get('timeout_ms') or 60000),
        provider=str(provider),
        max_tier=int(cfg.get('max_tier') or 5),
    )


def _token_client(config=None) -> TokenCaptchaClient | None:
    values = _config_values(config)
    cfg = get_challenge_config(values)
    if cfg.get('provider') != 'token_api':
        return None
    token_url = cfg.get('token_api_url') or ''
    if not token_url:
        return None
    ok, cleaned = validate_connector_http_url(token_url)
    if not ok:
        _set_last_error(cleaned)
        return None
    arr = _arr_cfg()
    api_key = (
        arr.get('challenge_token_api_key')
        or values.get('CHALLENGE_TOKEN_API_KEY')
        or ''
    )
    if not api_key:
        return None
    return TokenCaptchaClient(cleaned, api_key)


def _apply_solution_to_request_kwargs(
    kwargs: dict[str, Any],
    solution: SolverSolution,
) -> dict[str, Any]:
    out = dict(kwargs)
    headers = dict(out.get('headers') or {})
    cookie_header = solution.cookie_header()
    if cookie_header:
        headers['Cookie'] = cookie_header
    if solution.user_agent:
        headers['User-Agent'] = solution.user_agent
    out['headers'] = headers
    return out


def fetch_with_challenge_retry(
    method: str,
    url: str,
    *,
    session: requests.Session | None = None,
    validator: Any = None,
    _solver_used: bool = False,
    **kwargs: Any,
) -> requests.Response:
    """HTTP fetch with at most one challenge-solver retry when enabled.

    Pass *validator* (one of the ``validate_*_http_url`` helpers) to have every
    redirect hop revalidated instead of only the URL handed in — indexer hosts
    are operator-supplied, so an indexer that answers ``302`` should not be able
    to redirect the fetch somewhere the validator would have refused.
    """
    http = session or requests
    timeout = kwargs.pop('timeout', DEFAULT_TIMEOUT_SEC)

    if validator is not None:
        from oneirodex.utils.http_safe import safe_request

        def request_fn(target, **call_kwargs):
            return safe_request(
                method, target, validator=validator, session=session, **call_kwargs
            )
    else:
        request_fn = getattr(http, method.lower())

    resp = request_fn(url, timeout=timeout, **kwargs)

    if _solver_used or not is_challenge_response(resp):
        return resp
    if not challenge_solver_enabled():
        return resp

    client = _solver_client()
    if client is None:
        return resp

    try:
        solution = client.request_get(url)
        _set_last_error(None)
    except Exception as exc:
        _set_last_error(_safe_solver_error(exc))
        logger.warning(
            'Challenge solver request failed (error_type=%s)',
            type(exc).__name__,
        )
        return resp

    retry_kwargs = _apply_solution_to_request_kwargs(kwargs, solution)
    retry_resp = request_fn(url, timeout=timeout, **retry_kwargs)
    if is_challenge_response(retry_resp) and solution.body:
        retry_resp._content = solution.body.encode('utf-8', errors='replace')  # type: ignore[attr-defined]
        retry_resp.status_code = solution.status_code
    return retry_resp


def challenge_solver_status(*, probe: bool = False, config=None) -> dict[str, Any]:
    cfg = get_challenge_config(config)
    reachable = False
    error = _LAST_ERROR
    probe_ok = False
    if cfg.get('enabled') and cfg.get('url'):
        if probe:
            client = _solver_client(config)
            if client is None:
                error = error or 'Solver URL invalid or not configured'
            else:
                try:
                    solution = client.request_get('https://www.cloudflare.com/cdn-cgi/trace')
                    reachable = True
                    probe_ok = solution.status_code < 500
                    _set_last_error(None)
                except Exception as exc:
                    error = _safe_solver_error(exc)
                    _set_last_error(error)
        else:
            try:
                ok, _ = validate_connector_http_url(cfg['url'])
                reachable = ok
                if not ok:
                    error = 'Solver URL failed validation'
            except Exception as exc:
                error = f'Solver URL validation failed ({type(exc).__name__}).'
    return {
        'enabled': cfg.get('enabled'),
        'env_enabled': cfg.get('env_enabled'),
        'db_enabled': cfg.get('db_enabled'),
        'url': cfg.get('url') or None,
        'provider': cfg.get('provider'),
        'max_tier': cfg.get('max_tier'),
        'timeout_ms': cfg.get('timeout_ms'),
        'token_api_configured': cfg.get('token_api_configured'),
        'reachable': reachable,
        'probe_ok': probe_ok if probe else None,
        'last_error': error,
        'note': 'Opt-in BYO sidecar — never expose solver ports publicly.',
    }
