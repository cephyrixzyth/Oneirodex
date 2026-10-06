"""Report kind — bug report vs feature request.

"Report issue" collected both into one undifferentiated pile, so triage had to
read every title to sort them, and a request filed as a bug read as a broken
product.
"""

from uuid import uuid4

import pytest
from unittest.mock import patch

from oneirodex.models import SupportTicket, User


@pytest.fixture
def member(db_session):
    suffix = str(uuid4())[:8]
    user = User(
        name=f'reporter_{suffix}',
        email=f'reporter_{suffix}@example.com',
        password_hash='placeholder',
        role='user',
        user_id=str(uuid4()),
        invite_quota=0,
    )
    user.set_password('a good long password')
    db_session.add(user)
    db_session.commit()
    return user


def login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def _create(client, **body):
    payload = {'title': 'Something to report'}
    payload.update(body)
    return client.post('/api/support/tickets', json=payload)


class TestReportKind:
    def test_defaults_to_issue_when_unstated(self, client, member):
        login(client, member)
        response = _create(client)

        assert response.status_code == 201
        assert response.get_json()['ticket']['kind'] == 'issue'

    def test_an_enhancement_is_recorded_as_one(self, client, db_session, member):
        login(client, member)
        response = _create(client, kind='enhancement')

        assert response.status_code == 201
        ticket_id = response.get_json()['ticket']['id']
        assert db_session.get(SupportTicket, ticket_id).kind == 'enhancement'

    def test_an_unknown_kind_falls_back_rather_than_failing(self, client, member):
        # Losing a report someone took time to write, over a bad enum, is worse
        # than filing it under the safer of the two labels.
        login(client, member)
        response = _create(client, kind='wishlist')

        assert response.status_code == 201
        assert response.get_json()['ticket']['kind'] == 'issue'

    def test_kind_is_normalised(self, client, member):
        login(client, member)
        response = _create(client, kind='  ENHANCEMENT  ')

        assert response.get_json()['ticket']['kind'] == 'enhancement'

    def test_kind_reaches_the_listing(self, client, member):
        login(client, member)
        _create(client, kind='enhancement')

        rows = client.get('/api/support/tickets').get_json()['tickets']
        assert any(row.get('kind') == 'enhancement' for row in rows)

    def test_ticket_submission_is_limited_per_account(self, client, member):
        login(client, member)
        with patch(
            'oneirodex.routes_apis.support.create_github_issue',
            return_value={'ok': False, 'skipped': True},
        ) as create_issue:
            responses = [_create(client, title=f'Report {index}') for index in range(5)]
            rejected = _create(client, title='One too many')

        assert all(response.status_code == 201 for response in responses)
        assert rejected.status_code == 429
        assert rejected.get_json()['error_code'] == 'rate_limited'
        assert create_issue.call_count == 5
