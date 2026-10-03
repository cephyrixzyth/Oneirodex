"""The Unraid Community Apps files must stay valid XML with the fields CA requires.

Community Apps rejects a repository whose `ca_profile.xml` has an empty `<Profile>`, and a
template that does not parse is silently skipped, so both are checked here rather than
at submission time.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _root(path):
    return ET.parse(ROOT / path).getroot()


def test_ca_profile_has_a_non_empty_profile_section():
    root = _root('ca_profile.xml')
    assert root.tag == 'CommunityApplications'
    profile = root.find('Profile')
    assert profile is not None
    assert len((profile.text or '').strip()) > 50


def test_ca_profile_links_point_at_this_project():
    root = _root('ca_profile.xml')
    for tag in ('Icon', 'WebPage'):
        node = root.find(tag)
        assert node is not None and node.text and node.text.strip().startswith('https://')
    # Icon must be a file that actually ships in the repo (the raw URL maps onto it).
    icon = root.find('Icon').text.strip()
    relative = icon.split('/main/', 1)[1]
    assert (ROOT / relative).is_file()


def test_container_template_parses_and_names_its_image():
    root = _root('unraid/oneirodex.xml')
    assert root.tag == 'Container'
    assert (root.findtext('Repository') or '').startswith('chrisjrovira/oneirodex')
    assert (root.findtext('Overview') or '').strip()
    assert (root.findtext('Support') or '').startswith('https://')
