ARG BUILD_FROM
FROM ${BUILD_FROM:-crocodilestick/calibre-web-automated:v4.0.6}

ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install bashio so init scripts can use bashio::config / bashio::log.
# Upstream image is Ubuntu Noble (LSIO base) — jq is already present but pin it.
ARG BASHIO_VERSION="0.16.2"
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
