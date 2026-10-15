from flask import Blueprint
from flask_login import login_required
from oneirodex.utils.member_spa import render_member_spa

from oneirodex.utils.discover_projections import serialize_discover_game
from oneirodex.utils.discover_builder import (
    build_discover_feed, build_discover_sections, build_discover_zone,
    build_discover_row, MAX_ROW_OFFSET, MAX_ROW_LIMIT,
)
from oneirodex.utils.discover_feed import (
    FEED_ROW_CAP,
    assemble,
    excluded_for,
    manifest_from,
)
from oneirodex.utils.discover_pins import admin_forced, hidden_rows, member_pins
from oneirodex.utils.discover_hydrate import DiscoverHydration
from oneirodex.utils.discover_providers import (
    ROW_MAX,
    ROW_WINDOW,
    resolve_feed,
    resolve_identifier,
)
from oneirodex.utils.discover_zones import (
    resolve_zone,
    rows_in_zone,
    zone_for_row,
    zone_index,
)

discover_bp = Blueprint('discover', __name__)


# The four-identifier allow-list that used to live here is gone. Hiding an
# empty row is now `RowSpec.hide_when_empty`, applied in `discover_feed.assemble`
# — which is where it belongs, because a dropped row should free its slot for a
# row that missed the cut, and a filter applied after assembly cannot do that.
# The allow-list also only ever covered the four storefront shelves, so
# "Friends playing" with no friends still rendered as a heading over nothing.

# How far a row endpoint will page. Guards against a caller asking for an
# arbitrary offset and making the server walk the whole library to answer.

# How deep the row endpoint probes when it is trying to report a total.
#
# A selector takes a limit and returns rows; there is no count sibling, and
# adding one would mean writing every row's query twice and keeping the two in
# step forever. So the total is derived from the selection instead: ask for more
# than the window, and if the source returns fewer than were asked for, the
# source is exhausted and the count is exact.
#
# 200 is chosen to make that the common case rather than the lucky one — it is
# five times the row ceiling, so any row on a household-sized library resolves
# exactly. Past it the endpoint says it does not know rather than guessing,
# which is the whole point of `total_is_estimate`.

# How long a feed's dedupe record outlives the request that built it. Long
# enough to cover a browsing session; short enough that a stale arrangement
# does not follow a member into the next one.


























@discover_bp.route('/discover')
@login_required
def discover():
    # Shelves load client-side via GET /api/discover/sections (keeps HTML shell light).
    return render_member_spa()


@discover_bp.route('/discover/hub/genre/<path:genre>')
@login_required
def discover_genre_hub(genre):
    return render_member_spa(title='Discover')


@discover_bp.route('/discover/zone/<slug>')
@login_required
def discover_zone_page(slug):
    """SPA shell for a zone.

    Needed as its own route because `/discover/<identifier>` below matches a
    single segment: without this, `/discover/zone/popular` never reached the
    SPA at all and Flask 404'd before React Router could route it. The genre hub
    above has the same shape for the same reason.
    """
    return render_member_spa(title='Discover')


@discover_bp.route('/discover/<identifier>')
@login_required
def discover_row_page(identifier):
    return render_member_spa()
