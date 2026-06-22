#!/usr/bin/env bash
set -euo pipefail

model="${1:-small}"
if [[ "$model" != "small" && "$model" != "medium" ]]; then
  echo "Usage: scripts/setup_whisper_mac.sh [small|medium]" >&2
  exit 2
fi

if ! command -v brew >/dev/null 2>&1; then
  python3 -m pip install mlx-whisper
  echo "Ready: MLX Whisper will download the $model Metal model on first use."
  exit 0
fi
if ! command -v ffmpeg >/dev/null 2>&1; then brew install ffmpeg; fi
if ! command -v whisper-cli >/dev/null 2>&1; then brew install whisper-cpp; fi

model_dir="$HOME/Library/Application Support/Creator Signal/models"
model_path="$model_dir/ggml-$model.bin"
mkdir -p "$model_dir"
if [[ ! -f "$model_path" ]]; then
  curl --fail --location --progress-bar \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$model.bin" \
    --output "$model_path.part"
  mv "$model_path.part" "$model_path"
fi
echo "Ready: $model_path"
