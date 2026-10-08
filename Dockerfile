# SPA bundles contain only static assets. Build them on the native build
# platform so an arm64 image does not run npm install/build through QEMU.
FROM --platform=$BUILDPLATFORM node:22-alpine AS frontend-build

WORKDIR /build

# One workspace-aware install for all three SPAs (wave B1.1). The repo-root
# package.json declares the npm workspaces and the single root package-lock.json
# is the only lockfile — there is no per-app package-lock.json any more. Copy
# every workspace manifest first so `npm ci` can validate the graph against the
# root lock without the sources, then one install for the whole tree.
COPY package.json package-lock.json ./
COPY frontend/member-app/package.json frontend/member-app/
COPY frontend/admin-app/package.json frontend/admin-app/
COPY frontend/ops-glance/package.json frontend/ops-glance/
COPY frontend/api-client/package.json frontend/api-client/
COPY frontend/shared/package.json frontend/shared/
COPY clients/desktop/package.json clients/desktop/
RUN npm ci

# All three SPAs `extends` this from `frontend/<app>/tsconfig.json`
# (`../../tsconfig.base.json` → `/build/tsconfig.base.json`). Without it,
# `tsc --noEmit` in the image loses jsx/lib/moduleResolution and the
# frontend-build stage fails with hundreds of cascading TS errors.
COPY tsconfig.base.json ./

# App sources plus the shared workspace. frontend/shared is the `@oneirodex/ui`
# workspace now, but member-app/admin-app still import it by relative path, so it
# has to be on disk for the vite builds — `COPY frontend/` stages it (and
# dockerStagedImports.test.js enforces that a COPY covers it).
COPY frontend/ ./frontend/

# admin-app re-exports theme SoT (../../../oneirodex/... from src/); stage those
# files before the vite build. dockerStagedImports.test.js enforces this list.
COPY oneirodex/setup/default_theme/js/stageECandidates.js oneirodex/setup/default_theme/js/
COPY oneirodex/setup/default_theme/js/unmatchedTriage.js oneirodex/setup/default_theme/js/
COPY oneirodex/setup/default_theme/js/scanJobsDom.js oneirodex/setup/default_theme/js/

# vite writes each bundle to oneirodex/static/dist/<app>/ (outDir is resolved
# from the app dir in its vite.config); `npm run build` per workspace runs the
# app's `tsc --noEmit && vite build`.
RUN mkdir -p oneirodex/static/dist/member-app oneirodex/static/dist/admin-app oneirodex/static/dist/ops-glance \
    && npm run build --workspace=member-app \
    && npm run build --workspace=admin-app \
    && npm run build --workspace=ops-glance

FROM python:3.12-slim

WORKDIR /app

# Build identity. Unset is a supported state -- a hand-built image reads
# "n/a" on the Ops tile rather than claiming a commit it cannot know.
ARG ONEIRODEX_BUILD_SHA=""
ARG ONEIRODEX_BUILT_AT=""
ENV ONEIRODEX_BUILD_SHA=$ONEIRODEX_BUILD_SHA \
    ONEIRODEX_BUILT_AT=$ONEIRODEX_BUILT_AT

LABEL org.opencontainers.image.title="Oneirodex" \
      org.opencontainers.image.description="Self-hosted household game library" \
      org.opencontainers.image.source="https://github.com/cephyrixzyth/oneirodex" \
      org.opencontainers.image.revision="$ONEIRODEX_BUILD_SHA" \
      org.opencontainers.image.created="$ONEIRODEX_BUILT_AT"

# Install system dependencies (bash required by entrypoint/start scripts).
# libarchive-tools (bsdtar) and p7zip-full (7z) give rarfile a working
# extraction backend for .rar ROMs without needing Debian's non-free repo
# (plain `unrar` lives there and isn't enabled on this base image).
# postgresql-client gives `python -m oneirodex_standalone import` its
# pg_restore, for moving a standalone install onto this server (ADR 0011);
# Debian 13 ships PostgreSQL 17, the version standalone installs dump from.
#
# postgresql (server + client) is also installed so the image can run on its own
# with an embedded database when no DATABASE_URL is given (docker/embedded-db.sh,
# single-container / Unraid Community Apps install). The Compose stack keeps
# using its separate postgres:17 service and never starts this one. No cluster is
# created at build time: it is made on first start inside the /config volume.
RUN mkdir -p /etc/postgresql-common \
    && printf 'create_main_cluster = false\n' > /etc/postgresql-common/createcluster.conf \
    && apt-get update && apt-get install -y --no-install-recommends \
    curl \
    bash \
    libarchive-tools \
    p7zip-full \
    postgresql \
    postgresql-client \
    util-linux \
    && rm -rf /var/lib/apt/lists/*

COPY . .
COPY --from=frontend-build /build/oneirodex/static/dist/member-app /app/oneirodex/static/dist/member-app
COPY --from=frontend-build /build/oneirodex/static/dist/admin-app /app/oneirodex/static/dist/admin-app
COPY --from=frontend-build /build/oneirodex/static/dist/ops-glance /app/oneirodex/static/dist/ops-glance

RUN pip install -r requirements.txt
RUN sed -i 's/\r$//' /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/startweb-docker.sh
RUN sed -i 's/\r$//' /app/docker/embedded-db.sh
RUN chmod a+x /app/entrypoint.sh /app/docker/embedded-db.sh
RUN chmod a+x /app/startweb-docker.sh

# Appdata for the single-container install: embedded database, generated
# secrets, logs and (unless mounted separately) the library. Unused under Compose.
ENV ONEIRODEX_CONFIG_DIR=/config
RUN mkdir -p /config
VOLUME ["/config"]

EXPOSE 5006
ENTRYPOINT ["/bin/bash","/app/entrypoint.sh"]
