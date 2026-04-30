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

# Install Tailscale. Userspace networking mode (set via the s6 run script)
# means no /dev/net/tun, NET_ADMIN, or NET_RAW required — tailscaled runs as
# a userspace SOCKS/HTTP proxy and `tailscale serve` exposes localhost:8083
# to the tailnet. Tarball is fetched over HTTPS from the official publisher;
# matches upstream `hassio-addons/app-tailscale` precedent (no sha pin).
ARG TAILSCALE_VERSION="1.96.4"
RUN \
    case "${BUILD_ARCH}" in \
        amd64) TS_ARCH=amd64 ;; \
        aarch64) TS_ARCH=arm64 ;; \
        *) echo "Unsupported BUILD_ARCH: ${BUILD_ARCH}" >&2; exit 1 ;; \
    esac \
    && mkdir -p /opt/tailscale \
    && curl -fsSL "https://pkgs.tailscale.com/stable/tailscale_${TAILSCALE_VERSION}_${TS_ARCH}.tgz" \
        | tar -xzf - -C /opt/tailscale --strip-components=1 \
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
