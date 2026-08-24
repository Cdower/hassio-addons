ARG BUILD_FROM="ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.24-2026.08.0"
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

SHELL ["/bin/ash", "-o", "pipefail", "-c"]

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/acpro

# cryptography and paho-mqtt both publish musllinux wheels for amd64 and
# aarch64, so no compiler toolchain is needed in the image.
COPY requirements.txt /tmp/requirements.txt
RUN \
    pip3 install --no-cache-dir --only-binary=:all: -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

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
