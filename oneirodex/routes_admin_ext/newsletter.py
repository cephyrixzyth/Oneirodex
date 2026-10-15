# /oneirodex/routes_admin_ext/newsletter.py
from flask import redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from oneirodex.models import User, Newsletter
from oneirodex import db
from sqlalchemy import select
from oneirodex.forms import NewsletterForm
from . import admin2_bp
from oneirodex.utils.auth import admin_required
from oneirodex.utils.global_settings import global_settings_row
from oneirodex.utils.smtp import send_email_quiet
from oneirodex.utils.admin_spa import render_admin_spa

@admin2_bp.route('/admin/newsletter', methods=['GET', 'POST'])
@login_required
@admin_required
def newsletter():
    if request.method == 'GET':
        return render_admin_spa(title='Newsletter · Oneirodex Admin')

    settings_record = global_settings_row()
    # Keep this page useful even before SMTP is configured: admins can inspect
    # history and see exactly what remains before sending becomes available.
    enable_newsletter = bool(
        (settings_record.settings or {}).get('enableNewsletterFeature', False)
    ) if settings_record else False
    smtp_ready = bool(
        settings_record
        and settings_record.smtp_enabled
        and settings_record.smtp_server
        and settings_record.smtp_default_sender
    )
    can_send = bool(enable_newsletter and smtp_ready)

    form = NewsletterForm()
    if form.validate_on_submit():
        if not can_send:
            flash('Enable the newsletter feature and configure SMTP before sending.', 'warning')
            return redirect(url_for('admin2.newsletter'))
        recipients = [
            addr.strip()
            for addr in (form.recipients.data or '').split(',')
            if addr.strip()
        ]
        new_newsletter = Newsletter(
            subject=form.subject.data,
            content=form.content.data,
            sender_id=current_user.id,
            recipient_count=len(recipients),
            recipients=recipients,
            status='pending'
        )
        db.session.add(new_newsletter)
        db.session.commit()

        failed = []
        for addr in recipients:
            if not send_email_quiet(addr, form.subject.data, form.content.data):
                failed.append(addr)

        if failed:
            new_newsletter.status = 'failed'
            new_newsletter.error_message = (
                'Failed to send to: ' + ', '.join(failed)
            )
            db.session.commit()
            flash(new_newsletter.error_message, 'error')
        else:
            new_newsletter.status = 'sent'
            db.session.commit()
            flash('Newsletter sent successfully!', 'success')
        return redirect(url_for('admin2.newsletter'))
    
    if form.errors:
        flash('Please correct the errors below.', 'error')
    return render_admin_spa(title='Newsletter · Oneirodex Admin')

@admin2_bp.route('/admin/newsletter/<int:newsletter_id>')
@login_required
@admin_required
def view_newsletter(newsletter_id):
    return render_admin_spa(title='Newsletter detail · Oneirodex Admin')


# Additive JSON contract; legacy form routes remain available when pilot is off.
from oneirodex.utils.api_response import api_ok, api_error


def newsletter_readiness():
    settings = global_settings_row()
    enabled = bool(settings and (settings.settings or {}).get('enableNewsletterFeature', False))
    smtp = bool(settings and settings.smtp_enabled and settings.smtp_server and settings.smtp_default_sender)
    return {'newsletter_enabled': enabled, 'smtp_ready': smtp, 'can_send': enabled and smtp}


def newsletter_summary(row):
    return {'id': row.id, 'subject': row.subject,
            'sent_date': row.sent_date.isoformat() if row.sent_date else None,
            'status': row.status if row.status in ('pending', 'sent', 'failed') else 'unknown',
            'recipient_count': row.recipient_count}


@admin2_bp.route('/api/admin/newsletters', methods=['GET'])
@login_required
@admin_required
def newsletter_state():
    try:
        users = db.session.execute(select(User)).scalars().all()
        history = db.session.execute(select(Newsletter).order_by(Newsletter.sent_date.desc())).scalars().all()
        response = current_app.make_response(api_ok({**newsletter_readiness(),
                           'recipients': [{'id': user.id, 'email': user.email} for user in users if user.email],
                           'newsletters': [newsletter_summary(row) for row in history]}))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except Exception:
        return api_error('Could not load newsletters.', code='internal')


@admin2_bp.route('/api/admin/newsletters/<int:newsletter_id>', methods=['GET'])
@login_required
@admin_required
def newsletter_detail_state(newsletter_id):
    if newsletter_id < 1 or newsletter_id > 2147483647:
        return api_error('Newsletter not found.', code='not_found')
    try:
        row = db.session.get(Newsletter, newsletter_id)
        if row is None:
            return api_error('Newsletter not found.', code='not_found')
        response = current_app.make_response(api_ok({'newsletter': {**newsletter_summary(row), 'content': row.content,
                          'sender': row.sender.name if row.sender else 'Unknown member',
                          # Historical error strings may contain transport credentials or paths.
                          'delivery_error': 'Some recipients could not be reached.' if row.status == 'failed' else None}}))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except Exception:
        return api_error('Could not load newsletter.', code='internal')


@admin2_bp.route('/api/admin/newsletters', methods=['POST'])
@login_required
@admin_required
def newsletter_send():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {'subject', 'content', 'recipients'}:
        return api_error('Provide a subject, content and selected recipients.', code='bad_request')
    subject, content, recipients = (payload[key] for key in ('subject', 'content', 'recipients'))
    if (not isinstance(subject, str) or not subject.strip() or len(subject) > 255
            or '\r' in subject or '\n' in subject
            or not isinstance(content, str) or not content.strip() or len(content) > 1048576
            or not isinstance(recipients, list) or not recipients
            or any(not isinstance(value, str) or not value or '\r' in value or '\n' in value for value in recipients)):
        return api_error('Enter a valid subject, message and recipients.', code='bad_request')
    try:
        if not newsletter_readiness()['can_send']:
            return api_error('Enable newsletters and configure SMTP before sending.', code='conflict')
        allowed = {user.email for user in db.session.execute(select(User)).scalars().all() if user.email}
        if any(value not in allowed for value in recipients):
            return api_error('Select existing member recipients.', code='bad_request')
        recipients = list(dict.fromkeys(recipients))
        row = Newsletter(subject=subject.strip(), content=content, sender_id=current_user.id,
                         recipient_count=len(recipients), recipients=recipients, status='pending')
        db.session.add(row)
        db.session.commit()
        failed = 0
        for address in recipients:
            try:
                delivered = send_email_quiet(address, row.subject, content)
            except Exception:
                delivered = False
            if not delivered:
                failed += 1
        row.status = 'failed' if failed else 'sent'
        row.error_message = f'Could not deliver to {failed} recipient(s).' if failed else None
        db.session.commit()
        return api_ok({'newsletter': newsletter_summary(row), 'failed_count': failed})
    except Exception:
        db.session.rollback()
        return api_error('Could not complete newsletter delivery. Check history before trying again.', code='internal')
