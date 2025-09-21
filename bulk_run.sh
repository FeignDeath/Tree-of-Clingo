#!/usr/bin/env bash
set -euo pipefail

INPUT_DIR="data/instances"
OUTPUT_DIR="output"
SCRIPT="python tree2.py"
MODEL_FLAG="--model mistral-small --check"

mkdir -p "$OUTPUT_DIR"

shopt -s nullglob
for file in "$INPUT_DIR"/*; do
  filename=$(basename "$file")
  echo "Processing: $filename"
  # Redirect both stdout and stderr to the output file
  $SCRIPT "$file" $MODEL_FLAG > "$OUTPUT_DIR/$filename" 2>&1
done
shopt -u nullglob
