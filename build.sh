#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLCHAIN_DIR="${TOOLCHAIN_DIR:-$HERE/../usdaeco-toolchain}"
CORE_DIR="${CORE_DIR:-$HERE/../usdaeco-core}"
AXIS_DIR="${AECO_AXIS_ROOT:-$HERE/../usdaeco-axis}"
exec bash "$TOOLCHAIN_DIR/build.sh" usdAecoSync "$HERE" \
    --dep "${CORE_PLUGIN_DIR:-$CORE_DIR/out/plugins/usdAeco/resources}" \
    --dep "${AXIS_PLUGIN_DIR:-$AXIS_DIR/out/plugins/usdAecoAxis/resources}" "$@"
