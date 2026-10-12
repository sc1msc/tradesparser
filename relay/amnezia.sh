#!/usr/bin/env bash
# Личный VPN AmneziaWG на том же VPS, что и релей бота.
# AmneziaWG - это WireGuard с маскировкой: перед рукопожатием летят мусорные пакеты
# и пакет, похожий на ответ DNS (I1), а заголовки и размеры пакетов не такие, как у
# WireGuard, поэтому DPI не узнаёт протокол (обычный WireGuard из РФ режется, см.
# relay/README.md). Это UDP, а не TCP+TLS: MTProto и VLESS по TCP 11.10.2026 с
# домашнего IP перестали проходить.
#
# Работает amneziawg-go (программа, без модуля ядра). Модуль ядра из PPA на Ubuntu 26.04
# с ядром 7.0.0-38 и новее не собирается (с 01.10.2026, исправление
# amnezia-vpn/amneziawg-linux-kernel-module#218 не принято), а упавшая сборка DKMS
# оставляет apt недонастроенным после каждого обновления ядра - на сервере с релеем
# так нельзя. Для нескольких личных устройств скорости amneziawg-go хватает с запасом.
# Из PPA берём только утилиты awg и awg-quick, без модуля (--no-install-recommends).
#
# Запуск с ПК (спросит пароль root):
#   ssh root@89.124.97.131 "bash -s" < relay\amnezia.sh                                 (cmd)
#   ssh root@89.124.97.131 "CLIENTS='phone laptop tablet' bash -s" < relay\amnezia.sh   (другие устройства)
# Повторный запуск безопасен: ключи и параметры маскировки хранятся в /etc/amnezia/amneziawg,
# конфиги устройств не меняются. Устройства из CLIENTS добавляются к уже созданным.
# Убрать устройство: rm /etc/amnezia/amneziawg/clients/<имя>.* и запустить снова.
# Новые параметры маскировки (все старые конфиги перестанут работать): удалить
# /etc/amnezia/amneziawg/honestlot.env и запустить снова.
set -euo pipefail

PORT=${AWG_PORT:-41443}           # UDP; 443/udp занят Hysteria2 (relay/hysteria.sh)
CLIENTS=${CLIENTS:-"phone laptop"} # по конфигу на устройство: один ключ на двух устройствах сразу не работает
AWG_GO_TAG=v3.1.20260828          # версия github.com/amnezia-vpn/amneziawg-go
NET=10.66.66                      # адреса в туннеле: сервер .1, устройства .2, .3, ...
# IPv6 в туннеле - только чтобы IPv6 устройства не шёл мимо VPN. Наружу сервер его не
# пускает, а с адресом fd.. (ULA) системы сами выбирают IPv4.
NET6=fd66:66:66
MTU=1280                          # на мобильном интернете 1420 часто не проходит
IF=awg0
DIR=/etc/amnezia/amneziawg
STATE=$DIR/honestlot.env

