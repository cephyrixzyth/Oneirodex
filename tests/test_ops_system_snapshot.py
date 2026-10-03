"""GET /admin/api/ops/system must answer once the install has logged an event.

Found by the virtual-device UI sweep: ``get_log_info()['latest']`` is an ORM row,
which ``jsonify`` cannot serialise, so the snapshot returned 503 on every
install with at least one SystemEvents row (every real one).
"""
from datetime import datetime, timezone
from uuid import uuid4

from flask_login import login_user

from oneirodex.models import SystemEvents, User


def _admin(db_session):
    uid = str(uuid4())
    row = User(name=f'ops_{uid[:8]}', email=f'ops_{uid[:8]}@example.com', role='admin', user_id=uid, state=True)
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


def _login(client, app, person):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(person.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(person)


def test_system_snapshot_serialises_the_latest_log_event(client, app, db_session):
    admin = _admin(db_session)
    db_session.add(SystemEvents(
        timestamp=datetime.now(timezone.utc), event_level='ERROR', event_type='log', event_text='sweep marker',
    ))
    db_session.commit()
    _login(client, app, admin)

    response = client.get('/admin/api/ops/system')

    assert response.status_code == 200, response.get_data(as_text=True)[:200]
    logs = response.get_json()['logs']
    assert logs['count'] >= 1
    assert logs['latest']['text'] == 'sweep marker'
    assert logs['latest']['level'] == 'ERROR'
    assert logs['latest']['timestamp']
