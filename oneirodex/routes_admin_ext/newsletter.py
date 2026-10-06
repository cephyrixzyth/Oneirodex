# /oneirodex/routes_admin_ext/newsletter.py
from flask import render_template, redirect, url_for, flash, abort, request
from flask_login import login_required, current_user
from oneirodex.models import User, Newsletter
from oneirodex import db
from sqlalchemy import select
from oneirodex.forms import NewsletterForm
from . import admin2_bp
from oneirodex.utils.auth import admin_required
from oneirodex.utils.global_settings import global_settings_row
from oneirodex.utils.smtp import send_email_quiet

@admin2_bp.route('/admin/newsletter', methods=['GET', 'POST'])
@login_required
@admin_required
def newsletter():
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
    users = db.session.execute(select(User)).scalars().all()
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
    
    # Get all sent newsletters for display
    newsletters = db.session.execute(select(Newsletter).order_by(Newsletter.sent_date.desc())).scalars().all()
    return render_template('admin/admin_newsletter.html',
                         title='Newsletter', 
                         form=form, 
                         users=users,
                         newsletters=newsletters,
                         can_send=can_send,
                         smtp_ready=smtp_ready,
                         newsletter_enabled=enable_newsletter)

@admin2_bp.route('/admin/newsletter/<int:newsletter_id>')
@login_required
@admin_required
def view_newsletter(newsletter_id):
    newsletter = db.session.get(Newsletter, newsletter_id) or abort(404)
    return render_template('admin/view_newsletter.html', 
                         title='View Newsletter',
                         newsletter=newsletter)
