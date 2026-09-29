#!/bin/sh
# 会話開始時に自動で読み込まれる内容。
#   1. 進め方と説明のルール      docs/agents/flow-map.md
#   2. 引き継ぎメモの直近 SHOW 件 docs/agents/handover.md
# 読み込む件数と保存上限の正はこのファイル。文書側に数字を重複させない。
set -u

KEEP=5   # handover.md に残す上限
SHOW=2   # 会話開始時に読み込む件数

dir="${CLAUDE_PROJECT_DIR:-.}"

[ -f "$dir/docs/agents/flow-map.md" ] && cat "$dir/docs/agents/flow-map.md"

f="$dir/docs/agents/handover.md"
[ -f "$f" ] || exit 0

# ``` で囲まれた中の "## " は見出しとして数えない
total=$(awk '/^```/{fence=!fence; next} !fence && /^## /{n++} END{print n+0}' "$f")

echo
echo "--- 引き継ぎメモ 直近 $SHOW 件 / 全 $total 件（全文は docs/agents/handover.md）---"
awk -v show="$SHOW" '
  /^```/            { fence = !fence }
  !fence && /^## /  { n++; started = 1 }
  n > show          { exit }
  started           { print }
' "$f"

if [ "$total" -gt "$KEEP" ]; then
  echo
  echo "⚠ 引き継ぎメモが $total 件あります（上限 $KEEP 件）。古い分を削ってください: sh .claude/hooks/handover-trim.sh"
fi
