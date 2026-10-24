#!/usr/bin/env bash
# Publish the committed code to a Hugging Face Space (Docker SDK).
#
#   bash deploy/push_to_hf.sh https://huggingface.co/spaces/<your-username>/<space-name>
#
# Git will ask for your Hugging Face username and, as the password, an access token with WRITE permission
# (huggingface.co/settings/tokens). The token is typed into git's own prompt and is never stored by this script.
# Only COMMITTED files are published (git archive), and the project README is swapped for the Space's
# README (deploy/hf/README.md), which carries the Space configuration. Your GitHub history is untouched.
set -euo pipefail
URL="${1:?usage: bash deploy/push_to_hf.sh https://huggingface.co/spaces/<user>/<space>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

git -C "$ROOT" archive HEAD | tar -x -C "$TMP"
cp "$ROOT/deploy/hf/README.md" "$TMP/README.md"
cd "$TMP"
git init -q -b main
git add -A
git -c user.name="deploy" -c user.email="deploy@users.noreply.huggingface.co" commit -q -m "Deploy MCP Guardian"
git push --force "$URL" main
echo "Pushed. Now open the Space's Settings -> Variables and secrets and add OPENROUTER_API_KEY as a SECRET."
