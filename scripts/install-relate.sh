#!/usr/bin/env bash
# Install the pinned Relate wheel into a Python environment.
#
#   scripts/install-relate.sh            into the checkout's .venv (what `uv sync` made)
#   scripts/install-relate.sh PYTHON     into the environment at PYTHON (a venv directory or an interpreter)
#
# Relate (still released under its old name, CypherLite) is not on PyPI, and its GitHub release
# is internal, so `uv` cannot fetch it as a dependency and this script does: it asks the GitHub
# API for the wheel of this platform with `gh` (logged in, or GH_TOKEN set), checks its sha256
# against the list below, keeps it under ~/.cache/aip/relate/, and installs it with `uv pip`.
# When `relate-db` lands on PyPI this script goes and `pyproject.toml` pins it.
# The pin, the import and the install hint live in `src/aip/compiler/relate.py`.
set -euo pipefail

VERSION=0.16.1
REPO=neo4j-labs/cypherlite
TAG="v$VERSION"

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64)             plat=macosx_11_0_arm64;                             sha=a00ee6e6faa9f67534c5b6aa9b2496ccf6d23dfbc769e1a8a676062cefbee48e ;;
  Darwin-x86_64)            plat=macosx_10_12_x86_64;                           sha=8dc0fd8b73378159285dfff8619d3e8ff3bc3e57ab5b5d68915bb89d95424d4c ;;
  Linux-x86_64)             plat=manylinux2014_x86_64.manylinux_2_17_x86_64;    sha=fd1b30f525f00ff0b60d1267c6c2de0e15cd9405e5a19c2e73065d880b25055f ;;
  Linux-aarch64|Linux-arm64) plat=manylinux2014_aarch64.manylinux_2_17_aarch64; sha=b983e34fd00926dc2ad4e9a9afac1f52a3e1c3b797ff651f1e107ace79d87334 ;;
  MINGW*|MSYS*|CYGWIN*)     plat=win_amd64;                                     sha=37d0583b6035f235253e2cd6d7e29ca15a8d777e074329c3d516eb5a99415d1a ;;
  *) echo "install-relate: no Relate $VERSION wheel for $(uname -s) $(uname -m)" >&2; exit 1 ;;
esac
wheel="neo4j_cypherlite-$VERSION-cp39-abi3-$plat.whl"
cache="${AIP_RELATE_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/aip/relate}"
mkdir -p "$cache"

checksum() {  # sha256 of $1, on macOS and Linux
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

if [ ! -s "$cache/$wheel" ] || [ "$(checksum "$cache/$wheel")" != "$sha" ]; then
  echo "install-relate: fetching $wheel from $REPO $TAG" >&2
  asset=$(gh api "repos/$REPO/releases/tags/$TAG" --jq ".assets[] | select(.name == \"$wheel\") | .id")
  [ -n "$asset" ] || { echo "install-relate: release $TAG has no asset $wheel" >&2; exit 1; }
  gh api -H "Accept: application/octet-stream" "repos/$REPO/releases/assets/$asset" > "$cache/$wheel.part"
  got=$(checksum "$cache/$wheel.part")
  if [ "$got" != "$sha" ]; then
    rm -f "$cache/$wheel.part"
    echo "install-relate: $wheel has sha256 $got, expected $sha; not installing" >&2
    exit 1
  fi
  mv "$cache/$wheel.part" "$cache/$wheel"
fi

if [ $# -ge 1 ]; then
  uv pip install --quiet --python "$1" "$cache/$wheel"
else
  uv pip install --quiet "$cache/$wheel"
fi
echo "install-relate: Relate $VERSION (cypherlite) installed from $cache/$wheel"
