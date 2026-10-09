"""Request models for ``oneirodex/routes_apis/scan.py`` and its H-D.4 siblings
``scan_unmatched.py`` / ``scan_unmatched_edit.py``.

The JSON routes in those modules are almost all
librarian/admin batch endpoints that:

* return partial-success bodies via ``_parse_batch_ids`` whose rejection
  carries ``cap`` / ``requested`` / per-id ``results`` — the admin SPA branches
  on that, not on a flat 422; or
* also read ``request.form`` / ``request.args`` in addition to the JSON body
  (``start_library_scan``, ``refresh_all_libraries``), so a JSON-only model
  cannot see the whole input; or
* attach ``body_status='rejected'`` + ``job_id`` / ``position`` / ``item_kinds``
  to the refusal for the operator UI to render.

``unmatched_flag_bad_match`` and ``backfill_unmatched_suggested_kind_route``
have no missing-field rejection to remove, so wrapping them buys only an
``extra='forbid'`` risk.

See docs/dev/pydantic-adoption.md for the follow-up plan.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PlaceUnmatchedUpdateBody(BaseModel):
    """Optional admin override for the root title when placing an update."""

    game_root_name: str | None = Field(default=None, max_length=255)

    model_config = ConfigDict(extra='forbid')
