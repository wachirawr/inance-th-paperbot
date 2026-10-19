#!/usr/bin/env bash
set -euo pipefail
if [[ $(id -u) -ne 0 ]]; then echo 'Run: sudo bash install.sh'; exit 1; fi
DIR=/opt/cryptobot
if [[ ! -f "$DIR/bot.py" ]]; then echo "Copy bot.py to $DIR first"; exit 1; fi
apt-get update -qq
apt-get install -y python3 ca-certificates >/dev/null
if ! id -u paperbot >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$DIR" --shell /usr/sbin/nologin paperbot
fi
if [[ ! -f "$DIR/.env" ]]; then cp "$DIR/sample.env" "$DIR/.env"; fi
chown -R paperbot:paperbot "$DIR"
chmod 600 "$DIR/.env"
cat > /etc/systemd/system/cryptobot.service <<'UNIT'
[Unit]
Description=Binance TH read-only scanner and paper trading
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=paperbot
Group=paperbot
WorkingDirectory=/opt/cryptobot
ExecStart=/usr/bin/python3 -u /opt/cryptobot/bot.py run
Restart=always
RestartSec=20
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=/opt/cryptobot

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable cryptobot.service >/dev/null
echo 'Ready. Edit /opt/cryptobot/.env, then sudo systemctl start cryptobot'
echo 'Run doctor first: cd /opt/cryptobot && python3 bot.py doctor'
