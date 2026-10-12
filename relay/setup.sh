#!/usr/bin/env bash
# Релей Telegram Bot API на зарубежном VPS (Ubuntu 24.04 / Debian 12).
#
# Зачем: с ВМ мини-аппа в Yandex Cloud api.telegram.org недоступен (блокировка
# у провайдера в обе стороны). ВМ ходит в Telegram через этот сервер: Caddy
# принимает HTTPS-запросы только с IP ВМ и пересылает их в api.telegram.org.
# Данные пользователей здесь не хранятся, журнал запросов выключен.
#
# Запуск с ПК из Git Bash в корне репозитория (спросит пароль root от VPS):
#   ssh root@<IP релея> 'bash -s' < relay/setup.sh
# Повторный запуск безопасен: перезапишет Caddyfile и перезапустит Caddy.
set -euo pipefail

# Кого пускать: публичный IP ВМ мини-аппа (через пробел, если несколько).
ALLOWED_IPS="84.201.144.182"

export DEBIAN_FRONTEND=noninteractive
# Свежий сервер в первые минуты сам ставит обновления и держит блокировку apt - ждём до 5 минут.

# Репозиторий Caddy на Cloudsmith 10.10.2026 отвечал "402 Payment Required" -
# ставим Caddy из репозитория самой Ubuntu и убираем следы прошлой попытки.
rm -f /etc/apt/sources.list.d/caddy-stable.list /usr/share/keyrings/caddy-stable-archive-keyring.gpg

echo "== Пакеты"
apt-get -o DPkg::Lock::Timeout=300 update -q
apt-get -o DPkg::Lock::Timeout=300 install -y -q curl ca-certificates

# Имя релея для сертификата Let's Encrypt. A-запись `tg` в DNS honestlot.ru
# (панель SpaceWeb) должна указывать на IP этого сервера: новый VPS - сначала
# поменять запись, потом запускать скрипт. До 10.10.2026 тут было IP с дефисами
# + .sslip.io - ушли с чужого бесплатного сервиса на свой домен.
DOMAIN="tg.honestlot.ru"
IP=$(curl -4 -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')
echo "== IP релея: $IP, имя: $DOMAIN"
# Без верной A-записи Let's Encrypt откажет, а после 5 отказов за час на это имя
# перестанет выдавать сертификат на час - проверяем заранее. Смотрим и местный DNS,
# и публичный DNS Google: 10.10.2026 местный уже видел новую запись, а Google и
# Let's Encrypt - ещё нет (у SpaceWeb несколько DNS-серверов, зона доходит не сразу).
RESOLVED=$(getent ahostsv4 "$DOMAIN" | awk '{print $1; exit}' || true)
PUBLIC=$(curl -fsS --max-time 10 "https://dns.google/resolve?name=${DOMAIN}&type=A" | grep -o '"data":"[0-9.]*"' | head -1 | cut -d'"' -f4 || true)
if [ "$RESOLVED" != "$IP" ] || [ "$PUBLIC" != "$IP" ]; then
  echo "СТОП: $DOMAIN -> местный DNS '${RESOLVED:-ничего}', DNS Google '${PUBLIC:-ничего}', а IP этого сервера - $IP."
  echo "Поправьте A-запись в DNS (SpaceWeb) или подождите, пока она разойдётся, и запустите скрипт снова."
  exit 1
fi

if ! command -v caddy >/dev/null; then
  echo "== Ставлю Caddy (репозиторий Ubuntu)"
  apt-get -o DPkg::Lock::Timeout=300 update -q
  # Caddy лежит в разделе universe - включить, если на сервере он выключен.
  if ! apt-cache show caddy >/dev/null 2>&1; then
    apt-get -o DPkg::Lock::Timeout=300 install -y -q software-properties-common
    add-apt-repository -y universe
    apt-get -o DPkg::Lock::Timeout=300 update -q
  fi
  apt-get -o DPkg::Lock::Timeout=300 install -y -q caddy
fi
caddy version

echo "== Caddyfile"
cat > /etc/caddy/Caddyfile <<EOF
# Релей Telegram Bot API для honestlot. Создан relay/setup.sh из репозитория -
# правки делать там и перезапускать скрипт.
# Пускает только ВМ мини-аппа, остальным 403. Журнал запросов не ведём:
# через релей идут апдейты с данными пользователей, хранить их здесь нельзя.
{
	# UDP 443 отдан Hysteria2 (relay/hysteria.sh) - HTTP/3 в Caddy выключен.
	servers {
		protocols h1 h2
	}
}

${DOMAIN} {
	@denied not remote_ip ${ALLOWED_IPS}
	respond @denied 403

	reverse_proxy https://api.telegram.org {
		header_up Host {upstream_hostport}
	}
}
EOF
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

# Если на сервере включён ufw - открыть 80 (выпуск сертификата) и 443.
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp
  ufw allow 443/tcp
fi

systemctl enable caddy >/dev/null 2>&1
systemctl restart caddy

echo "== Жду сертификат (до 2 минут)"
code=000
for _ in $(seq 1 24); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "https://${DOMAIN}/" || true)
  [ "$code" = "403" ] && break
  sleep 5
done
if [ "$code" = "403" ]; then
  echo "OK: Caddy работает, сертификат получен, чужие запросы получают 403."
else
  echo "Не дождался сертификата (код $code). Журнал: journalctl -u caddy --no-pager -n 50"
  exit 1
fi
echo "Проверка связи с Telegram отсюда:"
curl -s --max-time 10 -o /dev/null -w "api.telegram.org -> HTTP %{http_code}\n" https://api.telegram.org/ || echo "api.telegram.org недоступен"
echo
echo "RELAY_URL=https://${DOMAIN}"
