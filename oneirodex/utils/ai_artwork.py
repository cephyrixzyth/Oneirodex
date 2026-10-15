"""Generated cover art for titles with missing or poor artwork (FEAT-D3).

Stance
------
This is the first feature that sends anything to an endpoint outside the
process, so the boundaries are narrow and enforced here rather than left to
call sites:

* **Off by default.** ``ENABLE_AI_ARTWORK`` must be truthy.
* **Prompt carries only catalogue facts** — title, platform, genres. Never file
  paths, library layout, usernames, ownership, or anything identifying the
  install. :func:`build_prompt` is the only thing that composes the payload, so
  there is one place to audit.
* **Self-hosted first.** The default adapter speaks the A1111 HTTP API, which
  AUTOMATIC1111, SD.Next and Forge all implement, so an operator can point at a
  box they run and nothing leaves their network.
* **Generated art is labelled** as generated when persisted, so it can be found
  and replaced later rather than masquerading as real cover art.

Adding an engine means implementing :class:`ArtworkGenerator`; nothing else
should need to change.
"""

from __future__ import annotations

import base64
import os
from typing import Protocol

import requests

# Kept short: the prompt is catalogue facts, not a creative brief, and a long
# tail of adjectives makes the output less recognisable rather than more.
_STYLE_SUFFIX = 'video game cover art, key art composition, high detail'
_NEGATIVE = 'text, watermark, signature, logo, blurry, lowres, jpeg artifacts'

DEFAULT_STEPS = 25
DEFAULT_WIDTH = 512
DEFAULT_HEIGHT = 768  # 2:3, matching the cover aspect used by tiles


class ArtworkGenerationError(RuntimeError):
    """Generation failed. Never fatal — callers keep the existing artwork."""


def ai_artwork_enabled(config=None) -> bool:
    if config is not None:
        return bool(config.get('ENABLE_AI_ARTWORK', False))
    try:
        from flask import current_app

        return bool(current_app.config.get('ENABLE_AI_ARTWORK', False))
    except (ImportError, RuntimeError):
        return os.getenv('ENABLE_AI_ARTWORK', 'false').lower() in ('1', 'true', 'yes')


def artwork_endpoint(config=None) -> str:
    if config is not None:
        return (config.get('AI_ARTWORK_URL') or '').rstrip('/')
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            return (current_app.config.get('AI_ARTWORK_URL') or '').rstrip('/')
    except (ImportError, RuntimeError):
        pass
    return (os.getenv('AI_ARTWORK_URL') or '').rstrip('/')


def artwork_engine(config=None) -> str:
    if config is not None:
        return (config.get('AI_ARTWORK_ENGINE') or 'a1111').strip().lower()
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            return (current_app.config.get('AI_ARTWORK_ENGINE') or 'a1111').strip().lower()
    except (ImportError, RuntimeError):
        pass
    return (os.getenv('AI_ARTWORK_ENGINE') or 'a1111').strip().lower()


def build_prompt(*, name: str, platform: str | None = None, genres=None) -> str:
    """Compose the prompt from catalogue facts only.

    The single place a payload is built, so what leaves the box is auditable in
    one function rather than spread across call sites.
    """
    title = (name or '').strip()
    if not title:
        raise ValueError('A title is required to generate artwork')

    parts = [title]
    if platform:
        parts.append(f'{str(platform).strip()} game')
    genre_list = [str(g).strip() for g in (genres or []) if str(g).strip()][:3]
    if genre_list:
        parts.append(', '.join(genre_list))
    parts.append(_STYLE_SUFFIX)
    return ', '.join(parts)


class ArtworkGenerator(Protocol):
    """One method: prompt in, PNG/JPEG bytes out."""

    def generate(
        self,
        prompt: str,
        *,
        width: int,
        height: int,
        timeout: float,
        negative_prompt: str | None = None,
    ) -> bytes:
        ...


