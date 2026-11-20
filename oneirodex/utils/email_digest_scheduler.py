"""Background scheduler for batched notification email digests."""

from __future__ import annotations

from oneirodex.utils.periodic_worker import PeriodicWorker

_scheduler = PeriodicWorker('oneirodex-email-digest')


def _is_enabled(app) -> bool:
    return bool(app.config.get('ENABLE_EMAIL_DIGEST', True))


def _poll_seconds(app) -> int:
    try:
        hours = float(app.config.get('EMAIL_DIGEST_INTERVAL_HOURS') or 24)
    except (TypeError, ValueError):
        hours = 24.0
    hours = max(1.0, min(hours, 168.0))
    return int(hours * 3600)


def start_email_digest_scheduler(app):
    """Start a daemon that sends opted-in digests (idempotent)."""
    if not _is_enabled(app):
        print('[EMAIL DIGEST] Disabled (ENABLE_EMAIL_DIGEST=false)')
        return

    interval = _poll_seconds(app)

    def run_once():
        try:
            with app.app_context():
                from oneirodex.utils.email_digest import run_email_digest_batch

                stats = run_email_digest_batch()
                print(
                    f"[EMAIL DIGEST] considered={stats.get('considered')} "
                    f"sent={stats.get('sent')} skipped={stats.get('skipped')}"
                )
        except Exception as exc:
            print(f'[EMAIL DIGEST] Error: {exc}')

    return _scheduler.start(run_once, interval=interval, delay=60)
