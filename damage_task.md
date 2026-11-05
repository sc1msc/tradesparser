# Задание: проверка фото подозрительно дешёвых лотов

Это разовое задание для облачной сессии Claude Code. Код репозитория менять не нужно.
Результат - файл `damage_results.json` в корне этой ветки (`damage-check`), закоммиченный и отправленный (push) в неё же.

## Что сделать

Для каждого из 83 лотов ниже (список - в конце файла, JSON):

1. Скачать его фото во временную папку (например `/tmp/p/`). В ссылках есть символы `$`, поэтому в shell ссылку
   ВСЕГДА брать в одинарные кавычки:
   `curl -sS -L -o /tmp/p/<lot_id>_1.jpg '<url>' -w '%{http_code}
'`
   Если сайт отвечает 502/503/504 или обрывает соединение - повторить до 3 раз с паузой 5 секунд
   (`sleep 5`): в прошлый раз сайт торгов отвечал так на часть фото. 404 - не повторять.
   Качать по ссылкам из поля `download` (фото МЭТС идут через наш сервер honestlot.ru/img - напрямую площадка
   отвечает облаку 403).
2. Если доступен python3 с Pillow - уменьшить каждое фото до 800 px по длинной стороне (меньше токенов).
   Фото .webp при необходимости перевести в .jpg.
3. Посмотреть каждое фото инструментом Read (он показывает картинки) и вынести вердикт по правилам ниже.
4. Сразу дописать результат лота в `damage_results.json` (массив объектов) - чтобы при обрыве сессии ничего не потерялось.
   Каждые 15 лотов и в конце - `git add damage_results.json && git commit -m "damage check: N лотов" && git push`.

Если фото не скачиваются вообще (ошибка соединения, а не 404) - запиши это в `damage_results.json` как
`{"error": "<текст ошибки curl>"}`, закоммить, отправь и остановись: значит, у облачной среды нет доступа к сайту.

Модель: Haiku (выберите её в сессии). Если доступен инструмент запуска подагентов - можно раздать лоты
подагентам на модели haiku пачками по 10, но запись в `damage_results.json` и git - только из основной сессии.

## Правила (те же, что в check_damage_photos.py)

Ты смотришь фотографии легкового автомобиля, который продаётся на торгах по банкротству. Цена лота намного ниже рыночной, и нужно понять: не объясняется ли это тем, что машина тотально повреждена.

Ответь verdict = "total" ТОЛЬКО если на фото однозначно видно хотя бы одно:
- машина горела: обгоревший кузов, салон или моторный отсек;
- сильная деформация кузова, нарушена геометрия: смят перед, зад или бок вместе со стойками, лонжеронами или крышей, кузов перекошен; машина после тяжёлого ДТП;
- нет колёс, машина стоит на подставках или кирпичах;
- машина разобрана или разукомплектована: нет двигателя, дверей, капота, сидений, большей части деталей;
- следы затопления по крышу или по окна.

verdict = "not_total", если машина видна и таких признаков нет. Царапины, вмятины, сколы, ржавчина, разбитое стекло или фара, оторванный бампер, мятое крыло или дверь, спущенное колесо, грязь, грязный салон - это НЕ тотальные повреждения.

verdict = "unclear", если по фото сказать нельзя: на фото не машина (документы, ключи, логотип или баннер площадки), машина видна плохо или частично, фото слишком мелкие или тёмные, либо признаки есть, но ты не уверен. Если сомневаешься между "total" и чем-то другим - выбирай не "total".

signs - короткие названия признаков, которые ты действительно видишь на фото (по-русски, например "обгоревший кузов", "смят передок со стойкой", "нет колёс"); для not_total и unclear можно пусто. comment - одно-два предложения по-русски: что видно на фото.

## Формат damage_results.json

```json
[
  {"lot_id": "7227636", "verdict": "total", "signs": ["обгоревший кузов"], "comment": "...", "photos_seen": 2}
]
```
`verdict` - строго одно из `total`, `not_total`, `unclear`. `photos_seen` - сколько фото лота реально просмотрено
(смотреть все скачанные!). Лот, у которого не скачалось ни одно фото: `unclear`, `photos_seen: 0`.

## Лоты

Задание от 05.11.2026: 83 лотов дешевле рынка на 40%+ без вердикта (и 2 с «unclear» - посмотри заново).
Прошлые результаты (19.10) - в истории ветки и в `damage_check_cache_additions.json`, их не трогать;
`damage_results.json` начат заново.

