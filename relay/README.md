# Релей Telegram Bot API

VPS в Амстердаме (VDSina, Ubuntu 26.04, `89.124.97.131`), через который ВМ мини-аппа в Yandex Cloud ходит в `api.telegram.org`: напрямую с ВМ Telegram заблокирован провайдером. Зачем и как устроено — `miniapp/README.md`, раздел «Бот и релей Telegram».

На сервере только Caddy: принимает HTTPS на `https://tg.honestlot.ru` (A-запись `tg` в DNS honestlot.ru у SpaceWeb → `89.124.97.131`; сертификат Let's Encrypt сам), пускает IP из `ALLOWED_IPS` (ВМ `84.201.144.182`), остальным отвечает 403, пересылает запросы в `api.telegram.org`. Данных и журнала запросов нет, бэкап не нужен: сервер пересоздаётся скриптом.

Настройка или повтор после правок `setup.sh` (с ПК, спросит пароль root). Новый VPS — сначала поменять A-запись `tg` на его IP: скрипт проверит её и без неё не запустит Caddy.

```
ssh root@89.124.97.131 "bash -s" < relay\setup.sh        # cmd
ssh root@89.124.97.131 'bash -s' < relay/setup.sh         # Git Bash
```

## Личный VPN AmneziaWG

`relay/amnezia.sh` поднимает на этом же VPS AmneziaWG — WireGuard с маскировкой под чужой трафик (UDP `41443`, другой порт: `AWG_PORT=...`). Конфиг на каждое устройство (по умолчанию `phone` и `laptop`); скрипт печатает текст конфигов и QR-коды. Приложения: AmneziaWG (Android, iOS, Windows) или AmneziaVPN.

```
ssh root@89.124.97.131 "bash -s" < relay\amnezia.sh                                 # cmd
ssh root@89.124.97.131 "CLIENTS='phone laptop tablet' bash -s" < relay\amnezia.sh   # добавить устройства
scp root@89.124.97.131:/etc/amnezia/amneziawg/clients/*.conf .                      # забрать конфиги на ПК
```

- Работает amneziawg-go (программа), а не модуль ядра из PPA: на Ubuntu 26.04 с ядром 7.0.0-38 и новее модуль не собирается (с 01.10.2026), а упавшая сборка DKMS ломает apt при каждом обновлении ядра.
- Ключи и параметры маскировки (`/etc/amnezia/amneziawg/honestlot.env`, `clients/`) создаются один раз, повторный запуск конфиги устройств не меняет.
- Сервер пускает устройства в интернет через NAT, журнала подключений нет.

Почему так, а не иначе (ресёрч 07.10.2026):
- обычный HTTPS, а не VPN/туннель: WireGuard и OpenVPN между РФ и заграницей детектятся и режутся; 3proxy/tinyproxy передают адрес api.telegram.org открытым текстом;
- база и логика бота остаются в РФ (152-ФЗ: первичная запись персональных данных россиян - только в РФ), релей ничего не хранит;
- Caddy ставится из репозитория Ubuntu: репозиторий Caddy на Cloudsmith 10.10.2026 отвечал «402 Payment Required».
