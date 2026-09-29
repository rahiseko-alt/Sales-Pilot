#!/bin/sh
# 引き継ぎメモを新しい順に KEEP 件だけ残す。追記したら必ず実行する。
# 溢れた分は削除せず、docs/agents/handover-archive.md（読み込み対象外）へ移す。
set -u

KEEP=5

dir="${CLAUDE_PROJECT_DIR:-.}"
f="$dir/docs/agents/handover.md"
archive="$dir/docs/agents/handover-archive.md"
[ -f "$f" ] || exit 0

keep_tmp="$f.keep.tmp"
overflow_tmp="$f.overflow.tmp"

awk -v keep="$KEEP" -v kf="$keep_tmp" -v of="$overflow_tmp" '
  /^```/            { fence = !fence }
  !fence && /^## /  { n++ }
                    { print > (n <= keep ? kf : of) }
' "$f"

archived=0
if [ -s "$overflow_tmp" ]; then
  archived=$(awk '/^```/{fence=!fence; next} !fence && /^## /{n++} END{print n+0}' "$overflow_tmp")

  if [ -f "$archive" ]; then
    archive_tmp="$archive.tmp"
    awk -v ins="$overflow_tmp" '
      { print }
      /^---$/ && !done { while ((getline line < ins) > 0) print line; done = 1 }
    ' "$archive" > "$archive_tmp" && mv "$archive_tmp" "$archive"
  else
    {
      echo "# 引き継ぎメモ・保管庫"
      echo
      echo "handover.md の保存上限（$KEEP 件）を超えて押し出された古いメモを、消さずにここへ移す。"
      echo "会話開始時には読み込まれない。過去の経緯を掘り返すときだけ開く。新しいものを一番上に来るよう足す。"
      echo
      echo "---"
      echo
      cat "$overflow_tmp"
    } > "$archive"
  fi
fi

mv "$keep_tmp" "$f"
rm -f "$overflow_tmp"

if [ "$archived" -gt 0 ]; then
  echo "引き継ぎメモを最新 $KEEP 件に整理しました。（$archived 件を docs/agents/handover-archive.md へ移動）"
else
  echo "引き継ぎメモを最新 $KEEP 件に整理しました。"
fi
