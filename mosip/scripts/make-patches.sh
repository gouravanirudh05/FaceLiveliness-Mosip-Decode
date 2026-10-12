#!/usr/bin/env bash
# Regenerates mosip/patches/<client>-face-liveness.patch from the submodules' working trees (committed or not,
# including new files), then checks that each patch applied to the pinned upstream commit reproduces the working
# tree exactly. The submodules' own index and files are not touched (a throwaway index is used).
#
# Run it after changing either MOSIP client, and commit the patches: the MOSIP repos are upstream, so the
# integration travels as these patches (setup.sh applies them on a fresh clone).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

# Tool-generated files that change when building locally but are not part of the integration.
ANDROID_EXCLUDES=(
  ':!ios/Runner/pigeon.h' ':!ios/Runner/pigeon.m'                       # pigeon output for iOS
  ':!pubspec.lock'                                                       # flutter pub get drift
  ':!test/*.mocks.dart'                                                  # mockito output
  ':!macos/Flutter/GeneratedPluginRegistrant.swift'
  ':!windows/flutter/generated_plugin_registrant.cc' ':!windows/flutter/generated_plugins.cmake'
  ':!linux/flutter/generated_plugin_registrant.*' ':!linux/flutter/generated_plugins.cmake'
  ':!android/livenessmanager/src/main/assets/face_landmarker.task'      # copied in by setup.sh
)

make_patch() {
  local name=$1; shift
  local dir="$REPO/mosip/$name" out="$REPO/mosip/patches/$name-face-liveness.patch"
  local idx check want got
  idx="$(mktemp)"; check="$(mktemp)"
  rm -f "$idx" "$check"
  (
    cd "$dir"
    GIT_INDEX_FILE="$idx" git read-tree HEAD
    GIT_INDEX_FILE="$idx" git add -A -- . "$@"
    GIT_INDEX_FILE="$idx" git diff --cached --binary --full-index HEAD > "$out"
    want="$(GIT_INDEX_FILE="$idx" git write-tree)"
    GIT_INDEX_FILE="$check" git read-tree HEAD
    GIT_INDEX_FILE="$check" git apply --cached "$out"
    got="$(GIT_INDEX_FILE="$check" git write-tree)"
    stat="$(GIT_INDEX_FILE="$idx" git diff --cached --shortstat HEAD)"
    if [ "$want" != "$got" ]; then
      echo "$name: patch does not reproduce the working tree" >&2
      exit 1
    fi
    echo "$name:$stat (against upstream $(git rev-parse --short HEAD); verified)"
  )
  rm -f "$idx" "$check"
}

make_patch registration-client
make_patch android-registration-client "${ANDROID_EXCLUDES[@]}"
echo "patches in $REPO/mosip/patches/"
