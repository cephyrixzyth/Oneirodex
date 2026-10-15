"""DB-free bounds and type checks for invite adjustments."""
import pytest
from pydantic import ValidationError
from oneirodex.schemas.invites import AdjustInviteQuotaBody

USER = '087671b7-6527-41b8-89cd-34beb13ab19d'

@pytest.mark.parametrize('value', [-1000, -1, 0, 1, 1000])
def test_valid_adjustment(value):
    body = AdjustInviteQuotaBody(user_id=USER, invites_number=value)
    assert body.invites_number == value
    assert str(body.user_id) == USER

@pytest.mark.parametrize('value', [-1001, 1001, True, 1.5, '1', None])
def test_reject_adjustment(value):
    with pytest.raises(ValidationError):
        AdjustInviteQuotaBody(user_id=USER, invites_number=value)

@pytest.mark.parametrize('payload', [{'user_id': 'bad', 'invites_number': 1}, {'user_id': USER}, {'user_id': USER, 'invites_number': 1, 'extra': 1}])
def test_reject_invalid_contract(payload):
    with pytest.raises(ValidationError):
        AdjustInviteQuotaBody.model_validate(payload)
