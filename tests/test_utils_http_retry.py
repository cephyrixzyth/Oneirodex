"""Retry/backoff behaviour of request_with_backoff.

These patch `safe_get`, not `requests.get`. The function stopped calling
requests directly when outbound URLs were put behind the SSRF validator, and
these tests kept patching the old name — so the mock was never reached, every
call returned None, and the retry logic they exist to guard had no coverage at
all while the file sat red.
"""

from unittest.mock import patch, MagicMock

from oneirodex.utils.http_retry import request_with_backoff


@patch('oneirodex.utils.http_retry.time.sleep', return_value=None)
@patch('oneirodex.utils.http_retry.safe_get')
def test_retries_on_429_then_succeeds(mock_safe_get, mock_sleep):
    bad = MagicMock(status_code=429)
    good = MagicMock(status_code=200)
    mock_safe_get.side_effect = [bad, good]

    resp = request_with_backoff('https://example.com/x', host_key='example')
    assert resp is good
    assert mock_safe_get.call_count == 2
    assert mock_sleep.called


@patch('oneirodex.utils.http_retry.time.sleep', return_value=None)
@patch('oneirodex.utils.http_retry.safe_get')
def test_gives_up_after_max_retries(mock_safe_get, mock_sleep):
    mock_safe_get.return_value = MagicMock(status_code=503)
    resp = request_with_backoff('https://example.com/x', host_key='example', max_retries=3)
    assert resp is None
    assert mock_safe_get.call_count == 3


@patch('oneirodex.utils.http_retry.time.sleep', return_value=None)
@patch('oneirodex.utils.http_retry.safe_get')
def test_returns_none_on_non_retryable_status(mock_safe_get, mock_sleep):
    mock_safe_get.return_value = MagicMock(status_code=404)
    resp = request_with_backoff('https://example.com/x', host_key='example')
    assert resp is None
    assert mock_safe_get.call_count == 1


@patch('oneirodex.utils.http_retry.time.sleep', return_value=None)
@patch('oneirodex.utils.http_retry.safe_get')
def test_retries_on_request_exception_then_succeeds(mock_safe_get, mock_sleep):
    import requests

    good = MagicMock(status_code=200)
    mock_safe_get.side_effect = [requests.exceptions.Timeout('timed out'), good]

    resp = request_with_backoff('https://example.com/x', host_key='example')
    assert resp is good
    assert mock_safe_get.call_count == 2


@patch('oneirodex.utils.http_retry.time.sleep', return_value=None)
@patch('oneirodex.utils.http_retry.safe_get')
def test_exhausted_request_log_omits_exception_url_and_credentials(
    mock_safe_get, mock_sleep, capsys,
):
    import requests

    secret = 'provider-secret-value'
    mock_safe_get.side_effect = requests.exceptions.ConnectionError(
        f"failed https://provider.example/search?api_key={secret}"
    )

    assert request_with_backoff(
        'https://provider.example/search?api_key=' + secret,
        host_key='provider',
        max_retries=1,
    ) is None

    logged = capsys.readouterr().out
    assert 'http_retry exhausted for provider: ConnectionError' in logged
    assert secret not in logged
    assert 'provider.example' not in logged
