ARG BUILD_FROM="crocodilestick/calibre-web-automated:v4.0.6"
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

# Install bashio so init scripts can use bashio::config / bashio::log.
# Upstream image is Ubuntu Noble (LSIO base) — jq is already present but pin it.
# Tailscale is bundled so the optional sidecar can be enabled at runtime via
# config without a rebuild. Version-pinned to keep image builds reproducible.
ARG BASHIO_VERSION="0.16.2"
ARG TAILSCALE_VERSION="1.96.4"
# hadolint ignore=DL3008
RUN \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        jq \
        curl \
        ca-certificates \
        gnupg \
        iptables \
    && curl -fsSL "https://github.com/hassio-addons/bashio/archive/v${BASHIO_VERSION}.tar.gz" \
        | tar -xzf - -C /tmp \
    && mv "/tmp/bashio-${BASHIO_VERSION}/lib" /usr/lib/bashio \
    && ln -s /usr/lib/bashio/bashio /usr/bin/bashio \
    && curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg \
        -o /usr/share/keyrings/tailscale-archive-keyring.gpg \
    && curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list \
        -o /etc/apt/sources.list.d/tailscale.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        "tailscale=${TAILSCALE_VERSION}" \
    && rm -rf "/tmp/bashio-${BASHIO_VERSION}" /var/lib/apt/lists/*

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