export DEBIAN_FRONTEND=noninteractive
APT="apt-get -o DPkg::Lock::Timeout=300"
$APT update -q >/dev/null
$APT install -y -q curl openssl iproute2 iptables qrencode >/dev/null
IP=$(curl -4 -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')

# --- 1. Утилиты awg, awg-quick из PPA Amnezia (модуль ядра amneziawg-dkms не ставим)
if ! command -v awg >/dev/null || ! command -v awg-quick >/dev/null; then
  echo "== Ставлю awg и awg-quick (PPA amnezia, без модуля ядра)"
  if ! compgen -G '/etc/apt/sources.list.d/*amnezia*' >/dev/null; then
    $APT install -y -q software-properties-common python3-launchpadlib gnupg >/dev/null
    add-apt-repository -y ppa:amnezia/ppa
  fi
  $APT update -q
  $APT install -y -q --no-install-recommends amneziawg-tools
fi
awg --version || true

# --- 2. amneziawg-go: сборок на GitHub нет, собираем из исходников (Go из репозитория Ubuntu)
mkdir -p "$DIR/clients"
chmod 700 "$DIR"
if ! command -v amneziawg-go >/dev/null || [ "$(cat "$DIR/amneziawg-go.version" 2>/dev/null)" != "$AWG_GO_TAG" ]; then
  echo "== Собираю amneziawg-go $AWG_GO_TAG (1-3 минуты)"
  $APT install -y -q --no-install-recommends golang-go ca-certificates >/dev/null
  BUILD=$(mktemp -d)
  SWAP=""
  cleanup_build() {
    rm -rf "$BUILD"
    if [ -n "$SWAP" ]; then swapoff "$SWAP" 2>/dev/null || true; rm -f "$SWAP"; fi
  }
  trap cleanup_build EXIT
  # На маленьком VPS сборке Go может не хватить памяти - временная подкачка на время сборки
  if [ "$(awk '/MemAvailable/ {print $2}' /proc/meminfo)" -lt 800000 ] && [ -z "$(swapon --show --noheadings)" ]; then
    SWAP=/swap-amneziawg-build
    fallocate -l 1G "$SWAP" && chmod 600 "$SWAP" && mkswap -q "$SWAP" >/dev/null && swapon "$SWAP"
  fi
  curl -fsSL "https://github.com/amnezia-vpn/amneziawg-go/archive/refs/tags/${AWG_GO_TAG}.tar.gz" \
    | tar -xz -C "$BUILD" --strip-components=1
  (cd "$BUILD" && CGO_ENABLED=0 GOTOOLCHAIN=local GOPATH="$BUILD/gopath" GOCACHE="$BUILD/cache" \
     go build -trimpath -ldflags='-s -w' -o amneziawg-go .)
  # Через переименование: поверх запущенной программы файл напрямую не записать
  install -m 755 "$BUILD/amneziawg-go" /usr/local/bin/amneziawg-go.new
  mv -f /usr/local/bin/amneziawg-go.new /usr/local/bin/amneziawg-go
  echo "$AWG_GO_TAG" > "$DIR/amneziawg-go.version"
  cleanup_build
  trap - EXIT
fi

# --- 3. Ключ сервера и параметры маскировки: создаются один раз, у сервера и устройств общие
rnd() { shuf -i "$1-$2" -n 1; }

# H1-H4 - номера типов пакетов (у WireGuard 1-4), в AmneziaWG 2.0 - непересекающиеся
# диапазоны: отправитель каждый раз берёт случайное число из диапазона.
# 8 случайных чисел по возрастанию = 4 пары; ширина каждой не меньше 1000. Верхняя
# граница 2^31-1: клиент AmneziaWG для Windows числа больше считает ошибкой.
gen_h() {
  local a i
  for i in $(seq 1 50); do
    mapfile -t a < <(shuf -i 5-2147483647 -n 8 | sort -n)
    if (( a[1] - a[0] >= 1000 && a[3] - a[2] >= 1000 && a[5] - a[4] >= 1000 && a[7] - a[6] >= 1000 )); then
      H1="${a[0]}-${a[1]}"; H2="${a[2]}-${a[3]}"; H3="${a[4]}-${a[5]}"; H4="${a[6]}-${a[7]}"
      return 0
    fi
  done
  echo "Не получилось подобрать H1-H4"; exit 1
}

# I1 - пакет, который устройство шлёт перед рукопожатием. Похож на ответ DNS на запрос
# A-записи <случайное имя>.cdns.icloud.com: <r 2> - случайный номер запроса, дальше
# заголовок (флаги 8580, как у пакета из приложения Amnezia), вопрос и 1-2 ответа.
# Не случайные байты: по замерам сентября 2026 (МТС) пакет из 128 случайных байт
# мобильная сеть выбрасывает и рукопожатие не проходит, а такой же длины в виде DNS -
# проходит (github.com/bivlked/amneziawg-installer, ADVANCED.md). Только теги <r> и <b>:
# их понимают все приложения AmneziaWG 2.0; имя поэтому постоянное, а не <rc N>.
gen_i1() {
  local label label_hex ans ttl answers="" i
  label=$(openssl rand -hex 12)
  label_hex=$(printf '%s' "$label" | od -An -tx1 | tr -d ' \n')
  ans=$(rnd 1 2)
  case $(rnd 1 4) in
    1) ttl=0000003c ;; 2) ttl=0000012c ;; 3) ttl=00000384 ;; *) ttl=00000e10 ;;
  esac
  for (( i = 0; i < ans; i++ )); do
    # c00c - ссылка на имя из вопроса, тип A, класс IN, TTL, длина 4, адрес
    answers+=$(printf 'c00c00010001%s0004%02x%02x%02x%02x' "$ttl" "$(rnd 11 126)" "$(rnd 0 255)" "$(rnd 0 255)" "$(rnd 1 254)")
  done
  I1=$(printf '<r 2><b 0x85800001%04x00000000%02x%s0463646e730669636c6f756403636f6d0000010001%s>' \
         "$ans" "${#label}" "$label_hex" "$answers")
}

if [ -f "$STATE" ]; then
  # shellcheck disable=SC1090
  . "$STATE"
