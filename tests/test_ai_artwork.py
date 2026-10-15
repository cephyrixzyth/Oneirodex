"""FEAT-D3 — generated cover art adapter.

The privacy assertions matter most: this is the first feature that sends
anything off-process, so what the prompt may contain is pinned by tests rather
than left to review.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from oneirodex.utils.ai_artwork import (
    A1111Generator,
    ArtworkGenerationError,
    ComfyUIGenerator,
    build_prompt,
    generate_cover_bytes,
    get_generator,
)

# 1x1 PNG
PNG_B64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)


class TestPrompt:
    def test_uses_catalogue_facts(self):
        prompt = build_prompt(name='Portal 2', platform='PC Windows', genres=['Puzzle'])
        assert 'Portal 2' in prompt
        assert 'PC Windows' in prompt
        assert 'Puzzle' in prompt

    def test_never_leaks_paths_or_identity(self):
        """The prompt is built from arguments only — a caller cannot smuggle
        a file path in by passing extra context, because there is nowhere to
        put it."""
        prompt = build_prompt(
            name='Portal 2',
            platform='PC Windows',
            genres=['Puzzle', 'Adventure'],
        )
        for leak in ('/mnt/', 'C:\\', 'Z:\\', 'user', 'library_uuid', '.exe'):
            assert leak.lower() not in prompt.lower()

    def test_caps_genres_so_the_prompt_stays_a_title_not_a_dossier(self):
        prompt = build_prompt(
            name='Game',
            genres=['A', 'B', 'C', 'D', 'E'],
        )
        assert 'D' not in prompt.split(',')[1:4]

    def test_requires_a_title(self):
        with pytest.raises(ValueError):
            build_prompt(name='')


class TestA1111Adapter:
    @patch('oneirodex.utils.ai_artwork.requests.post')
    def test_decodes_returned_image(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: {'images': [PNG_B64]},
        )
        data = A1111Generator('http://sd:7860').generate(
            'x', width=512, height=768, timeout=5,
        )
        assert data.startswith(b'\x89PNG')
        assert mock_post.call_args.kwargs['allow_redirects'] is False

    @patch('oneirodex.utils.ai_artwork.requests.post')
    def test_tolerates_a_data_url_prefix(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: {'images': [f'data:image/png;base64,{PNG_B64}']},
        )
        data = A1111Generator('http://sd:7860').generate(
            'x', width=512, height=768, timeout=5,
        )
        assert data.startswith(b'\x89PNG')

    @patch('oneirodex.utils.ai_artwork.requests.post')
    def test_http_error_is_reported_not_swallowed(self, mock_post):
        mock_post.return_value = MagicMock(status_code=500, json=lambda: {})
        with pytest.raises(ArtworkGenerationError, match='HTTP 500'):
            A1111Generator('http://sd:7860').generate('x', width=1, height=1, timeout=1)

    @patch('oneirodex.utils.ai_artwork.requests.post')
    def test_redirect_is_rejected_without_following(self, mock_post):
        mock_post.return_value = MagicMock(status_code=302, json=lambda: {})
        with pytest.raises(ArtworkGenerationError, match='HTTP 302'):
            A1111Generator('http://sd:7860').generate('x', width=1, height=1, timeout=1)
        assert mock_post.call_args.kwargs['allow_redirects'] is False

    @patch('oneirodex.utils.ai_artwork.requests.post')
    def test_empty_image_list_is_an_error(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {'images': []})
        with pytest.raises(ArtworkGenerationError, match='no image'):
            A1111Generator('http://sd:7860').generate('x', width=1, height=1, timeout=1)

    @patch('oneirodex.utils.ai_artwork.requests.post')
    def test_unreachable_endpoint_is_an_error(self, mock_post):
        import requests as _requests

        mock_post.side_effect = _requests.RequestException(
            'refused https://user:password@sd.local:7860/generate?token=secret'
        )
        with pytest.raises(ArtworkGenerationError) as error:
            A1111Generator('http://sd:7860').generate('x', width=1, height=1, timeout=1)
        assert 'unreachable' in str(error.value)
        assert 'password' not in str(error.value)
        assert 'token=secret' not in str(error.value)


class TestComfyUI:
    def test_fails_honestly_rather_than_guessing_a_workflow(self):
        with pytest.raises(ArtworkGenerationError, match='workflow'):
            ComfyUIGenerator('http://comfy:8188').generate(
                'x', width=1, height=1, timeout=1,
            )


class TestGating:
    def test_disabled_by_default(self, app):
        with app.app_context():
            app.config['ENABLE_AI_ARTWORK'] = False
            with pytest.raises(ArtworkGenerationError, match='disabled'):
                generate_cover_bytes(name='Portal 2')

    def test_enabled_but_unconfigured_is_a_clear_error(self, app):
        with app.app_context():
            app.config['ENABLE_AI_ARTWORK'] = True
            app.config['AI_ARTWORK_URL'] = ''
            with pytest.raises(ArtworkGenerationError, match='not configured'):
                generate_cover_bytes(name='Portal 2')

    def test_unknown_engine_is_rejected(self, app):
        with app.app_context():
            app.config['ENABLE_AI_ARTWORK'] = True
            app.config['AI_ARTWORK_URL'] = 'http://sd:7860'
            app.config['AI_ARTWORK_ENGINE'] = 'dall-e'
            with pytest.raises(ArtworkGenerationError, match='Unknown'):
                get_generator()

    def test_a1111_aliases_all_resolve(self, app):
        with app.app_context():
            app.config['AI_ARTWORK_URL'] = 'http://sd:7860'
            for alias in ('a1111', 'automatic1111', 'sdnext', 'forge'):
                app.config['AI_ARTWORK_ENGINE'] = alias
                assert isinstance(get_generator(), A1111Generator)
