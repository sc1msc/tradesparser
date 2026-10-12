#!/usr/bin/env bash
# Личный MTProto-прокси для Telegram (телефон, ноутбук) на том же VPS, что и релей.
# Программа mtg (github.com/9seconds/mtg), режим Fake TLS: снаружи соединение
# выглядит как HTTPS к нашему же сайту 89-124-97-131.sslip.io (его отдаёт Caddy).
#
# Запуск с ПК (спросит пароль root):
#   ssh root@89.124.97.131 "bash -s" < relay\mtproxy.sh        (cmd)
# Повторный запуск безопасен: секрет сохраняется, ссылка не меняется.
# Новый секрет (старая ссылка перестанет работать): удалить /etc/mtg.toml и запустить снова.
set -euo pipefail

PORT=8443   # 443 занят Caddy (релей бота)

export DEBIAN_FRONTEND=noninteractive
IP=$(curl -4 -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')
DOMAIN="${IP//./-}.sslip.io"

case "$(uname -m)" in
  x86_64) ARCH=amd64 ;;
  aarch64) ARCH=arm64 ;;
  *) echo "Неизвестная архитектура $(uname -m)"; exit 1 ;;
esac

if ! command -v mtg >/dev/null; then
  echo "== Скачиваю mtg"
  URL=$(curl -fsSL https://api.github.com/repos/9seconds/mtg/releases/latest \
        | grep -o '"browser_download_url": *"[^"]*linux-'"$ARCH"'\.tar\.gz"' \
        | head -1 | sed 's/.*"\(https[^"]*\)"/\1/')
  [ -n "$URL" ] || { echo "Не нашёл сборку mtg на GitHub"; exit 1; }
  TMP=$(mktemp -d)
  curl -fsSL "$URL" | tar -xz -C "$TMP"
  install -m 755 "$(find "$TMP" -type f -name mtg | head -1)" /usr/local/bin/mtg
  rm -rf "$TMP"
fi
mtg --version || true

if [ ! -f /etc/mtg.toml ]; then
  echo "== Создаю секрет"
  SECRET=$(mtg generate-secret --hex "$DOMAIN")
  cat > /etc/mtg.toml <<EOF
# Личный MTProto-прокси (relay/mtproxy.sh). Fake TLS под ${DOMAIN}:
# чужие подключения mtg пересылает на ${DOMAIN}:443 (Caddy), и порт выглядит как обычный сайт.
secret = "${SECRET}"
bind-to = "0.0.0.0:${PORT}"
prefer-ip = "prefer-ipv4"
EOF
  chmod 644 /etc/mtg.toml
fi

cat > /etc/systemd/system/mtg.service <<EOF
[Unit]
Description=mtg - MTProto proxy for Telegram
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/mtg run /etc/mtg.toml
Restart=always
RestartSec=3
DynamicUser=true

[Install]
WantedBy=multi-user.target
EOF

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow ${PORT}/tcp
fi

systemctl daemon-reload
systemctl enable mtg >/dev/null 2>&1
systemctl restart mtg
sleep 2
if ! systemctl is-active --quiet mtg; then
  echo "mtg не запустился:"; journalctl -u mtg --no-pager -n 30; exit 1
fi

SECRET=$(grep '^secret' /etc/mtg.toml | cut -d'"' -f2)
echo
echo "OK: прокси работает на ${IP}:${PORT}"
echo
echo "Ссылка для телефона и ноутбука (откроет Telegram и предложит подключить прокси):"
echo "tg://proxy?server=${IP}&port=${PORT}&secret=${SECRET}"
echo "Если tg:// не открывается - то же через сайт: https://t.me/proxy?server=${IP}&port=${PORT}&secret=${SECRET}"
echo
echo "Вручную (Настройки - Данные и память - Прокси - MTProto):"
echo "  сервер ${IP}, порт ${PORT}, ключ ${SECRET}"
