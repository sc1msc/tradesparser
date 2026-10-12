#!/usr/bin/env bash
# Личный VPN Hysteria2 (QUIC поверх UDP) на том же VPS, что и релей бота.
# Весь трафик устройства идёт по одному QUIC-соединению на UDP 443 с именем
# tg.honestlot.ru и настоящим сертификатом Let's Encrypt (берём у Caddy):
# снаружи выглядит как HTTP/3 к обычному сайту. MTProto и VLESS по TCP 11.10.2026
# с домашнего IP перестали проходить (первый пакет TLS выбрасывается по дороге).
#
# Запуск с ПК (спросит пароль root):
#   ssh root@89.124.97.131 "bash -s" < relay\hysteria.sh        (cmd)
# Повторный запуск безопасен: пароль хранится в /etc/hysteria/honestlot.env,
# ссылка не меняется. Новый пароль: удалить этот файл и запустить снова.
set -euo pipefail

DOMAIN="tg.honestlot.ru"     # то же имя, что у релея в relay/setup.sh
HY_DIR=/etc/hysteria
STATE=$HY_DIR/honestlot.env

export DEBIAN_FRONTEND=noninteractive
apt-get -o DPkg::Lock::Timeout=300 install -y -q curl openssl iproute2 >/dev/null
IP=$(curl -4 -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')

# --- 1. UDP 443: Caddy по умолчанию держит его под HTTP/3. Релею бота HTTP/3 не
# нужен - выключаем (то же самое прописано в relay/setup.sh, чтобы не вернулось).
# (вывод ss - в переменную: grep -q в трубе при pipefail может дать ложное "нет")
if grep -q ':443 .*caddy' <<<"$(ss -lunp)"; then
  echo "== Выключаю HTTP/3 в Caddy, чтобы освободить UDP 443"
  cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak
  if ! grep -q 'protocols h1 h2' /etc/caddy/Caddyfile; then
    { printf '{\n\t# UDP 443 отдан Hysteria2 (relay/hysteria.sh) - HTTP/3 в Caddy выключен.\n\tservers {\n\t\tprotocols h1 h2\n\t}\n}\n\n'; cat /etc/caddy/Caddyfile.bak; } > /etc/caddy/Caddyfile
  fi
  if caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
    systemctl restart caddy
    sleep 2
  else
    echo "Caddy не принял настройку - возвращаю как было"
    cp /etc/caddy/Caddyfile.bak /etc/caddy/Caddyfile
  fi
fi
HY_PORT=443
if grep -q ':443 ' <<<"$(ss -lun)"; then
  HY_PORT=8443
  echo "UDP 443 всё ещё занят - Hysteria2 будет на UDP 8443"
fi
# Релей бота должен работать как прежде (чужим - 403).
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://${DOMAIN}/" || true)
echo "== Релей бота: https://${DOMAIN}/ -> HTTP $code (ожидается 403)"

# --- 2. Hysteria2 (официальный установщик)
if ! command -v hysteria >/dev/null; then
  echo "== Ставлю Hysteria2"
  # </dev/null: сам этот скрипт приходит через stdin (ssh ... "bash -s" <), установщик не должен его съесть
  bash <(curl -fsSL https://get.hy2.sh/) </dev/null
fi
hysteria version 2>/dev/null | sed -n '1,3p' || true
OWNER=root
id hysteria >/dev/null 2>&1 && OWNER=hysteria

# --- 3. Сертификат: копия того, что выпустил Caddy, + ежедневная сверка (Caddy продлевает сам)
mkdir -p "$HY_DIR"
cat > /usr/local/sbin/hysteria-cert-sync <<EOF
#!/bin/sh
# Копирует сертификат ${DOMAIN} из хранилища Caddy для Hysteria2; при смене - перезапуск.
SRC=\$(find /var/lib/caddy -type f -name '${DOMAIN}.crt' -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)
[ -n "\$SRC" ] || { echo "нет сертификата ${DOMAIN} в /var/lib/caddy"; exit 1; }
if ! cmp -s "\$SRC" ${HY_DIR}/tls.crt; then
  install -o ${OWNER} -g ${OWNER} -m 644 "\$SRC" ${HY_DIR}/tls.crt
  install -o ${OWNER} -g ${OWNER} -m 600 "\${SRC%.crt}.key" ${HY_DIR}/tls.key
  systemctl is-active --quiet hysteria-server && systemctl restart hysteria-server || true
fi
EOF
chmod 755 /usr/local/sbin/hysteria-cert-sync
/usr/local/sbin/hysteria-cert-sync

cat > /etc/systemd/system/hysteria-cert-sync.service <<EOF
[Unit]
Description=Copy Caddy certificate for Hysteria2
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/hysteria-cert-sync
EOF
cat > /etc/systemd/system/hysteria-cert-sync.timer <<EOF
[Unit]
Description=Daily copy of Caddy certificate for Hysteria2
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
EOF

# --- 4. Пароль и конфиг
if [ -f "$STATE" ]; then
  # shellcheck disable=SC1090
  . "$STATE"
else
  PASS=$(openssl rand -hex 16)
  umask 077; printf 'PASS=%s\n' "$PASS" > "$STATE"; umask 022
fi
cat > "$HY_DIR/config.yaml" <<EOF
# Hysteria2 (relay/hysteria.sh). Чужим вместо VPN отвечает как обычный сайт ${DOMAIN}.
listen: :${HY_PORT}
tls:
  cert: ${HY_DIR}/tls.crt
  key: ${HY_DIR}/tls.key
auth:
  type: password
  password: "${PASS}"
masquerade:
  type: proxy
  proxy:
    url: https://${DOMAIN}/
    rewriteHost: true
EOF
chown "$OWNER":"$OWNER" "$HY_DIR/config.yaml"; chmod 600 "$HY_DIR/config.yaml"

# Без журнала подключений (в info Hysteria пишет IP клиентов)
mkdir -p /etc/systemd/system/hysteria-server.service.d
printf '[Service]\nEnvironment=HYSTERIA_LOG_LEVEL=warn\n' > /etc/systemd/system/hysteria-server.service.d/honestlot.conf

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow ${HY_PORT}/udp
fi

systemctl daemon-reload
systemctl enable --now hysteria-cert-sync.timer >/dev/null 2>&1
systemctl enable hysteria-server >/dev/null 2>&1
systemctl restart hysteria-server
sleep 2
if ! systemctl is-active --quiet hysteria-server; then
  echo "Hysteria2 не запустилась:"; journalctl -u hysteria-server --no-pager -n 30; exit 1
fi
grep -q ":${HY_PORT} " <<<"$(ss -lun)" || { echo "Hysteria2 запущена, но UDP ${HY_PORT} не слушается"; journalctl -u hysteria-server --no-pager -n 30; exit 1; }

echo
echo "OK: Hysteria2 работает на UDP ${HY_PORT}"
echo
echo "Ссылка для приложения (Hiddify: + -> Добавить из буфера обмена):"
echo "hysteria2://${PASS}@${IP}:${HY_PORT}/?sni=${DOMAIN}#honestlot-hy2"
