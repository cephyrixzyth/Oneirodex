"""DB-free whitelist validation."""
import pytest
from pydantic import ValidationError
from oneirodex.schemas.whitelist import AddWhitelistBody


def test_normalizes_existing_form_case_and_whitespace():
    assert AddWhitelistBody(email=' Person@Example.COM ').email == 'person@example.com'

@pytest.mark.parametrize('email', ['', 'bad', 'two@@example.com', 'a@', 'a'*121+'@example.com'])
def test_rejects_invalid_email(email):
    with pytest.raises(ValidationError):
        AddWhitelistBody(email=email)
