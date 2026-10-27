"""Resource limits shared by store ownership import entry points."""

MAX_OWNERSHIP_CSV_BYTES = 16 * 1024 * 1024
# Leave room for JSON escaping and multipart framing while keeping the complete
# request well below the application-wide upload ceiling.
MAX_OWNERSHIP_CSV_REQUEST_BYTES = MAX_OWNERSHIP_CSV_BYTES * 2 + 1024 * 1024
MAX_OWNERSHIP_CSV_REQUEST_MIB = MAX_OWNERSHIP_CSV_REQUEST_BYTES // (1024 * 1024)
