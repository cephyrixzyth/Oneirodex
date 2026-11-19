"""Serve a validated byte range from an already authorized, open ZIP file."""
from __future__ import annotations

import hashlib
import os
import re


def snapshot(handle):
    stat = os.fstat(handle.fileno())
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def archive_identity(handle):
    initial = snapshot(handle)
    digest = hashlib.sha256()
    handle.seek(0)
    for chunk in iter(lambda: handle.read(1024 * 1024), b''):
        digest.update(chunk)
    handle.seek(0)
    if snapshot(handle) != initial:
        raise OSError('Archive changed during verification')
    return '"sha256-' + digest.hexdigest() + '"', initial[0]


def resolve_range(size, requested, validator, etag):
    if not requested or validator != etag:
        return 200, 0, size
    match = re.fullmatch(r'bytes=(\d{1,20})-', requested)
    if not match or int(match[1]) >= size:
        return 416, 0, 0
    start = int(match[1])
    return 206, start, size - start