class A1111Generator:
    """AUTOMATIC1111 / SD.Next / Forge — the ``/sdapi/v1/txt2img`` contract."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    def generate(
        self,
        prompt: str,
        *,
        width: int,
        height: int,
        timeout: float,
        negative_prompt: str | None = None,
    ) -> bytes:
        payload = {
            'prompt': prompt,
            'negative_prompt': negative_prompt if negative_prompt is not None else _NEGATIVE,
            'steps': DEFAULT_STEPS,
            'width': width,
            'height': height,
            'batch_size': 1,
        }
        try:
            response = requests.post(
                f'{self.base_url}/sdapi/v1/txt2img',
                json=payload,
                timeout=timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            # requests exceptions can embed the configured URL, including
            # credentials or signed query parameters. Keep the public error
            # useful without reflecting endpoint details.
            raise ArtworkGenerationError('Artwork endpoint unreachable') from exc

        if response.status_code != 200:
            raise ArtworkGenerationError(
                f'Artwork endpoint returned HTTP {response.status_code}',
            )
        try:
            images = (response.json() or {}).get('images') or []
        except ValueError as exc:
            raise ArtworkGenerationError('Artwork endpoint returned invalid JSON') from exc
        if not images:
            raise ArtworkGenerationError('Artwork endpoint returned no image')

        raw = images[0]
        # Some builds prefix a data URL; tolerate both shapes.
        if ',' in raw and raw.strip().startswith('data:'):
            raw = raw.split(',', 1)[1]
        try:
            return base64.b64decode(raw)
        except (ValueError, TypeError) as exc:
            raise ArtworkGenerationError('Artwork endpoint returned undecodable image') from exc


class ComfyUIGenerator:
    """ComfyUI adapter.

    Deliberately a stub with an honest failure rather than a half-working
    guess: ComfyUI's ``/prompt`` takes a full workflow graph, so a real
    implementation needs an operator-supplied workflow JSON with a known
    prompt-injection point. Wiring that blind would silently generate against
    the wrong nodes.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    def generate(
        self,
        prompt: str,
        *,
        width: int,
        height: int,
        timeout: float,
        negative_prompt: str | None = None,
    ) -> bytes:
        raise ArtworkGenerationError(
            'ComfyUI support needs an operator-supplied workflow JSON '
            '(AI_ARTWORK_WORKFLOW). Use AI_ARTWORK_ENGINE=a1111 for now.',
        )


def get_generator(config=None) -> ArtworkGenerator:
    endpoint = artwork_endpoint(config)
    if not endpoint:
        raise ArtworkGenerationError('AI_ARTWORK_URL is not configured')
    engine = artwork_engine(config)
    if engine in ('a1111', 'automatic1111', 'sdnext', 'forge'):
        return A1111Generator(endpoint)
    if engine == 'comfyui':
        return ComfyUIGenerator(endpoint)
    raise ArtworkGenerationError(f'Unknown AI_ARTWORK_ENGINE: {engine}')


def generate_cover_bytes(
    *,
    name: str,
    platform: str | None = None,
    genres=None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    timeout: float = 120.0,
    config=None,
) -> bytes:
    """Generate cover bytes for a title. Raises :class:`ArtworkGenerationError`.

    Callers should treat failure as "keep what you have" — generated art is an
    improvement on a placeholder, never a reason to lose existing artwork.
    """
    if not ai_artwork_enabled(config):
        raise ArtworkGenerationError('AI artwork is disabled (ENABLE_AI_ARTWORK)')
    prompt = build_prompt(name=name, platform=platform, genres=genres)
    return get_generator(config).generate(prompt, width=width, height=height, timeout=timeout)


def generate_and_store_cover(
    game_uuid: str, *, image_type: str = 'cover', config=None,
) -> dict:
    """Generate artwork for a game and persist it, labelled as generated.

    Never destroys existing artwork on failure — a generation miss leaves the
    game exactly as it was. Singular kinds replace their previous *generated*
    row only, so a real cover a librarian picked is not silently overwritten.
    """
    import os
    import uuid as _uuid

    from sqlalchemy import select
    from werkzeug.utils import secure_filename

    from oneirodex.runtime_native.db_session import native_db as db
    from oneirodex.models import Game, Image
    from oneirodex.utils.image_kinds import SINGULAR_IMAGE_KINDS, parse_image_kind

    if config is None:
        from flask import current_app
        runtime_config = current_app.config
    else:
        runtime_config = config

    kind = parse_image_kind(image_type, default='cover')

    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        raise LookupError('Game not found')

    data = generate_cover_bytes(
        name=game.name,
        platform=getattr(getattr(game, 'library', None), 'platform', None)
        and game.library.platform.value,
        genres=[g.name for g in (game.genres or [])],
        config=runtime_config,
    )
    if not data:
        raise ArtworkGenerationError('Generator returned no data')

    engine = artwork_engine(runtime_config)
    file_name = secure_filename(f'{game_uuid}_{kind}_gen_{_uuid.uuid4().hex[:10]}.png')
    save_dir = runtime_config['IMAGE_SAVE_PATH']
    os.makedirs(save_dir, exist_ok=True)
    with open(os.path.join(save_dir, file_name), 'wb') as handle:
        handle.write(data)

    # Replace a previous *generated* row of this kind, never a curated one.
    if kind in SINGULAR_IMAGE_KINDS:
        stale = db.session.execute(
            select(Image).filter_by(
                game_uuid=game_uuid, image_type=kind, is_generated=True,
            )
        ).scalars().all()
        for row in stale:
            db.session.delete(row)

    image = Image(
        game_uuid=game_uuid,
        image_type=kind,
        url=file_name,
        is_downloaded=True,
        is_generated=True,
        generated_by=engine,
    )
    db.session.add(image)
    db.session.commit()

    static_url_path = (runtime_config.get('STATIC_URL_PATH') or '/static').rstrip('/')
    return {
        'game_uuid': game_uuid,
        'image_id': image.id,
        'kind': kind,
        'filename': file_name,
        'url': f'{static_url_path}/library/images/{file_name}',
        'generated_by': engine,
        'is_generated': True,
    }
