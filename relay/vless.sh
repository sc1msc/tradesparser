#!/usr/bin/env bash
# Личный VLESS + Reality (Xray) на том же VPS, что и релей бота.
# Два входа: Vision (TCP, порт 2053) - понимает любое приложение;
#            XHTTP (порт 2083) - новее, по статьям 2026 года его хуже ловят.
# Reality "одалживает" сертификат нашего же сайта tg.honestlot.ru (Caddy на 443):
# имя в соединении совпадает с IP сервера, а чужие подключения видят обычный сайт.
#
# Запуск с ПК (спросит пароль root):
#   ssh root@89.124.97.131 "bash -s" < relay\vless.sh        (cmd)
# Повторный запуск безопасен: ключи сохраняются в /usr/local/etc/xray/honestlot.env,
# ссылки не меняются. Новые ключи: удалить этот файл и запустить снова.
set -euo pipefail

PORT_VISION=2053
PORT_XHTTP=2083
CONF_DIR=/usr/local/etc/xray
STATE=$CONF_DIR/honestlot.env

export DEBIAN_FRONTEND=noninteractive
apt-get -o DPkg::Lock::Timeout=300 install -y -q curl unzip openssl >/dev/null

IP=$(curl -4 -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')
# Reality "одалживает" сертификат у Caddy на этом же сервере, поэтому имя - то, на которое
# у Caddy есть сертификат (relay/setup.sh). До 10.10.2026 было IP с дефисами + .sslip.io.
DOMAIN="tg.honestlot.ru"

if ! command -v xray >/dev/null; then
  echo "== Ставлю Xray (официальный установщик XTLS)"
  bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install </dev/null
fi
# sed, а не head: head закрывает трубу раньше времени, xray получает SIGPIPE,
# и из-за pipefail скрипт молча останавливается (так было при первом запуске).
xray version | sed -n 1p

mkdir -p "$CONF_DIR"
if [ -f "$STATE" ]; then
  # shellcheck disable=SC1090
  . "$STATE"
else
  echo "== Создаю ключи"
  UUID=$(xray uuid)
  KEYS=$(xray x25519)
  # Формат вывода менялся: "Private key:/Public key:" или "PrivateKey:/Password:"
  PRIV=$(printf '%s\n' "$KEYS" | awk -F': ' '/Private/ && !f {print $2; f=1}' | tr -d ' \r')
  PUB=$(printf '%s\n' "$KEYS" | awk -F': ' '/Public|Password/ && !f {print $2; f=1}' | tr -d ' \r')
  SID=$(openssl rand -hex 8)
  XPATH=/$(openssl rand -hex 6)
  [ -n "$PRIV" ] && [ -n "$PUB" ] || { echo "Не разобрал вывод xray x25519:"; echo "$KEYS"; exit 1; }
  umask 077
  printf 'UUID=%s\nPRIV=%s\nPUB=%s\nSID=%s\nXPATH=%s\n' "$UUID" "$PRIV" "$PUB" "$SID" "$XPATH" > "$STATE"
  umask 022
fi

REALITY=$(cat <<EOF
{
          "dest": "127.0.0.1:443",
          "serverNames": ["${DOMAIN}"],
          "privateKey": "${PRIV}",
          "shortIds": ["${SID}"]
        }
EOF
)

cat > "$CONF_DIR/config.json" <<EOF
{
  "log": { "loglevel": "warning", "access": "none" },
  "inbounds": [
    {
      "tag": "vision",
      "listen": "0.0.0.0",
      "port": ${PORT_VISION},
      "protocol": "vless",
      "settings": { "clients": [ { "id": "${UUID}", "flow": "xtls-rprx-vision" } ], "decryption": "none" },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": ${REALITY}
      },
      "sniffing": { "enabled": true, "destOverride": ["http", "tls", "quic"] }
    },
    {
      "tag": "xhttp",
      "listen": "0.0.0.0",
      "port": ${PORT_XHTTP},
      "protocol": "vless",
      "settings": { "clients": [ { "id": "${UUID}" } ], "decryption": "none" },
      "streamSettings": {
        "network": "xhttp",
        "xhttpSettings": { "path": "${XPATH}" },
        "security": "reality",
        "realitySettings": ${REALITY}
      },
      "sniffing": { "enabled": true, "destOverride": ["http", "tls", "quic"] }
    }
  ],
  "outbounds": [
    { "protocol": "freedom", "tag": "direct" },
    { "protocol": "blackhole", "tag": "block" }
  ],
  "routing": {
    "rules": [ { "type": "field", "ip": ["geoip:private"], "outboundTag": "block" } ]
  }
}
EOF
chmod 644 "$CONF_DIR/config.json"

echo "== Проверяю конфиг"
xray run -test -config "$CONF_DIR/config.json"

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow ${PORT_VISION}/tcp
  ufw allow ${PORT_XHTTP}/tcp
fi

systemctl enable xray >/dev/null 2>&1
systemctl restart xray
sleep 2
if ! systemctl is-active --quiet xray; then
  echo "Xray не запустился:"; journalctl -u xray --no-pager -n 30; exit 1
fi

ENC_PATH=$(printf '%s' "$XPATH" | sed 's#/#%2F#g')
echo
echo "OK: Xray работает (порты ${PORT_VISION} и ${PORT_XHTTP})"
echo
echo "1) Vision - вставить в приложение (импорт из буфера обмена):"
echo "vless://${UUID}@${IP}:${PORT_VISION}?encryption=none&flow=xtls-rprx-vision&security=reality&sni=${DOMAIN}&fp=chrome&pbk=${PUB}&sid=${SID}&type=tcp#honestlot-vision"
echo
echo "2) XHTTP - запасной, если первый не подключается:"
echo "vless://${UUID}@${IP}:${PORT_XHTTP}?encryption=none&security=reality&sni=${DOMAIN}&fp=chrome&pbk=${PUB}&sid=${SID}&type=xhttp&path=${ENC_PATH}&mode=auto#honestlot-xhttp"