else
  echo "== Создаю ключ сервера и параметры маскировки"
  SERVER_PRIV=$(awg genkey)
  # Мусорные пакеты перед рукопожатием. Мало и небольшие: Tele2 и Yota по отзывам
  # пропускают Jc=3 и Jmax до 300, больше - хуже.
  JC=3
  JMIN=$(rnd 30 50)
  JMAX=$(( JMIN + $(rnd 20 80) ))
  # S1-S4 - случайные байты в начале пакетов рукопожатия (S1, S2), cookie (S3) и данных (S4).
  # Размеры пакетов разных типов не должны совпадать: получатель различает их по длине
  # (рукопожатие 148+S1, ответ 92+S2, cookie 64+S3).
  S1=$(rnd 15 150)
  S2=$(rnd 15 150)
  while [ $(( S1 + 56 )) -eq "$S2" ]; do S2=$(rnd 15 150); done
  S3=$(rnd 8 55)
  while [ $(( S2 + 28 )) -eq "$S3" ]; do S3=$(rnd 8 55); done
  # Пакет данных той же длины, что пакет рукопожатия, получатель может принять за
  # рукопожатие и выбросить - берём S4 только из значений без таких совпадений
  # (формула из bivlked/amneziawg-installer, _awg_size_collisions, замер 08.10.2026).
  S4_OK=()
  for s4 in $(seq 4 27); do
    p1=$(( S1 - s4 + 116 )); p2=$(( S2 - s4 + 60 )); p3=$(( S3 - s4 + 32 ))
    if (( p1 >= 32 && p1 % 16 == 0 && p1 != 128 )); then continue; fi
    if (( p2 >= 32 && p2 % 16 == 0 )); then continue; fi
    if (( p3 >= 48 && p3 % 16 == 0 )); then continue; fi
    S4_OK+=("$s4")
  done
  S4=${S4_OK[$(rnd 0 $(( ${#S4_OK[@]} - 1 )))]}
  gen_h
  gen_i1
  umask 077
  {
    printf 'SERVER_PRIV=%s\n' "$SERVER_PRIV"
    printf 'JC=%s\nJMIN=%s\nJMAX=%s\n' "$JC" "$JMIN" "$JMAX"
    printf 'S1=%s\nS2=%s\nS3=%s\nS4=%s\n' "$S1" "$S2" "$S3" "$S4"
    printf 'H1=%s\nH2=%s\nH3=%s\nH4=%s\n' "$H1" "$H2" "$H3" "$H4"
    printf "I1='%s'\n" "$I1"
  } > "$STATE"
  umask 022
fi
SERVER_PUB=$(printf '%s\n' "$SERVER_PRIV" | awg pubkey)

# Одинаковые у сервера и устройств (S1-S4 и H1-H4 обязаны совпадать; Jc/Jmin/Jmax и I1
# нужны тому, кто начинает рукопожатие, то есть устройству, у сервера - на всякий случай).
OBFS="Jc = $JC
Jmin = $JMIN
Jmax = $JMAX
S1 = $S1
S2 = $S2
S3 = $S3
S4 = $S4
H1 = $H1
H2 = $H2
H3 = $H3
H4 = $H4
I1 = $I1"

# --- 4. Устройства: ключ и номер адреса в clients/<имя>.key и .ip
for name in $CLIENTS; do
  [[ "$name" =~ ^[A-Za-z0-9_-]{1,32}$ ]] || { echo "Имя устройства '$name': только латиница, цифры, - и _"; exit 1; }
  [ -f "$DIR/clients/$name.key" ] && continue
  n=2
  while grep -qsx "$n" "$DIR"/clients/*.ip; do n=$(( n + 1 )); done
  [ "$n" -le 254 ] || { echo "Кончились адреса в ${NET}.0/24"; exit 1; }
  umask 077
  awg genkey > "$DIR/clients/$name.key"
  echo "$n" > "$DIR/clients/$name.ip"
  umask 022
  echo "== Новое устройство: $name (${NET}.$n)"
done

shopt -s nullglob
KEYS=("$DIR"/clients/*.key)
shopt -u nullglob
[ ${#KEYS[@]} -gt 0 ] || { echo "Нет ни одного устройства: задайте CLIENTS"; exit 1; }

# --- 5. Конфиг сервера. NAT в интернет, MSS под MTU туннеля (иначе крупные загрузки
# зависают там, где режут ICMP), FORWARD разрешён явно - на случай включённого ufw.
MSS=$(( MTU - 40 ))
UP="iptables -I FORWARD -i %i -j ACCEPT; iptables -I FORWARD -o %i -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -A POSTROUTING -s ${NET}.0/24 ! -o %i -j MASQUERADE; iptables -t mangle -A FORWARD -o %i -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss ${MSS}; iptables -t mangle -A FORWARD -i %i -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss ${MSS}"
DOWN=$(printf '%s' "$UP" | sed 's/ -I / -D /g; s/ -A / -D /g')
{
  echo "# AmneziaWG (relay/amnezia.sh). Правки - в скрипте, этот файл перезаписывается."
  echo "[Interface]"
  echo "PrivateKey = $SERVER_PRIV"
  echo "Address = ${NET}.1/24"
  echo "ListenPort = $PORT"
  echo "MTU = $MTU"
  echo "$OBFS"
  echo "PostUp = $UP"
  echo "PostDown = $DOWN"
  for key in "${KEYS[@]}"; do
    name=$(basename "$key" .key)
    echo
    echo "[Peer]"
    echo "# $name"
    echo "PublicKey = $(awg pubkey < "$key")"
    echo "AllowedIPs = ${NET}.$(cat "$DIR/clients/$name.ip")/32"
  done
} > "$DIR/$IF.conf"
chmod 600 "$DIR/$IF.conf"

# --- 6. Конфиги устройств (clients/<имя>.conf)
for key in "${KEYS[@]}"; do
  name=$(basename "$key" .key)
  n=$(cat "$DIR/clients/$name.ip")
  cat > "$DIR/clients/$name.conf" <<EOF
[Interface]
PrivateKey = $(cat "$key")
Address = ${NET}.$n/32, ${NET6}::$n/128
DNS = 1.1.1.1, 8.8.8.8
MTU = $MTU
$OBFS

[Peer]
PublicKey = $SERVER_PUB
Endpoint = ${IP}:${PORT}
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
EOF
  chmod 600 "$DIR/clients/$name.conf"
done

# --- 7. Пересылка пакетов, ufw, служба
printf 'net.ipv4.ip_forward = 1\n' > /etc/sysctl.d/90-amneziawg.conf
sysctl -q -p /etc/sysctl.d/90-amneziawg.conf

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow "${PORT}/udp"
fi

# Порт не должен быть занят чужой программой (своя - amneziawg-go - перезапустится)
BUSY=$(ss -lunpH "sport = :${PORT}" | grep -v amneziawg || true)
if [ -n "$BUSY" ]; then
  echo "СТОП: UDP ${PORT} занят: $BUSY"
  echo "Другой порт: ssh root@${IP} \"AWG_PORT=<порт> bash -s\" < relay\\amnezia.sh"
  exit 1
fi

if [ ! -f /lib/systemd/system/awg-quick@.service ] && [ ! -f /usr/lib/systemd/system/awg-quick@.service ]; then
  cat > /etc/systemd/system/awg-quick@.service <<EOF
[Unit]
Description=AmneziaWG via awg-quick for %I
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=$(command -v awg-quick) up %i
ExecStop=$(command -v awg-quick) down %i

[Install]
WantedBy=multi-user.target
EOF
fi
systemctl daemon-reload
# Остаток прошлой неудачной попытки мешает awg-quick up ("awg0 already exists")
if ! systemctl is-active --quiet "awg-quick@$IF" && ip link show "$IF" >/dev/null 2>&1; then
  ip link del "$IF"
fi
systemctl enable "awg-quick@$IF" >/dev/null 2>&1
if ! systemctl restart "awg-quick@$IF"; then
  echo "AmneziaWG не запустился:"; journalctl -u "awg-quick@$IF" --no-pager -n 30; exit 1
fi
sleep 1
if [ -z "$(ss -lunH "sport = :${PORT}")" ]; then
  echo "Служба запущена, но UDP ${PORT} не слушается:"; journalctl -u "awg-quick@$IF" --no-pager -n 30; exit 1
fi

echo
echo "OK: AmneziaWG работает на UDP ${PORT} (amneziawg-go ${AWG_GO_TAG})"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://tg.honestlot.ru/" || true)
echo "Релей бота: https://tg.honestlot.ru/ -> HTTP $code (ожидается 403)"
awg show "$IF" | sed -n '1,3p'
echo
echo "Приложения: AmneziaWG (Android, iOS, Windows) или AmneziaVPN."
echo "Телефон: + -> сканировать QR-код. Компьютер: сохранить текст конфига в файл <имя>.conf"
echo "и импортировать его, или забрать все файлы разом (в cmd, из папки, куда сохранить):"
echo "  scp root@${IP}:${DIR}/clients/*.conf ."
for key in "${KEYS[@]}"; do
  name=$(basename "$key" .key)
  echo
  echo "=============== ${name} ==============="
  cat "$DIR/clients/$name.conf"
  echo
  qrencode -t ansiutf8 -m 2 < "$DIR/clients/$name.conf"
done
