"""Resource limits shared by store ownership import entry points."""

MAX_OWNERSHIP_CSV_BYTES = 16 * 1024 * 1024
# Leave room for JSON escaping and multipart framing while keeping the complete
# request well below the application-wide upload ceiling.
MAX_OWNERSHIP_CSV_REQUEST_BYTES = MAX_OWNERSHIP_CSV_BYTES * 2 + 1024 * 1024
MAX_OWNERSHIP_CSV_REQUEST_MIB = MAX_OWNERSHIP_CSV_REQUEST_BYTES // (1024 * 1024)

# Imports and live syncs can be repeated with new identifiers, so per-request
# byte/title limits do not bound persistent rows. Keep one household account's
# ownership register finite while leaving room for large multi-store libraries.
MAX_OWNED_TITLES_PER_USER = 100_000
OWNERSHIP_REGISTER_LIMIT_ERROR = (
    f'Ownership register reached the {MAX_OWNED_TITLES_PER_USER:,}-title safety limit.'
)
