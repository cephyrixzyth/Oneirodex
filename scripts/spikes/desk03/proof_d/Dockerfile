# DESK-04 proof image (throwaway): the app image plus a relocated PostgreSQL 17
# bundle, laid out the way a standalone Linux download would carry it.
FROM postgres:17.6 AS pg
COPY make_bundle.sh /make_bundle.sh
RUN bash /make_bundle.sh /bundle

FROM oneirodex:review
COPY --from=pg /bundle /opt/oneirodex-postgres