```json
[
 {
  "lot_id": "7238565",
  "name": "Лот",
  "gap": 91.9,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$VTJooG8jkR3H2yTfpcnJmuu3R7M8TDHEJ5MIeakab6IKBuASWNg96.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$vOPx.lWwDL4pBZZmERoLePq5bTrzcGzpo.7BrcmpgmmyuXTE.EJe.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$bUCRfVseivHwmIzy7RzxN.XUaojO6girkxM5wfIHU0unKKpQKUNr2.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$ItBclOdq6xJdqKwPst22ouDFHBVNJ4KmUOx8rtiFOJV2oLkNO.8eW.jpeg"
  ]
 },
 {
  "lot_id": "7269755",
  "name": "Chery Tiggo 7 Pro Max, 2023",
  "gap": 91.2,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$GKd.e.7S6.KF6JhfxAXiu.qPO7xsA5cbk25ws6K1FHkq6PX81iCEa.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$iG1fBRo86jXCJaeeHFeOK.Ff45MP0CLCVd.TEzQBnv7MRQuzLEnW.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$J73g9QhA2Sy4IJKeGXEWau7ZNc0c.ynYzenqe9EMDpLhZ0ozuQa.m.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$r50WbHHw5x3B3AAmOK37BOfpuD5LFUOOdYkDxs82KCdafcELpaapm.jpeg"
  ]
 },
 {
  "lot_id": "9223511401",
  "name": "Volkswagen Golf, 1999",
  "gap": 83.5,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269260688%2F269260688_269260688.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269260676%2F0_269260676.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269260685%2F0_269260685.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269260680%2F0_269260680.jpg"
  ]
 },
 {
  "lot_id": "7251076",
  "name": "Toyota LAND CRUISER РRАD, 2005",
  "gap": 81.5,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$UDnX20TVEg6cpJEvSxrupOuZ4g9E9dSjEpM8WUNMXgnscNVcmrW6.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$0uulc275nG8AKeuvoju8Weoa1.16qWSkcrMAcgjvXzND872VRVVpG.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$skymNiRKTmh42LFpVTAI.vJJfRc7HomjWMuFm.PURf9BMCSH3vy.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$2P8LyH242cTm9qyzXPJrQ.aoZk2DfgS6DJv8dVXuCZvh1zv2rnM6.png"
  ]
 },
 {
  "lot_id": "7267498",
  "name": "Лот",
  "gap": 79.3,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$DWCIixRqBMscmlNdsu8Fl.BmKUUhRAdNy8D9C6KkRLKfOcQe9v6j6.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$xCRd4q1eRfJ8ZYsRD.zA1OdJrR04Wt76aha9dC5fd5wmw9iO9vnv6.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$XiYigw.edYhbMarl5WdtEODaVar72QPM.Q5rxbi91Vo6BqYejDOq.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$H4pOuorpatR2XS8Vs5QR5uyHsag1rH0A.0zSCb2v7S057ve.HLu.png"
  ]
 },
 {
  "lot_id": "7268714",
  "name": "BMW 320d xDrive, 2017",
  "gap": 77.5,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$Fm5EBIYBpcuhGaFg6vblBO6QytsxQFHmRPOAo.8yBOF.uKQHLBX6y.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$rTY3sCuoQcnpbtzddA1nC.nEpTx3ia6xCPmj9NJb8n6Y1BW6IiCq.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$2pk9YXCY4QSuqxYOqaJKP.A0U3nwFATjzv6lBLMgC9ncDc9vZhWkG.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$GaVxTd07.6LkFpQd.PZX2.6QcxAl71yvvJmSj6SpFq4j7pyVqigWa.jpeg"
  ]
 },
 {
  "lot_id": "9300390929",
  "name": "Лот",
  "gap": 76.4,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=7db85fba-8dad-4159-9d82-99c1dc746677&LotId=391464&TradeId=390929&_v=b1cf4758-47d1-4567-b0a2-c7ea5f060a39",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=93348589-44d1-4293-95ff-05878ca64514&LotId=391464&TradeId=390929&_v=8cc9b9c6-c992-4f18-a8fb-0af1387c08e6",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=758e8996-3dce-4909-98dc-163c94d82c0e&LotId=391464&TradeId=390929&_v=c3320c1f-ca16-4551-96e3-72ff9a0cb5d3",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=194615b3-7efc-4c4c-b48d-b64fe266600d&LotId=391464&TradeId=390929&_v=e4020a8c-f2d9-4b3c-8514-0ed7c4afbe14"
  ]
 },
 {
  "lot_id": "9224321101",
  "name": "Hyundai ix35, 2012",
  "gap": 75.4,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269886625%2F269886625_268773737.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269886618%2F0_268773748.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269886624%2F0_268773750.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269886623%2F0_268773754.jpg"
  ]
 },
 {
  "lot_id": "9224216901",
  "name": "Daewoo Gentra, 2014",
  "gap": 75.2,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269814867%2F269814867_269814867.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269814868%2F0_269814868.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269814870%2F0_269814870.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269814871%2F0_269814871.jpg"
  ]
 },
 {
  "lot_id": "9100020886",
  "name": "Citroen C4, 2014",
  "gap": 74.1,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$ogKSMBJSMmKomUsVHBYJ.E2eFDEmY1tKvJ.WYGkXJuL.WZalvHy.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$sBjZgyCI5V7Ep9c7tQ41eL1HlvPM..KlU8QSoSg4MU2PQwrtH4kC.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$PsXwoqVujM6NVDtz7LjSbOmE0cIdKEBsLkhZ4iG9eCXjc3EWKldrq.png"
  ]
 },
 {
  "lot_id": "9224133101",
  "name": "Chery IndiS (S18D), 2012",
  "gap": 71.4,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269749661%2F269749661_269150692.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269749665%2F0_269150691.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269749662%2F0_269150690.jpg"
  ]
 },
 {
  "lot_id": "7176593",
  "name": "Skoda Rapid, 2019",
  "gap": 68.7,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$2pWQOVSTnkZzxNLu5r1pN.NPavh1aMBo1FRzdue4FTA4M0Z8YJa.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$r9QNCVvdre82OXU34sdu1.lgVtrUw.EUsEnpLBWzaYbS8YsXaVYpW.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$nwZWnLBMG7w3PQ9gJIUENu02aNyfGHLdgYMi2DjFZDcSobqdtlayq.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$0ryN8yXM.OT3o3S4WDPZeziDZpkcsGOSSNqgGnnzlJ3BtcNjVF2.png"
  ]
 },
 {
  "lot_id": "9224000801",
  "name": "Лот",
  "gap": 68.4,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269637658%2F269637658_269038126.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269637655%2F0_269038128.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269637656%2F0_269038124.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269637663%2F0_269038120.jpg"
  ]
 },
 {
  "lot_id": "7209002",
  "name": "«Jaguar X-Ture» 2003, 2003",
  "gap": 68.3,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$xVC6pSOThFeeq67Ky98X.RCO5bHoPFlkehLKBxQyBlyIUZtrM2xW.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$qSemeuybaPZwLyl54.wouOYRXElehKpQR89c9FZFQEFfLmkfULQC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$1jZd2xlI2jGh5qyg4VRqOMxWKJWBwg0AA5sQmA.R8H2H.vTEDxC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Zx9kijgco8RnqovcwWbWulyNviwzkhc4U71dofPD4yzVlRf8e9G.jpeg"
  ]
 },
 {
  "lot_id": "9300389651",
  "name": "Kia РИО, 2012",
  "gap": 68.0,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$aa2OzU6uUWF1SZy4.BGPN.nudXUtMlW.ExwpIzrArg2.KkBXl2sYS.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$GrDDb6W1H2bVaeZVrVlYM.2Gy0ydKL0UwmMlZ1ehKvN6PUcXrIC0i.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$jsfirTBHGZskL2kroN6suYEaUD3TPadsi1EbEFj4lpsznJQd3yO.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$XVN5KM8hPXul5HmGcYZ7aejeevqjl39Kweym10GXcHwy1fWGBrU..png"
  ]
 },
 {
  "lot_id": "9300391565",
  "name": "Kia SPECTRA, 2008",
  "gap": 66.2,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=badb6276-dfef-42c9-8082-54cd60a400a5&LotId=392100&TradeId=391565&_v=eda4bd71-46a9-4802-9533-4c280f478f31",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=a5bdbb14-0806-4c41-922b-6b4527954ffe&LotId=392100&TradeId=391565&_v=eaacccc4-917c-4cd0-949c-7a04c43a380e",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=4cf5360f-3fe9-4606-a1c7-05f80bdad5b8&LotId=392100&TradeId=391565&_v=f033042a-f794-410b-a0f6-83df505f4901",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=5472a288-9e78-4046-baf8-4a949905ea7d&LotId=392100&TradeId=391565&_v=d454b28e-16e5-4069-9bc4-23b9d7c3cb74"
  ]
 },
 {
  "lot_id": "7245641",
  "name": "Mitsubishi Montero Sport, 2000",
  "gap": 65.8,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$EO7E1cEzi6UseITFN5AGefhNbtEXcsPYBRrD6MkPh1EzJvwpma.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$Tv1e5x8a0rFHsLIvQEaHi.x30u2vK2p098yiMjXLomN4IUGdnVb..png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$ZjB.ChZFMDVwCvmdHDW3ufSUV6DS8ht7egHl1noyx6ibi3FZpa6.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$LJs2xo72DEas0EuELMfymOzOfv5fPpqW3MML0mwedA4VoxbaLyaA6.png"
  ]
 },
 {
  "lot_id": "9300391929",
  "name": "Ford Focus",
  "gap": 65.6,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=468429a5-28ef-4ff0-baeb-8278bcd50c00&LotId=392464&TradeId=391929&_v=65693bbc-ac48-4480-b137-3debdc4b20c7",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=38233fde-553d-40ee-9426-919e07b249d3&LotId=392464&TradeId=391929&_v=385363f6-9bb8-4229-9ca6-831b1fd9aa52",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=d05fc3f8-f337-4bc3-8982-35aff754a79a&LotId=392464&TradeId=391929&_v=8dd4c4cf-41a3-4d4f-9cd4-1bf16f603739",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=4d8717cd-e4e5-4f80-b6f5-2b31a49f25b7&LotId=392464&TradeId=391929&_v=58e72a73-7b19-459e-981b-1cdee7b11097"
  ]
 },
 {
  "lot_id": "7266222",
  "name": "Renault Megane, 2011",
  "gap": 64.5,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$L0QJMft4YXTAhR00tR2ROzNTLO75ASJUs7GH66gQzEsy.jEjIWou.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$b3PkWQaciui2SPesWYYNaehqSc25DFTnlMvnecLTbq0WBGyK4xvP..jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$ebSiA7u2I5tNcGzWHBgwR.SR4LAE2koO1z87YaIGED.MP8AE1tleW.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$wwO29Sy53F5MvqnD9nB9neLyZP30TVhoaUiSSli3pnMNC8Sh85UO.jpeg"
  ]
 },
 {
  "lot_id": "9300379916",
  "name": "Лот",
  "gap": 62.7,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=d829c02b-0927-44a6-9e08-da4d0d17cb14&LotId=380450&TradeId=379916&_v=3905a4c1-d4bb-4dca-982f-b1a1a1c63d57",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=5683f3cc-6dc7-4424-8e6e-2266f9d93951&LotId=380450&TradeId=379916&_v=3d72569e-17ce-47c5-9a51-4618e912301b",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=b5cf5f23-1553-46ab-a0c2-675767950a12&LotId=380450&TradeId=379916&_v=4745f093-29a0-4dbb-85c6-4bf3b64abb33",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=04b696ee-60f4-4909-bbb2-4acc4b314580&LotId=380450&TradeId=379916&_v=0dd37f81-5a35-4db7-9599-b3643326139c"
  ]
 },
 {
  "lot_id": "7224949",
  "name": "Lada 219020 LADA GRANTA, 2013",
  "gap": 61.5,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$v3DbnszFU8YjqHSpXlyOrO82BXCwCKOQBFPmiLD4KnfnVzMVHLA16.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$YFc3xQMkZ4VAViDEysIeqehAaQw1PBm5gfCBpqyl0w2ZFiN5hba.jpg"
  ]
 },
 {
  "lot_id": "7234352",
  "name": "Peugeot NFU1OFX 6OPSA2745738, 2005",
  "gap": 60.2,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Os97Dnzf18uwyOBJkN8SuEDXNXIIdgFiWAtBQQGgMmVr1Ka2k3eq.webp",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ZTMdgq01.1Vxe8kl47coi.rfYh3vukTboLFyGTrDsaWUV25mLfQLe.webp",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$MxILSIWwAxG0p3qIqMoepOVDcfNbH.jJGrFMOHIOdii57Bcw3Yui.webp",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$4WJNhXJ5I66y91Jglma6AufjEabjLmtDNIVwoOJuXf8qw6tCQUwm.webp"
  ]
 },
 {
  "lot_id": "9300386203",
  "name": "Лот",
  "gap": 60.1,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=74f26ba2-2284-48c8-95e2-ca1e0f353e4e&LotId=386738&TradeId=386203&_v=a490ac23-b310-4c10-bee1-a4cd51f0dd7a",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=bca7243d-a9d4-493e-a842-845b6441075f&LotId=386738&TradeId=386203&_v=36478546-651a-4bf3-bd84-b6d7373d3474",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=63ca9349-f53a-4a8c-b164-178513e77bd7&LotId=386738&TradeId=386203&_v=52eb6526-28b2-4fcb-a6ba-23b420083863",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=53159605-b59a-433f-920f-13e79eab965f&LotId=386738&TradeId=386203&_v=e528e895-dbdb-43e5-9a1a-2f9918b48c51"
  ]
 },
 {
  "lot_id": "9300391659",
  "name": "Chery TIGGO 4 PRO, 2023",
  "gap": 58.7,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=bd1be8bd-0af8-479f-ba0d-c27f585f74c5&LotId=392194&TradeId=391659&_v=f82437a4-c2e0-4fe7-9c72-96b9c7d8f923",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=a582e236-677c-407a-baf9-59042bac73b5&LotId=392194&TradeId=391659&_v=0a85e5a9-1fd3-4e51-a452-e0d65433abd0",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=5493ebb3-bd43-45d3-9c32-52d692f2a233&LotId=392194&TradeId=391659&_v=5ed76ebf-82d5-445c-85fd-b84193629c41"
  ]
 },
 {
  "lot_id": "7223136",
  "name": ", Модель Тс: Вольво S80 ТС: ВОЛЬВО S80",
  "gap": 58.6,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$JdeHsVAR0ITswWHCSA5SgOyhFFgkCrJfGHQ.M36OOCiRIeBkdV5C.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$jtq1zMeoDpzgMs5klU4kuuE.GwO6gqlGx.0F8xz3kin.wn6d2p2K.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$a6Xe8mqhWmPQReUOvDNtc.MjkRoPTkFNqGzCv4lPZvZjqz6Q3E1AW.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$vkCG5lhaIGJ5iuliyp0aOpAA60v34M4JjZAimYJZW1uLn1CLbaWe.jpg"
  ]
 },
 {
  "lot_id": "9501171667",
  "name": "И(Или) Модель: Volkswagen Polo VOLKSWAGEN POLO, 2016",
  "gap": 58.2,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$bCsILtlHVkgcpCrBsj.Ug.1z8MmwFmzgBsxy32zuZagrDxOJBKae.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$DYuE0PtQqFtC10tj0c8MQu2Rh9bSSOXZ0e4eUkOuHSlzh7lLyuKcm.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$K4IIKghvP2grL.xOsCKvnOZD4M0.iqeUX9Yvsvc5pSX83Q7VmqVIa.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$cXsnuAh7Jp3z7SE6GlFvoOb9ewxm7L4z0APSHfyuKWCG0qjSxlJe2.png"
  ]
 },
 {
  "lot_id": "7227014",
  "name": "Ford ФОКУС, 2007",
  "gap": 56.7,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$bIYRkEpTPtUNaOQMKrFCruT0LAh0k4AAZcbISk6qCA7JbtTtUWv4S.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$7WdoCa00DP9gDbtgUaleqOleDMm.YgcX51bJQxazc8wN25Dthghm.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$lu7GoEs9hdMiVCZSeA02peA6yvdxKeAwjnPQP9GYhhwxfN15eZdpe.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$g0VSETyGj.X51RVs3Vbt5.SEmOkpugiz1MH9tz7uRLSqWbSmsgO.png"
  ]
 },
 {
  "lot_id": "7227372",
  "name": "Ford Focus, 2003",
  "gap": 55.8,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$DqjnluURMCIWtiZ7XyEOAeo0Fq7Q5h0A4KVE2RoRMIcc11.Rl5PiG.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$POFUVSizXRUT5kCIEIWUeefV0gbOh40RbPj81VOMYyaS.cv4O0x6e.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$yfgrBJZ.TUuki9nsXf8detkeIzxnl2F2sbT.iNoTtGyLT3Dz7CK.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Gts0I70zjy0cScaQUWQIoe2qGn1NggS0b2EVXJbIIhO0rT2bgVNVW.jpeg"
  ]
 },
 {
  "lot_id": "9300390446",
  "name": "Renault ЛОГАН, 2011",
  "gap": 55.8,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$LCKHWPA6hOAI.p2wOA4KvuwXIo2zjCV.TqdYkQNWx0Wl09NT1Hq.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$1VB8j872zV.iGO9d8TZwTO5gxcx7zBzIRIigiOuo61BN6fQAwoHKu.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$7yB3Z7gOG8R6MkK0MY2jeeQBJGU7d4gcnBfIjBBxfLnOY..OFJkTa.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$rI1LPVd5a.JETUrxip5lButn0tFCS0AKWT6yeYVlGTEKx6xXQRTBG.jpg"
  ]
 },
 {
  "lot_id": "7229361",
  "name": "Lada 2111, 2005",
  "gap": 55.7,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$PwGKRxWax22s.ebRY5xUwOB7ouZCbO8Fk8o7jd2HCJqajsDMAxPNW.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$KDvfDEuxs2TAzuUWB4a0ekCNgKT46G6XKUN.p9pRDzaMMLNmC3p2.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$hu0Y5oTvKQ6zaRAB.LZGgOZxdWJCZn0NkZtEF19lYQRUr4VhK5he.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$nhhmH5uTbKbiG624RbwDaufY9GDl21SZlU2wPVulPERRBjsJ63bi.jpg"
  ]
 },
 {
  "lot_id": "7272367",
  "name": "Chery Tiggo 7 Pro Max, 2023",
  "gap": 55.7,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$Ym0bNtGzWjdVg7MtQBHn.UYDcQTsCF.DHkkBCWydI9JFw4osMn8W.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$o7m.dzUmrxUD45TplhAgiOEzNC2No2eCQ9pCiItRAIEiEV8NkBdW.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$JXKQP8O09CCbSdl8ws.XOzAJZpIvOSLcAX7enBMhr18JgW8Dy..jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$W0jgYjCR6OF.P3U5CEiJNe.GI2o8jsHnF4Xgk9.VaPRrsqSISql0e.jpeg"
  ]
 },
 {
  "lot_id": "7229847",
  "name": ", Модель Тс: Ваз 21150 ТС: ВАЗ 21150",
  "gap": 55.6,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$3e1e78rdfYXaHxICrZfCQ.WfkAHGW62uMKUBi2XZs.EpEmenyCNr2.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$OaP4qIdCPranh21MIBmOBeRtZOvdG8htIGEIPcxkhSjagnKtZ3vlm.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$YvO6mqZyUj74twiqEFWeBbVwwgCRVnUjiLZo4SWc60KNBFBVr5u.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$edEiuCJkiRyKZWmHTCCrNeKs5Yt8hNLcMTMdWa.BktqQO72NA3iS.png"
  ]
 },
 {
  "lot_id": "7220461",
  "name": "Лот",
  "gap": 55.4,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$6401vebtJK5d6oUibz6KnecbcnVBjc35pzSojXCmRyTU6M68npicu.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ViCgByMw4K90Q4xJOrhnl.YasodXf7B5O7b55pvbdGG6lcCbwqTGS.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ppp03JBAhFmU4xbFh1zwOtclNHm8..7fiWZqZO7zXNLUFhUASy2.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$3zyJ5SZh.ormZOhI2wsqouAjG2a8mCCwUmtvU1S.huIE3Kiy.Y7zy.jpeg"
  ]
 },
 {
  "lot_id": "9300385633",
  "name": "Лот",
  "gap": 54.8,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=028a567e-d018-41ab-a491-34449f097c5e&LotId=386168&TradeId=385633&_v=8d764c3c-c34e-462c-8ea7-6b2aa6f6abb0",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=b530c896-87c7-4f8b-a2fb-cfb22da7a73e&LotId=386168&TradeId=385633&_v=55d27a31-ca4c-498b-95ee-350b33990b0d",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=7fc9a87d-3009-464b-9008-06dc4639494f&LotId=386168&TradeId=385633&_v=056af062-bfc0-4af3-981e-7bab788c7e30",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=287c2a24-56dc-41ce-b67d-cac37609d17c&LotId=386168&TradeId=385633&_v=1dbc7cf0-a7bd-4e80-b961-6f590428b84f"
  ]
 },
 {
  "lot_id": "9300385236",
  "name": "Лот",
  "gap": 54.7,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=86016ad3-c09d-4a28-a962-f571387e8a69&LotId=385771&TradeId=385236&_v=fdb62223-41cb-4022-9106-fc0c82b7f74f",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=11344723-a13d-42f3-9043-8339ba7ba1df&LotId=385771&TradeId=385236&_v=8294f2fb-1385-4856-8373-1052f7e63446",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=ecc0d90b-eab4-41d3-9caa-42d24c575ec4&LotId=385771&TradeId=385236&_v=379267d0-e1ce-4f07-b0c7-49c596f784d9",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=f2fdb2fa-72cc-4d2f-99d2-eba048353f93&LotId=385771&TradeId=385236&_v=2cf2a77c-0b96-48fa-b710-4248f0c523c6"
  ]
 },
 {
  "lot_id": "9224033901",
  "name": "BMW 3 серии, 2021",
  "gap": 54.6,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269672050%2F0_269672050.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269672040%2F0_269672040.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269672053%2F0_269672053.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269672026%2F0_269672026.jpg"
  ]
 },
 {
  "lot_id": "7225215",
  "name": "Chevrolet Aveo, 2007",
  "gap": 54.4,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$9xN0pZRW7sh10hBmu0j.MUwAHb5HSAXdPF6YLuJTbBJEHGmRXI2.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$0N07xTt2zu0x7z5sdpURN.KKqtSKL7dJVqH2nMY9.Br6IrnFgzC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$cVLemyxtvdsZLgl6ojsVsuwD4OtuCO.HXLpMYLThO3f5kZv.0l..jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$RS2AsekWQLxtMfRPQwxVOeEjI7Fla7nqDFDHKlP3O5hxM9BqqSga.jpeg"
  ]
 },
 {
  "lot_id": "7260819",
  "name": "Chevrolet Lacetti, 2008",
  "gap": 53.8,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$4c4mjxew84W0sJiwgYf44OCJ5WD4cpCGlBzNjtRKe4A1K3OaYK5Q6.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$6rUk38rvrNRIH51NNbHtO2C0GbRNZ2qgMJPXEeShKnN32UpM1h2.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$5JF6OevbMf7baLSBSzVz6.uzPbUJlGEjq0.rTImFnFApN1ZsO0t0K.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$dWw4F8TIHTm1HYG1th1h..bD9A.LQ801RB1tEp88RG9GpxtfiTFem.png"
  ]
 },
 {
  "lot_id": "9100021725",
  "name": "JAC J7, 2023",
  "gap": 53.3,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$bcq8osu8OpxE2Ui0YKI60.l2OHpod1BhZYCQxC4jc6Pn.b3mx4wa.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$CsDZsX5Hk9EXUtHQyVEVuogLyfVl4R7RxaBOUBmB2zqB0RW8xI6y.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$6p89uoW7PJAdeKgNq0iN4.Y7h7RCZrlYRrMTsMJZ5HToFRd3q.DC.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$UfDDF0KZhbIko6oLtnWEcOLyD1sgErBJfYwfXmURhKh50RPa5La7m.png"
  ]
 },
 {
  "lot_id": "7245776",
  "name": "Лот",
  "gap": 53.1,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$jm0B0Z6lrwL1.aBKUdKFQu0hqxPWvjbukcpLh8YRdLUn9wsqG6Nm.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$kAtVSO7OidOC4WeQWoDJT.dRVuSS8JyGCweBxVXekz46omJDdlW26.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$qjKggbwvLhCI5RsWLUCO0OQifOvhraBuVpHSE5VLgrcf8xEs5iRS.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$tfYyjwUZ3VWLyHGtgYZe6edIqpU2uDX4x6pq5EeHKX0X9OrrrFXEe.png"
  ]
 },
 {
  "lot_id": "9224272301",
  "name": "Opel Insignia, 2013",
  "gap": 52.9,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269862589%2F269862589_269862589.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269862588%2F0_269862588.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269862593%2F0_269862593.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269862592%2F0_269862592.jpg"
  ]
 },
 {
  "lot_id": "9300384125",
  "name": "Nissan ALMERA",
  "gap": 52.8,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=c754ef86-4a38-4e3f-8799-ac4e386173c2&LotId=384660&TradeId=384125&_v=62e902b7-848a-45c3-af56-ffaf3bb5234c",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=5afc20eb-117d-4f7e-81d6-d7e456e95db1&LotId=384660&TradeId=384125&_v=cb2041bd-e9de-49ad-ba57-6d3811dc721d",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=eeb58cab-de7c-4cb5-935b-912e969aa9f4&LotId=384660&TradeId=384125&_v=0a66e92b-c81d-468f-a9ee-504361e71ea8",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=e16c686e-799f-4f27-b1d6-d70a7b8a16c1&LotId=384660&TradeId=384125&_v=89fd2d64-0838-4814-8b0d-ff57b04fe7be"
  ]
 },
 {
  "lot_id": "9300389895",
  "name": "Лот",
  "gap": 52.3,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=986e71dc-0c6b-4f34-a0bb-24959933cf8d&LotId=390430&TradeId=389895&_v=6a201b53-81ec-42e2-99b0-27cacf478e0f",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=8ea768ec-f1ed-41d7-91d3-e6c4c2cdbdb6&LotId=390430&TradeId=389895&_v=510d30ca-3cff-4d5c-b340-7a49baabd6fd",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=fa8d5e38-9fe4-4e39-911f-0a3f54d0e5e7&LotId=390430&TradeId=389895&_v=ac1cb533-2cd0-46ec-83d4-16ac147357a1",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=3aae27f6-d8e5-4d23-aa34-1a1e963ab02b&LotId=390430&TradeId=389895&_v=72a3163d-631a-4f5a-8ab6-2c6495340db5"
  ]
 },
 {
  "lot_id": "7173228",
  "name": "CHEVROLET Cruze (4DR NB), 2012",
  "gap": 52.0,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$VtZEF0leKR4VxOHHZo.QejXbqksxW5B5Y6IrdgtAlGsCvKmy6QOW.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$2nhbonukJH1plwd.scp8cugd2mbFpdRlKeUvdTB9sP6hqJpiwqtBS.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ezuwSARpgKg0B5KmCbJMG.f6JUyCgq2umZfJwM6O15DKQogWsAYl2.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$GaJT9GrYhy1iPkV7zRu0Qu5bj9fyP5r.GimFocWPMEz.44.nIiXm.jpeg"
  ]
 },
 {
  "lot_id": "7211957",
  "name": "Ford Mondeo, 2013",
  "gap": 51.9,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$swvBevmPjDnhc9I7e9rdRe4TEqEfU93wSlL1EbaKQE2Q7kjZde1W6.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$aq93FAAe2xEuscHFfvBgK.0YneznUTvXRoFiffDygNc9rmuASXsI2.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Xo14JgSWRn7miC9rxdIB.Wx2hivp0pkqy4mzlxSDGHI2a3CPKuvW.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$p3F5Bgl5T2Xl6XD7oh3eg4Q7rk3NilLS1KfDghw4jduMw6kXgx..jpeg"
  ]
 },
 {
  "lot_id": "7138447",
  "name": "Great Wall грейт волл сс6461км29, 2012",
  "gap": 51.6,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$0Wr4y1imlwHNirU.mtJeS.PVlXzv7f33t9DaMhNhxBJMFEt7gn9mq.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$xooxmzbT6ymokOiSirRIDu6bTEqijJnvYC0lf66e299j2NCY4QXpG.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$TJCXtJif.izXSDGT6N.bu6ZiJmKrLTVhOnzcSnRkdSjhojaBfccC.jpeg"
  ]
 },
 {
  "lot_id": "9223957501",
  "name": "Hyundai Santa Fe, 2008",
  "gap": 51.5,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269610635%2F269610635_269610635.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269610625%2F0_269610625.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269610628%2F0_269610628.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269610629%2F0_269610629.jpg"
  ]
 },
 {
  "lot_id": "9300391003",
  "name": "Лот",
  "gap": 51.5,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=6e51708f-8c4f-4c97-9dd7-c22e590851f0&LotId=391538&TradeId=391003&_v=582c4981-7502-4465-8647-c20e5409a221",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=ae56cb81-08f8-4138-b1d0-c5bb1b9f02cb&LotId=391538&TradeId=391003&_v=8b1e31d4-d143-48f7-8566-0c9e59707b23",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=93ad9b7b-a858-4f24-aad6-bb0c9ade9f30&LotId=391538&TradeId=391003&_v=9c742935-8b85-47ce-99bd-e6291f681a3c",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=13c0be87-bbf9-4712-b87b-19a5f25830d6&LotId=391538&TradeId=391003&_v=faef8cf0-7cc1-4672-964f-6bd7af6a2dea"
  ]
 },
 {
  "lot_id": "7198461",
  "name": "Lada 219070 LADA GRANTA года выпуска, 2016",
  "gap": 51.2,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$MnGiwqUiz5ByEmCCSs8fzeVcBblJ.X.OdSAswKffF0iso19vzqG.webp"
  ]
 },
 {
  "lot_id": "7070626",
  "name": "Ford Fiesta, 2015",
  "gap": 50.5,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$k8e2cdZbeu4sh3LpB9GVuOUdiKkEMxF.MOpufT9o6VxbVtAVbLxn..jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$fY5tNwFElNSheYpaiQBUJOlxqPKo0.OLQJSvkUV2GOYiY9W5KIsWC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$LQB7sj6DdI9Vk.VFOoKnY.499OCJWIF0QapF8uO7ekHfIawJquhPm.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$grDetbFwLkIkE21Eps8CXOahGXDwbd9JFukg0543m0HnMgcc4hwDa.jpeg"
  ]
 },
 {
  "lot_id": "9224082601",
  "name": "Skoda Octavia, 2018",
  "gap": 50.3,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269705667%2F269705667_269705667.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269705666%2F0_269705666.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269705669%2F0_269705669.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269705668%2F0_269705668.jpg"
  ]
 },
 {
  "lot_id": "7226355",
  "name": "Opel Astra, 2011",
  "gap": 50.0,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$f2X7UEO5H53zYbRBZ3WeGe.8MkjoGuOeeADaW6ffYDEJAWrGjoHC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$.KbtKCiUuZyCHzR.8sQ1Qu5cQiVlMwPUIrn8.qQ88PBpz4byaNcw6.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$wVy6Z3cUTRVNtMRQ2ScbDue2e1xLl1bcXB4HGZRdOVO.7NlLAS10u.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$hxSGvhTdzJi4Re912JPpev9lJ168eJj39Vxqz0CsKFEMDE.DzuDa.jpeg"
  ]
 },
 {
  "lot_id": "9300386775",
  "name": "Ford Focus, 2011",
  "gap": 49.4,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=01777613-28a9-4d90-bc1f-22a339bc6ad3&LotId=387310&TradeId=386775&_v=19e7ac2f-9be7-47b5-9d9b-994702718732",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=64a90a5e-13c2-417b-8dd1-7f2d9fb081c4&LotId=387310&TradeId=386775&_v=cf6981b8-9f8b-4bf2-a259-d7f8acf4f5f5",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=4a0b95bd-fc3a-435d-a08b-5211ba268a9e&LotId=387310&TradeId=386775&_v=9a641f62-d615-4128-a9b9-f801bcb43fe1",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=134d778f-5cc9-4f18-8b6b-049b2a5adb02&LotId=387310&TradeId=386775&_v=e3ea72bd-a730-4bea-8588-2f4c941dc948"
  ]
 },
 {
  "lot_id": "7255565",
  "name": "Volkswagen ПОЛО, 2017",
  "gap": 49.2,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$hlRo5CzSA4hq51oYsYZl8eOQIGMn7wtlnrYm8ygv6zsh2e2rPe0ZS.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$xr6lYslQDBuWlNbHzl3J9OjxNGCgHuB.Xxn207qxdHJWdjBB5yU1K.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$H5oMLDnBYST1Y0R2kKbcGuLODj3GyI0Z9aY2y59LwIXtZ.nclVpm.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$dkt9zBTsgS8O8HddmWnYJum0OXTA3obV1WQtMNaiDiWYocaAZkCQq.png"
  ]
 },
 {
  "lot_id": "7191790",
  "name": "Citroen C4, 2013",
  "gap": 47.8,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$BqAhOhNMRiRLPhzYTfGAeKejUoCCvzZM6WzPywJycR1gZ6Fg8NCa.jpeg"
  ]
 },
 {
  "lot_id": "9224212301",
  "name": "Audi A3, 2013",
  "gap": 47.7,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269809330%2F269809330_269149005.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269809327%2F0_269149009.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269809334%2F0_269148988.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269809326%2F0_269149022.jpg"
  ]
 },
 {
  "lot_id": "9224275001",
  "name": "Лот",
  "gap": 47.5,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269864955%2F269864955_269864955.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269864948%2F0_269864948.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269864953%2F0_269864953.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269864949%2F0_269864949.jpg"
  ]
 },
 {
  "lot_id": "7181207",
  "name": "FORD Focus 2004-/Focus C-Max CAP 2003-2007, 2006",
  "gap": 47.1,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$X7YLcGsG86ujyHQOw7XS.mJDBWfERtmqX.KVIO7mUrSJckWdMl6.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$KR6ws94PBKXoODIMGiguClMLRYHYTYg1rSWMSa0k0xt3s2O2tS.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$WbSFUryOnhbghVlJDWJNje.bJISIxt6rUWW3GDcSWfcwLx8h.2KC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$8apef8AEmLBsCcMAf1H7eueE.I7oPSxgwEtjOLFfFya2gu1E6ZMvK.jpeg"
  ]
 },
 {
  "lot_id": "9100015276",
  "name": "Opel модель Astra, 2008",
  "gap": 46.9,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$WThiUGmyJbzokTp0m5v7qenjkEqXDfR2.ip42leq0OQsuY0yoELyO.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$XakwwCIzKyVH5ffSzUNJIenuLohhBKYVn6nNWz8ETnKcUSUY7pmS.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$wbxMpn2MN4ZXUVPEM9SI4OKk8NX5VaFJXBfJvci2qwHTG8Pf4DOYe.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$rW0h35lN3ek8MwUQo0Nne7jslm.xEpm3o7e0EHkEimtnX7.1VXpC.jpeg"
  ]
 },
 {
  "lot_id": "9224270101",
  "name": "Cadillac SRX, 2013",
  "gap": 46.9,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269861483%2F269861483_269278205.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269861501%2F0_269278245.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269861497%2F0_269278240.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269861482%2F0_269278246.jpg"
  ]
 },
 {
  "lot_id": "7173946",
  "name": "SUZUKI Grand Vitara, 2010",
  "gap": 46.2,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$pvAJllUtixQbohultSuqf.7WvTJ.6DDWgZ6JE4vhU9lX6yOnN9NbK.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$CPJhX1I6vgWNdg9IHyCM.T9.I9lji6JWjJ4I8wJ5TVKQ6YcxEVCC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$I2zKYJLzV7Z4Sy3WV1SulOcTwU4d86SzRh41fYEugqdo8V7ykzSGu.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$b98NndAwgUtZFX5ax9Sll.u9GUmNywfxYJSMajUHOH0UG8Nv7c09y.jpeg"
  ]
 },
 {
  "lot_id": "9300386696",
  "name": "Лот",
  "gap": 46.2,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=6bd4a717-6e2c-432c-bdf0-ae80939cb49b&LotId=387231&TradeId=386696&_v=49114f29-08c4-4cd9-8b50-f61fceff1abe",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=4c47e7cf-610d-4165-b51c-b2ef7deb2289&LotId=387231&TradeId=386696&_v=19f7ea86-8a5e-4ead-87cb-c8de9ba9bc2d",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=c05ad529-ac59-4cc2-bc06-6b0d7656e67a&LotId=387231&TradeId=386696&_v=6835ffbb-6a35-468a-b321-94fcb37132af",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=484f6b53-6d4e-44e9-b6d5-7a8114731587&LotId=387231&TradeId=386696&_v=a4d06466-63c8-49af-b5c1-42d94d55f31d"
  ]
 },
 {
  "lot_id": "9300387076",
  "name": ", Ваз 21041- 20, 2007",
  "gap": 45.6,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=f0530cf5-6c3a-4e5c-b690-ba4194f44d37&LotId=387611&TradeId=387076&_v=0108e9b2-7f90-460a-9c55-6cdd16a2bfd1"
  ]
 },
 {
  "lot_id": "7193356",
  "name": "SKODA Octavia, 2014",
  "gap": 44.8,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$1u3Cnd091f1EAIs69Kz2lOdii81G7BQXpErzYre8ETUzpLQGz4Xke.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$QRXfUb3LhJfoqVXnrGuk5uUSafZ2H7ykOfC9o8FLQFJoBW9Ms0S.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$LmLJiU760AjzPL9F5.wuJePWrHhiBaqlzY.Xw9IZwlqyElRRvEs...jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$e1DBJVNtOVhoPTbsO3Bzwe838.RLIp3S86gvRvcUyY8HkoH3oNhSu.jpeg"
  ]
 },
 {
  "lot_id": "7263207",
  "name": "Mazda CX-7",
  "gap": 44.5,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$ro1qnKajkZ4PjUy0vp650.RhK5OqmgxZkxN76WFS5sBnA8qbczYIG.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$KM8fbevQLhdNMit1Gp931eX9bb4c19.p7jqeZ7mkRycoJIhBgEad2.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$xALdcSxlU3wi3Zqkb8bEOWdNMi337bn6iRjdjkaZruwnKkdTNwO.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$yoFsVBs2X6jxQU2x9Og6uYjRgP.Os.7wWNriWt1vgtTAXFwuR5G.png"
  ]
 },
 {
  "lot_id": "9223968501",
  "name": "Vortex Tingo, 2011",
  "gap": 44.2,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269573125%2F269573125_268244446.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269573131%2F0_268244431.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269573130%2F0_268244433.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269573121%2F0_268244441.jpg"
  ]
 },
 {
  "lot_id": "9100016355",
  "name": "Volkswagen Polo, 2018",
  "gap": 44.2,
  "download": [
   "https://bankrot.torggroup.org/Picture/Show/82976"
  ]
 },
 {
  "lot_id": "7196618",
  "name": "Volkswagen POLO, 2010",
  "gap": 43.8,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$tzU5QYTlqCvLIAVw2PtfvOVLOuz8Vzbe2NhzD2hxLAH.YfXkSVBiO.jpeg"
  ]
 },
 {
  "lot_id": "9100020831",
  "name": "Volkswagen POLO, 2018",
  "gap": 43.6,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$r6fJzPjpHyG7kRPsfEfrBuYokgG0cXI9L7D0lCAz82CNWiD8fy1f2.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$C9WMOqNhcDcdOuZ3Cx7dhecUcpg22oj6U5g2pxqsB6mIiRdwCWlKS.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$p4v7Lk2r21E7tGSsDupT6uxeRiym32y94UwnM2lnniR.7qKpAN7bC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$nvbYUqbGenI78u6.bnP2gOpKlfg.uchRmKNIxIme2EZD5HaGrXFa.jpeg"
  ]
 },
 {
  "lot_id": "7229452",
  "name": "Lada 111930 КАЛИНА, 2012",
  "gap": 43.3,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$15Km.Q8Uz77d85wrJlsgIuOSsZ9cGxNmyLqwriWTwGPK7EtATKn0..png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$5CDpcjLtWnqSEgkY1ts.TujLVMIfkHI9..x4UWavL0lfz5NIS2Se.png"
  ]
 },
 {
  "lot_id": "9300385551",
  "name": "Citroen С4, 2008",
  "gap": 43.2,
  "download": [
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=ec51251d-201f-4d0b-a645-1a7d952c5819&LotId=386086&TradeId=385551&_v=91fdaf6a-13ff-4370-8c90-cc187f4d1e33",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=a20e3ae8-c90c-4649-8043-6178b1766331&LotId=386086&TradeId=385551&_v=7588aea5-1d6f-4e31-b1f2-b58fad20ce45",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=864b0dc7-d435-4b20-bb3c-3f1f2df77b1b&LotId=386086&TradeId=385551&_v=ebed61d1-fb16-41da-b506-a0c2ed41cc21",
   "https://webapi.torgi.cdtrf.ru/LotImage/public?LotImageSize=Large&ImageId=45ab4a39-ceb4-43d8-8f9e-aee7edc3de11&LotId=386086&TradeId=385551&_v=cb99a9bd-48a1-489f-933d-a72be016a2df"
  ]
 },
 {
  "lot_id": "7228755",
  "name": "Lada 21070, 1999",
  "gap": 42.6,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$r3PjW4cmYn2.zpQbUJXjXuAD0WpWNdGleTgh8J2qvRVglUeNHaHOe.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Y3hKm4KpQXNvadHEn8KPh.R5HuFqDadaKp0GdWaDGYBF8Vjby8wGO.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$65tROx4rtbsnOHAURiOHLuOf6RiRGH.2Jrgr3LKegQgJaQqJRbFC..jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$nMbmFxv5UwDW61rhwz.ZOahKUM3clonHfVs0G6dZyLLKjdFuBmC.jpg"
  ]
 },
 {
  "lot_id": "7177760",
  "name": "KIA Optima, 2019",
  "gap": 42.3,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$WkMtAPGcEMVf79Odi9yNxe6QdlUTzubFJE30aTMMbzZjWBZ7t0i.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$l3oDkqsmCHANdEhatZwaIOAOiZ5MdyYABEHIhCtNjIA5p0RPle7nq.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$50bumbBiYoBS7p7jCL6VTOCTR3MGy5Eb5FWgYHHa8eVnIxJWcae2.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$wb1Db9zfL6DCYlxhEwBeGMKKXSNkBrYyh9HsWVgYZ5OOrxm0i.e.jpeg"
  ]
 },
 {
  "lot_id": "9100016694",
  "name": "Opel Astra, 2013",
  "gap": 42.2,
  "download": [
   "https://bankrot.torggroup.org/Picture/Show/83606"
  ]
 },
 {
  "lot_id": "9224017601",
  "name": "Peugeot 308, 2008",
  "gap": 42.2,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269635900%2F269635900_269635900.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269635910%2F0_269635910.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269635966%2F0_269635966.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269635911%2F0_269635911.jpg"
  ]
 },
 {
  "lot_id": "7190801",
  "name": "Mg 5, 2023",
  "gap": 41.8,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$l8BHSEx2Tiz7t1O098O38eYQV.TK4HKUconcJsJSIOyJ4UCeymJ9m.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$qjdkpfETLCRUKUCd1zXrTuLr22P.X56sTU1qMs6u6RiKL15bw6GSW.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$MdqH25zMHJy.Ivr6c1d0eOaFnQO6Bxj0mC3E7t9EDXQ2JlWghzxK.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$AAcNEDtbg25RYLpkWDalOZTCz7BxMCmuFdJhipTEqLUzIIUThz5K.jpg"
  ]
 },
 {
  "lot_id": "7229588",
  "name": "Лот",
  "gap": 41.3,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Kie7kg434jKZrZxX6zAz3ebNYe9TA84g3FSLPEJH1gMV679rV8e.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$lGG36dKcTA24zFovJxdCgO0D1lojHK16fjuwIEoEESgmlOfEapBay.jpeg"
  ]
 },
 {
  "lot_id": "9224113601",
  "name": "Mercedes-Benz GL-Класс, 2011",
  "gap": 41.3,
  "download": [
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269732840%2F269732840_269185077.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269732844%2F0_269185071.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269732842%2F0_269185067.jpg",
   "https://honestlot.ru/img?u=https%3A%2F%2Fm-ets.ru%2Fdownload%2F269732847%2F0_269185072.jpg"
  ]
 },
 {
  "lot_id": "7131996",
  "name": "NISSAN TEANA, 2010",
  "gap": 41.2,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$UGMfEaf6kltdx7PMzffOLLDK6acOFknzf4gDzgSlCs6gLUqFX2.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$1Wy5EyRhwxP8YrQpVMtQ6.N9vOIZ7cUxtcMCPtlykAN4062.AZ71e.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$U.I09pQQCiYmRc8CUa5lHe81QW4zvZ.cwix3kIxlxc2VX1ZMO5SXO.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$SOgyZTdnvtSBcUb77f.dOJwfoWAcB4w5WD.qJpPPpQglfg3dd9Ee.jpeg"
  ]
 },
 {
  "lot_id": "7260305",
  "name": "Kia Rio, 2012",
  "gap": 40.8,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$eTOnO3Qv8Z8XhJjybdGsOXC6MsP4OBiccCUp7W6VrgX2ylnHjdxK.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$DJYolek4ryt5vSN4QdkxT.Vj3LzPRo.cpsVHiIsXjMOEUblXz0hK.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$DuUK1XdnNQnMjrkHvMKQOOsyooMVifaoFAyns0civ7jfcRgxHU..jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$12$T1TRE8VgX4ZVrp.hs8EyueKgv7ijv.h47AfZWRBlmykLrV3XdtnCK.jpg"
  ]
 },
 {
  "lot_id": "7160709",
  "name": "CHEVROLET LACETTI + NUBIRA + OPTRA (J200) [EUR], 2008",
  "gap": 40.7,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ZfwrOTQc48IGNUW8htkwceqS6XByun4l7ZEdqn5YYZ4TpUDUzLTC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$KHeAKBxtYPXf.aZmY704.YxT7ZvRLtdddL8hpiI96XaSarrZvd9a.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$9EQivmGkiSP21x0KWlwht.sFsmchc.NuF0Rbj7QlaVKLpAitjyDe.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ehws0SsDZBdvRHg7rsHh0.8NO3etySVKtA2u4Ce13otJyPMEmf.o2.jpeg"
  ]
 },
 {
  "lot_id": "7134701",
  "name": "OPEL ASTRA-H, 2008",
  "gap": 40.5,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$stHD..A3uNSOk6XbdvmfLuo3zkqNGVxLG4nHhvL9L3YF97Sd.6ROi.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$fLzTcWoRmOUJTMruO8zu4O.aHPXXQOOfOTa7tiiI2Yp4761EknOvC.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Gpn.NaM12YrTlGtu2Ae8eOj.h3p1qY3FIUrYV4kG3lLIbRnbm.0y.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$CwRvs0TZARMPiQWHn8mtR..8PTbpdp3HLmzmm0Ddoq5iu42cHOoa.png"
  ]
 },
 {
  "lot_id": "7200889",
  "name": "Volvo S80, 2011",
  "gap": 40.3,
  "download": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$BIxFIFKMvssVSemItdCUkeq2keP1oZuG2WObuWEU0nmgZsG8wOAm..jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$fEViW6nY1VW69MRw.9Afju3fM6geyWUv29Fow8qS7nsnSrZrzVeHG.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$TxB7tWFni6tPFnPgjLrAOBEn931Qrdm9AhIoYJ7O8FuZ4B47mphS.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$71gKm1KJdakk9nU3g.gt.ccGfnihG5FCXwEdItnklmdvuiaBnxzO.jpeg"
  ]
 }
]
```
