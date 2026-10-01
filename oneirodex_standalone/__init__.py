"""Standalone installs: the normal server plus a bundled user-space PostgreSQL (ADR 0011).

Lives outside the ``oneirodex`` package on purpose: importing ``oneirodex``
loads the app config, which needs the SECRET_KEY this launcher provides.
Nothing here imports ``oneirodex``.
"""
