FROM ubuntu:22.04

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates curl binutils libglib2.0-0 libdbus-1-3 libegl1 libgl1 libopengl0 \
    libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
    libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxcb-randr0 \
    libxcb-shape0 libxcb-xfixes0 libxcb-sync1 libxcb-xkb1 libx11-xcb1 \
    libfontconfig1 libfreetype6 libsm6 libice6 libwayland-client0 libwayland-cursor0 \
    libwayland-egl1 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
ENV UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1
RUN curl -LsSf https://astral.sh/uv/0.13.6/install.sh | sh
WORKDIR /work
COPY pyproject.toml uv.lock readme.md LICENSE THIRD_PARTY_NOTICES.md .dockerignore ./
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY packaging/ ./packaging/
COPY docs/ ./docs/
COPY demo/000[0-5].WVF demo/000[0-5].HDR demo/README.md ./demo/
ENV UV_PROJECT_ENVIRONMENT=/work/build/packaging-venv UV_LINK_MODE=copy
RUN uv run --locked --python 3.12 --no-dev --group packaging python scripts/build-linux.py
RUN for executable in /work/build/linux-package/release/*/yokogawa-tool; do \
    QT_QPA_PLATFORM=offscreen XDG_CONFIG_HOME=/tmp/yokogawa-package-check \
    "$executable" --package-self-test; done
CMD ["sh", "-c", "cp /work/dist/yokogawa-tool-*.tar.gz /work/dist/yokogawa-tool-*.tar.gz.sha256 /out/"]
