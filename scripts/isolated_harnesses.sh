#!/usr/bin/env bash
# Create ISOLATED config environments for opencode and pi, so cross-harness
# comparisons measure the harness itself, not the operator's global config.
#
# Why: opencode's prompt was found to include the operator's global AGENTS.md,
# MCP servers (unchainedsky, npcterm) and skills, inflating the tool surface
# from ~10 to 66 and requests from ~35KB to ~97KB. Isolating the config dirs
# removes that contamination.
#
# Usage:
#   ./scripts/isolated_harnesses.sh                 # creates /tmp/opencode-clean + /tmp/pi-clean
#   XDG_CONFIG_HOME=/tmp/opencode-clean/config opencode run --model skycap/<model> "<prompt>"
#   HOME=/tmp/pi-clean pi -p --provider skycap --model <model> "<prompt>"
#
# The isolated configs contain ONLY a "skycap" provider pointing at the
# capture proxy (localhost:8789, see scripts/capture_proxy.py). Capture must
# be running first: uv run python scripts/capture_proxy.py &
set -euo pipefail
cd "$(dirname "$0")/.."

KEY="${OPENROUTER_API_KEY:-$(grep '^OPENROUTER_API_KEY=' .env | cut -d= -f2- | tr -d '"' | tr -d "'")}"
[ -n "$KEY" ] || { echo "need OPENROUTER_API_KEY"; exit 1; }

CLEAN_OC=/tmp/opencode-clean
CLEAN_PI=/tmp/pi-clean
rm -rf "$CLEAN_OC" "$CLEAN_PI"

mkdir -p "$CLEAN_OC/config/opencode"
cat > "$CLEAN_OC/config/opencode/opencode.json" <<EOF
{
  "provider": {
    "skycap": {
      "npm": "@ai-sdk/openai-compatible",
      "options": {"baseURL": "http://localhost:8789/v1", "apiKey": "$KEY"},
      "models": {"nvidia/nemotron-3-super-120b-a12b:free": {"name": "nemotron-super"}}
    }
  },
  "model": "skycap/nvidia/nemotron-3-super-120b-a12b:free"
}
EOF

mkdir -p "$CLEAN_PI/.pi/agent"
cat > "$CLEAN_PI/.pi/agent/models.json" <<EOF
{
  "providers": {
    "skycap": {
      "baseUrl": "http://localhost:8789/v1",
      "api": "openai-completions",
      "apiKey": "$KEY",
      "models": [{"id": "nvidia/nemotron-3-super-120b-a12b:free", "name": "nemotron-super", "contextWindow": 128000, "maxTokens": 8192}]
    }
  }
}
EOF
cat > "$CLEAN_PI/.pi/agent/settings.json" <<EOF
{"defaultProvider": "skycap", "defaultModel": "nvidia/nemotron-3-super-120b-a12b:free"}
EOF

echo "isolated opencode config: $CLEAN_OC/config/opencode/opencode.json"
echo "isolated pi config:       $CLEAN_PI/.pi/agent"
echo
echo "run opencode:  XDG_CONFIG_HOME=$CLEAN_OC/config opencode run --model skycap/nvidia/nemotron-3-super-120b-a12b:free \"<prompt>\""
echo "run pi:        HOME=$CLEAN_PI pi -p --provider skycap --model nvidia/nemotron-3-super-120b-a12b:free \"<prompt>\""