#!/usr/bin/env bash
# 注册/卸载每日 ESG 招标监控任务（macOS launchd）。
#
#   bash scripts/setup_cron.sh            注册（默认每天 09:07）
#   bash scripts/setup_cron.sh --time 08:30
#   bash scripts/setup_cron.sh --remove   卸载
#
# 为什么不直接用 crontab：launchd 在 Mac 休眠后会补跑错过的任务，
# 且不需要给 crontab 写权限。

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.esg.tender-monitor.plist"
LABEL="com.esg.tender-monitor"
RUN_TIME="09:07"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --remove)
            launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
            rm -f "$PLIST"
            echo "已卸载 $LABEL"
            exit 0
            ;;
        --time)
            RUN_TIME="$2"
            shift 2
            ;;
        *)
            echo "未知参数: $1" >&2
            exit 1
            ;;
    esac
done

# 优先用仓库 venv，其次系统 python3
if [[ -x "/Users/zhanglei/zl/vscode/ai-homework/.venv/bin/python" ]]; then
    PY="/Users/zhanglei/zl/vscode/ai-homework/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
else
    echo "找不到 python3" >&2
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$SKILL_DIR/output" "$SKILL_DIR/data"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>$SKILL_DIR/scripts/monitor.py</string>
        <string>--days</string>
        <string>2</string>
        <string>--pages</string>
        <string>2</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$SKILL_DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>${RUN_TIME%%:*}</integer>
        <key>Minute</key><integer>${RUN_TIME##*:}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$SKILL_DIR/data/monitor.log</string>
    <key>StandardErrorPath</key>
    <string>$SKILL_DIR/data/monitor.err.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST_EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "已注册 $LABEL"
echo "  运行时间：每天 $RUN_TIME"
echo "  执行：$PY $SKILL_DIR/scripts/monitor.py"
echo "  日志：$SKILL_DIR/data/monitor.log"
echo "  日报：$SKILL_DIR/output/daily-<日期>.md"
echo
echo "推送提示：脚本本身只生成日报文件。配置 webhook 或让 Claude 读取日报后推送："
echo "  python scripts/monitor.py --webhook https://your-webhook-url"
