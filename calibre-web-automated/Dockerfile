ARG BUILD_FROM="ghcr.io/new-usemame/calibre-web-nextgen:v4.1.40"
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# LSIO base remaps its `abc` user to PUID:PGID at s6-overlay startup. HA's
# Supervisor owns /share and /media as 1000:1000, so without this the app
# (default 911:911) cannot write library_path / ingest_path.
ENV PUID=1000 \
    PGID=1000

# Opt in to user-installed Calibre plugins, which is what makes the add-on's
# `plugins_path` option actually work.
#
# CWA v4.0.6 exported `CALIBRE_CONFIG_DIR=/config/.config/calibre`. Calibre
# reads `CALIBRE_CONFIG_DIRECTORY`; it has never recognised that name, so the
# variable was inert and plugin loading only ever worked by accident of HOME.
# That is why the add-on used to warn about hand-writing `customize.py.json`.
# The NextGen base drops the misspelled name and gates the correctly-spelled
# one behind `CWA_CALIBRE_USER_PLUGINS`, which
# `cps/services/calibre_user_plugins.py` applies per Calibre subprocess
# (ingest, convert, cover-enforcer, embed-metadata). Setting the opt-in here
# turns that on image-wide and lets the boot-time `auto_library` pass register
# every .zip under `plugins_path` with `calibre-customize -a`.
#
# `CALIBRE_CONFIG_DIRECTORY` is then also set globally, for the Calibre
# invocations that do not route through that helper (`calibre-customize`
# itself, anything an operator runs from the add-on shell) so they all resolve
# the same directory the add-on bind-mounts `plugins_path` over. The base
# image deliberately omits it because a global value would force plugin
# loading on for every subprocess — here that is the intent, not a side
# effect. Nothing loads unless the operator puts a plugin in `plugins_path`.
ENV CWA_CALIBRE_USER_PLUGINS=1 \
    CALIBRE_CONFIG_DIRECTORY=/config/.config/calibre

# Install bashio so init scripts can use bashio::config / bashio::log.
# Base image is Ubuntu Noble (LSIO base) — jq is already present but pin it.
ARG BASHIO_VERSION="0.16.2"
# hadolint ignore=DL3008
RUN \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        jq \
        curl \
        ca-certificates \
    && curl -fsSL "https://github.com/hassio-addons/bashio/archive/v${BASHIO_VERSION}.tar.gz" \
        | tar -xzf - -C /tmp \
    && mv "/tmp/bashio-${BASHIO_VERSION}/lib" /usr/lib/bashio \
    && ln -s /usr/lib/bashio/bashio /usr/bin/bashio \
    && rm -rf "/tmp/bashio-${BASHIO_VERSION}" /var/lib/apt/lists/*

# nginx + PyJWT power the optional Cloudflare Access mode: nginx fronts CWA
# (LAN header-stripping listener on 8083, JWT-gated listener on 8085) and the
# verifier validates Cf-Access-Jwt-Assertion with PyJWT. PyJWT rides the
# /lsiopy venv, whose `cryptography` (upstream pyproject.toml) provides the
# RS256 backend. Ubuntu's nginx-core includes http_auth_request_module.
ARG PYJWT_VERSION="2.10.1"
# hadolint ignore=DL3008
RUN \
    apt-get update \
    && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default \
    && /lsiopy/bin/pip install --no-cache-dir "PyJWT==${PYJWT_VERSION}"

# Install Tailscale. Userspace networking mode (set via the s6 run script)
# means no /dev/net/tun, NET_ADMIN, or NET_RAW required — tailscaled runs as
# a userspace SOCKS/HTTP proxy and `tailscale serve` exposes localhost:8083
# to the tailnet. Tarball is fetched over HTTPS from the official publisher
# and verified against per-arch sha256 pinned below; bump TAILSCALE_VERSION
# and both hashes together when upgrading.
ARG TAILSCALE_VERSION="1.102.3"
ARG TAILSCALE_SHA256_AMD64="36ddd9b51be57ffc2990cf76323cfa13643bfbb1b8a969f6183fa164741cdef5"
ARG TAILSCALE_SHA256_ARM64="a0fa1b154af8c61f862a2259f559f7396d96c0225f4a863eae2333e1546bbe25"
RUN \
    case "${BUILD_ARCH}" in \
        amd64) TS_ARCH=amd64; TS_SHA256="${TAILSCALE_SHA256_AMD64}" ;; \
        aarch64) TS_ARCH=arm64; TS_SHA256="${TAILSCALE_SHA256_ARM64}" ;; \
        *) echo "Unsupported BUILD_ARCH: ${BUILD_ARCH}" >&2; exit 1 ;; \
    esac \
    && mkdir -p /opt/tailscale \
    && curl -fsSL -o /tmp/tailscale.tgz \
        "https://pkgs.tailscale.com/stable/tailscale_${TAILSCALE_VERSION}_${TS_ARCH}.tgz" \
    && echo "${TS_SHA256}  /tmp/tailscale.tgz" | sha256sum -c - \
    && tar -xzf /tmp/tailscale.tgz -C /opt/tailscale --strip-components=1 \
    && rm -f /tmp/tailscale.tgz \
    && rm -rf /opt/tailscale/systemd \
    && ln -sf /opt/tailscale/tailscale /usr/local/bin/tailscale \
    && ln -sf /opt/tailscale/tailscaled /usr/local/bin/tailscaled

COPY rootfs /

LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}" \
    org.opencontainers.image.created="${BUILD_DATE}" \
    org.opencontainers.image.revision="${BUILD_REF}" \
    org.opencontainers.image.source="${BUILD_REPOSITORY}" \
    org.opencontainers.image.version="${BUILD_VERSION}"
