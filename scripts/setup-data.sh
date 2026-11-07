#!/usr/bin/env bash
# 下载 EmulatorJS 运行时（data/ 目录，约 100MB，含各平台 wasm 模拟核心）。
# 首次部署运行一次即可；以后升级改下面的 VER。
set -euo pipefail
cd "$(dirname "$0")/.."

VER=4.2.3

echo "==> 查询 EmulatorJS $VER release ..."
URL=$(curl -fsSL "https://api.github.com/repos/EmulatorJS/EmulatorJS/releases/tags/$VER" \
      | grep -oE 'https://[^"]+/download/[^"]+\.zip' | head -1)
if [ -z "${URL:-}" ]; then
  echo "!! 没有自动找到下载地址，请手动到下面页面下载 zip，把解压出的 data/ 放到项目根目录："
  echo "   https://github.com/EmulatorJS/EmulatorJS/releases/tag/$VER"
  exit 1
fi

echo "==> 下载 $URL"
curl -fL --retry 3 -o /tmp/emulatorjs-$VER.zip "$URL"

echo "==> 解压 ..."
rm -rf /tmp/ejs-extract && mkdir -p /tmp/ejs-extract
unzip -q "/tmp/emulatorjs-$VER.zip" -d /tmp/ejs-extract
SRC=$(find /tmp/ejs-extract -maxdepth 3 -type d -name data | head -1)
if [ -z "${SRC:-}" ]; then
  echo "!! zip 里没找到 data/ 目录，请手动解压确认目录结构"
  exit 1
fi

rm -rf data
cp -r "$SRC" data
echo "==> 完成：data/ 共 $(du -sh data | cut -f1)，现在可以 python3 server.py 了"
