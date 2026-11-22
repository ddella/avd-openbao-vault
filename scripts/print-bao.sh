#!/usr/bin/env bash
# Print OpenBao structure.
set -euo pipefail
for mount in net-prod net-staging net-lab; do
  echo "$mount/"
  for path in global dc; do
    echo "  $path/"
    bao kv list -format=json "$mount/$path" 2>/dev/null | jq -r '.[]' |
    while read -r item; do
      echo "    $item"
      if [ "$path" = dc ]; then
        bao kv list -format=json "$mount/dc/$item" 2>/dev/null | jq -r '.[]' |
        while read -r category; do
          echo "      $category"
        done
      fi
    done
  done
done
