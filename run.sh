#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if ! command -v uv >/dev/null 2>&1; then
    echo 'uvが必要です。readme.mdの起動手順を確認してください。' >&2
    exit 1
fi
exec uv run --locked --python 3.12 yokogawa-tool "$@"
