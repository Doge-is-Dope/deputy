# One container: virtual display, RDP session to Windows, the runtime and its HTTP API, and a TURN server that
# relays the live view's WebRTC stream to the browser.
FROM python:3.15-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

# FreeRDP comes from backports: trixie's 3.15 doesn't tell Windows the clipboard changed when the new text has
# the same formats as the last, so Windows pastes the old text (fixed in 3.27).
RUN echo "deb http://deb.debian.org/debian trixie-backports main" > /etc/apt/sources.list.d/backports.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends xvfb xdotool xclip coturn \
    && apt-get install -y --no-install-recommends -t trixie-backports freerdp3-x11 \
    && rm -rf /var/lib/apt/lists/*

# xdotool needs a UTF-8 locale to type non-ASCII text ("keys" type mode).
ENV LANG=C.UTF-8
# No download cache: the image installs once, and the cache was a quarter of its size.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
# PyYAML and zstandard have no wheels for Python 3.15 yet: a compiler builds them, and leaves with the same layer.
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && uv sync --locked --no-dev --no-install-project \
    && apt-get purge -y --auto-remove gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY src ./src
RUN uv sync --locked --no-dev
COPY entrypoint.sh /usr/local/bin/desktop-entrypoint
ENV PATH="/app/.venv/bin:$PATH"

CMD ["desktop-entrypoint"]
