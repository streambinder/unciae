# Limen: the Muse Gadget (Linux Device SDK) service from
# facebookincubator/muse-gadget-sdk, packaged as a container image.
# Built and published to GHCR by the unciae push workflow; hosts
# consume the published image and never build it locally.
# The service must run as root inside the container: it owns the command
# socket and drops to the unprivileged gadget account per command via
# --run-as, like the upstream installer (trivy DS-0002, waived in
# /.trivyignore).
# checkov:skip=CKV_DOCKER_3: Must run as root; privileges are dropped to the gadget account per command via --run-as.
FROM docker.io/library/debian:bookworm-slim

# Pinned upstream commit of facebookincubator/muse-gadget-sdk.
ARG MUSEGADGET_COMMIT=b139b45064b4dcecf7bfe97e75bc7f99c10c28b6

# python3-dbus / python3-gi / python3-cryptography come from the distro,
# exactly like the upstream installer does on Debian/Raspberry Pi OS.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-dbus python3-gi python3-cryptography \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://github.com/facebookincubator/muse-gadget-sdk/archive/${MUSEGADGET_COMMIT}.tar.gz" -o /tmp/sdk.tgz \
    && mkdir -p /opt/src \
    && tar -xzf /tmp/sdk.tgz -C /opt/src --strip-components=1 \
    && python3 -m venv --system-site-packages /opt/musegadget/venv \
    && /opt/musegadget/venv/bin/pip install --no-cache-dir /opt/src/linux \
    && rm /tmp/sdk.tgz

# Patch: the stock 60s chat timeout (REQUEST_TIMEOUT_S) is far too short
# for real Muse turns; raise it to 30 minutes inside our own image.
RUN sed -i 's/^REQUEST_TIMEOUT_S = 60$/REQUEST_TIMEOUT_S = 1800/' \
        /opt/musegadget/venv/lib/python3.11/site-packages/musegadget/link_client.py \
    && grep -n '^REQUEST_TIMEOUT_S' \
        /opt/musegadget/venv/lib/python3.11/site-packages/musegadget/link_client.py

# Commands Muse runs on this device execute as this unprivileged account.
RUN useradd --create-home --uid 10001 gadget \
    && mkdir -p /run/musegadget /workspace \
    && ln -s /opt/musegadget/venv/bin/musegadget /usr/local/bin/musegadget

# Patch: allow reporting a fixed SSID via MUSEGADGET_REPORT_SSID
# (wired-only hosts have no real SSID; upstream issue 79).
COPY patch_network.py /tmp/patch_network.py
RUN python3 /tmp/patch_network.py && rm /tmp/patch_network.py

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV MUSEGADGET_RUN_AS=gadget \
    PYTHONUNBUFFERED=1

HEALTHCHECK --interval=60s --timeout=10s \
    CMD test -S /run/musegadget/musegadget.sock

VOLUME ["/var/lib/musegadget"]
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["run"]
