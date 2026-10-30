ARG BUILD_FROM="ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.24-2026.08.0"

# uv (https://docs.astral.sh/uv/) installs the add-on's Python dependencies
# from pyproject.toml / uv.lock. This stage only supplies the binary, which is
# bind-mounted into the one RUN step that needs it: nothing from it is in the
# released image. Pinned by tag and digest; Dependabot moves both. Keep the
# version in step with the uv set up in .github/workflows/ci.yaml.
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

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

# pyproject.toml declares the add-on's dependencies and uv.lock pins them, so
# `uv export` of the lock is a hash-pinned requirements file that uv installs
# into the base image's system Python. `--no-default-groups` leaves out the
# `test` dependency group (pytest), which never reaches the image.
#
# cryptography and paho-mqtt both publish musllinux wheels for amd64 and
# aarch64, so `--only-binary :all:` holds and no compiler toolchain is needed
# in the image.
#
# The base image points uv (UV_EXTRA_INDEX_URL) at Home Assistant's musllinux
# wheel index, which uv would search ahead of PyPI. uv.lock was resolved
# against PyPI and carries PyPI's hashes, so the install drops that index and
# fetches exactly the locked wheels.
COPY pyproject.toml uv.lock /tmp/acpro-addon/
RUN --mount=type=bind,from=uv,source=/uv,target=/usr/local/bin/uv \
    unset UV_EXTRA_INDEX_URL \
    && uv export --project /tmp/acpro-addon --frozen --no-default-groups \
        --no-emit-project --output-file /tmp/acpro-addon/requirements.txt \
    && uv pip install --system --no-cache --require-hashes --only-binary :all: \
        --requirements /tmp/acpro-addon/requirements.txt \
    && rm -rf /tmp/acpro-addon /tmp/uv-*.lock

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
