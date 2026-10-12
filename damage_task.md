# Задание: проверка фото подозрительно дешёвых лотов

Это разовое задание для облачной сессии Claude Code. Код репозитория менять не нужно.
Результат - файл `damage_results.json` в корне этой ветки (`damage-check`), закоммиченный и отправленный (push) в неё же.

## Что сделать

Для каждого из 31 лотов ниже (список - в конце файла, JSON):

1. Скачать его фото во временную папку (например `/tmp/p/`). В ссылках есть символы `$`, поэтому в shell ссылку
   ВСЕГДА брать в одинарные кавычки:
   `curl -sS -L -o /tmp/p/<lot_id>_1.jpg '<url>' -w '%{http_code}
'`
   Неудачную загрузку повторить не больше одного раза.
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

```json
[
 {
  "lot_id": "7229744",
  "title": "Транспортное средство HONDA ACCORD, идентификационный номер (VIN) 1HGCV1F96JA009468.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$kj1WWIZSv9rjCIC1IC5Gk.pqGzzjPYrz2AxXKgdjjGvNq93.47kde.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$sz0qexvqHEWsy.D9WSwWb.Pxd7v2oCG7FhcyGyk2wPGTdLvW7v2.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$fFewNL3xUROJQGqRQsMs3ut1O56xkz3VsokgaB80yAWeLq.UnS3uG.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$DiMJihQHLA0auI0AcKdmIekArBzbh3VfSeYP492AxdAD8ljPYQ6.O.jpeg"
  ]
 },
 {
  "lot_id": "7223710",
  "title": "Автомобиль",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$NlFBFIDnIx1CFB92h9LBGuQsJthCRhkbcE15vxxny8AfTsWlY9ZIW.png"
  ]
 },
 {
  "lot_id": "7229662",
  "title": "Автомобиль марки CHANGAN модель CS35SC7164A АS 2017 г.в. VIN-номер XDJA3ABE4HL000550",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$hhOTrwtcYH0EpW8S6pM6QueLvgDgpVvgJ2dbyVecSeLjUbwfk6Oma.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$SN73iV.2aqjn0IDPjAKvkOHTsuvIXQwgO6qHSLHPMtSAtoHCI7S6m.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$zjG12HsA3s194Dvfz.86u1m2E5m0YdiGj0aM0V7yBGy3s7o3S.W.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$7DrnLPpvvVU357C.Hqa9eI5HKnOKG2PenGaSGocxBYoo9fsyORBy.jpeg"
  ]
 },
 {
  "lot_id": "7234087",
  "title": "Автомобиль марки CHEVROLET модель Niva 2014 г.в. VIN-номер X9L212300E0532284",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$sTG7ytwDxN97L7eEhkL37O8I0rBU4siMmrDDggP9uF.sCt7KNL6..jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$AYQ5gpAT4QJK75VumE08OAN9yho0tS7AelLmCb0eQscFCNuih89u.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$rfmAK3YJ3pdL1TXCsJbGZ.skKGU4LqQcJnjQG7bUlDQCFkbiqu12.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$eM8oaJBzIaCph9lFcrqoaOjc39z.Y2eKlDNq1VtMzxsrxppJbKGPq.jpg"
  ]
 },
 {
  "lot_id": "7224970",
  "title": "Публичное предложение имуществом Багдасаряна Г.А.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ei0G3J8wSrniJ.Njyc2zDendMomvf9h6aJqwEa35TtH5HES3HRxm.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$rJL9rnG6.AJVmTOgSZugeFfEhDK6sfEAJmKsu3ETKwCVZkqqV9Qy.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$9AHlE1B57ldupU8rTwQ.gO7zsey9Jiq4TC9wFup7jcgMhtrYbiEjC.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$sDnUj5UkkLTF9dsJUr2Np.mMgEUfSKQZ8cGdeyidlPD.PuReDCqsu.jpg"
  ]
 },
 {
  "lot_id": "7224949",
  "title": "Легковой автомобиль, LADA 219020 LADA GRANTA, 2013 г.в., VIN: XTA219020D0148505.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$v3DbnszFU8YjqHSpXlyOrO82BXCwCKOQBFPmiLD4KnfnVzMVHLA16.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$YFc3xQMkZ4VAViDEysIeqehAaQw1PBm5gfCBpqyl0w2ZFiN5hba.jpg"
  ]
 },
 {
  "lot_id": "7232714",
  "title": "Автомобиль марки PEUGEOT модель 301 2013 г.в. VIN-номер VF3DDHMY0DJ716632",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$IT7RpZtfc6hQfLyvxtTVZOxRUnM9E5MqOitRDCY4yqfCq3iES3Tom.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$k3KYQIEoKm1hnhOLpZwPQ.a8rpajkmATuuTbbsf1VMC293fo.BY2.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ZyZIOw7mHxNZnsOEeSCc8uQOccAnAx4xKVTYPebazEIXdbPQ03H5i.jpeg"
  ]
 },
 {
  "lot_id": "7234389",
  "title": "Infiniti QX56, 2012 года, 405 лс, 100000 км, полный привод, АКПП",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$9ViCuO9DXvxbnw.ttkr8P.3MjvqrI5inpRrk9IUmunXn.NGO93T6.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$M6X7b8U5KeKIGgGb0o4Wq.v.Fw0lmlvS0oqGDL0mgWIEloeV0C0SK.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$uNZqZ3jvTrzexEBINVKqzuOdJNEI44m4xCY038AaqTWZqDm2KjBa.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$j0pD9bV1n6O.HFampXNH.OBdQnDCDvvZLoo6eJvQ0m4EfLGD.dxcq.jpeg"
  ]
 },
 {
  "lot_id": "7230080",
  "title": "BMW 3 серии, 1996 года, 102 лс, 350000 км",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$w2iwtNwQcMUl8oy5eeZNV.AjHfc.EXOInneUATiOiJWMfbuTJpopu.jpeg"
  ]
 },
 {
  "lot_id": "7221086",
  "title": "Автомобиль легковой, марка: ШКОДА , модель: ЙЕТИ, VIN: XW8LB25L0CH700200, гос. рег. номер: У260МТ48, год изготовления: 2",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$vnLeQq4LBAUmEwXdL4ObteFP17.qH.8EUt8YsKUkh21dCYGs6x4.a.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$QHGg7.Lz6f33oamC1xQbkuWgVt0yBud8YQ1YicCdxtlJBD0fFGUK2.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Dlx8uFMIdbhvk2ohBO.IbOv4aoqjbz6ZCjxtWwOdU0Ul0aaLcRKza.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$jpEItWPA5.BunpInsEK5QurAcaAue4t6q6FgT1qLkWcM4nccmO.png"
  ]
 },
 {
  "lot_id": "7226473",
  "title": "Транспортное средство БМВ X5 XDRIVE40D (вид собственности: индивидуальная, VIN...",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$rAH9FEFV5MudYBbtLDgoAuLWPmsb9wjjemVl..Rf8uwqJAbpyFQLW.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$SFMPwMoJDIU6cOehHL9PM.uB9Srsaxra.XxfRq4ReZZN.ZcBOmEya.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$03iqjZbBA8gmoSZClv8e7eIYlMyr6QeqYqnbCmRH3XiJUr46gdWm.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$PM9dT48AH8EXhaR0m0os4eNF5l6Y7CXW6kkMq3DC3ZKR3JfofK.FW.png"
  ]
 },
 {
  "lot_id": "7227943",
  "title": "Автомобиль марки: МЕРСЕДЕС-БЕНЦ ML320 BLUEГод выпуска:2008Государственный регистрационныйзнак: У663СН790Идентификационны",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$dPZqlHN3YQU8qVjBhoUqjuBwOd.QJNOHNITvKZkWki5hrMKVPoVvu.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$dEHBn2IPzHoDVnsr3.PVG.TZFXIg.LIma1wRPCPQsBpFRAF7DZoN6.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$hKHvRcT6bG1SApYmsYqwCOsuHPBGgbq57pu5WBPTTbMc4ToXu0u.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$moTEGaLLZ7ICCWm0UayfeegUsVSLuSCInft8udvtKXn3EnYLjVaK.png"
  ]
 },
 {
  "lot_id": "7208960",
  "title": "ПЕЖО 308, 2012 в залоге АО «Авто Финанс Банк»",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$p7QnaUEDrEwloY9CmedteGhm9SlExBWZZc.okauKz52aUjSR9m.6.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$w4LAnn0BmtJfQkCp5WF4uc0rMo33m5lodFmMhYfaWfLEWXr4CBC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$tH7jbuJ5yv9NYkTOeDT.NlpxFU9mQl15BN4zl0OnIYj132vqSuG.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$J.pB5LvPN9RTo3XBCjHDHetajqLZyQC6XgBCUM..UhkAu82pz.5zu.jpeg"
  ]
 },
 {
  "lot_id": "7212763",
  "title": "транспортное средство",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$05oaJ4VxhiNEIus8kPltRucBGysRwNgXiBr5GjZIAoBXFCTRimnya.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$0b7XHtuFN13gRgLF3x.7S.jl6f4Dv.jh1VGPpISoT7mmnwk9tE2.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$a9HRQv79kiAuBW0HduGRcOxQ7Wg41jmLIxfG1OodPZFL0Dj8HMhhm.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$C9QGk0X1IPRZgU3xha6YsOB3jEprtmVvOiiuUXXLaqLyLsGkpUHq.png"
  ]
 },
 {
  "lot_id": "7210310",
  "title": "Skoda Rapid, 2018 года, 110 лс",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$NIPpBErgX05rtjoQlzk1eFoZblucLpSo1glKAXg9ASbxey07A..jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$3C0rNbDj0BnFfPJUxtgVuiUejp3e92koYQ5aGZbjd84Rr0iosUuC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$dGBzf06Ip.OjFFU.V86juqBi3ZaKdzpPZijPo9iTbN4IFcYAQ5G.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$HaY19xwirvrYHzqq65QZ6OBMCBInwvYTbNe5bR3aCFM1jvpF4PJiK.png"
  ]
 },
 {
  "lot_id": "7167329",
  "title": "Автомобиль KIA JD (CEED) 2013 г.в., VIN: XWEHN512AD0004068",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$fWCbwkR2YW031nk1iWdYaOOlbgXhVC1dQzWSamYuELVy8nFQT2hPa.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$iq4QmydL1GZebd9Ipco6eVahU4fuuMBM.vlFUx0rukZ7bXOeSO.C.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$gV83nPlS4GECNtWw9CmwGeYM2AKHoY4JZ00KOx5zhJEXWuaSIqr3..png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$n9GzX.zELBiPXCyMaqM0I.Qo7eE8bGVEpkAHVEzhhRIJGW3kjCju.png"
  ]
 },
 {
  "lot_id": "7192922",
  "title": "Opel Astra, 2006 года, 105 лс, 304171 км",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$nHQlZX9GiDaXPAFkOftceXK9n5yJm1gsid4ukV.03YIjbTfaQ2ZO.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$YTrHAFE10SFZEg3GQgePcup3FbzMYOnoWCSE667rqwMFQhAmy3C.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$v5HjoymmtzKrZSKS1I1QueGjFGq4lbUqzTjG.n1fhPmlqLMrreZW.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$oQhnz2P6atFAhtcmIPrLOdboXPHzLfkk6J0XB8oWVGAIn1lub2..jpeg"
  ]
 },
 {
  "lot_id": "7226548",
  "title": "Легковой автомобиль марки: JAGUAR, модель: X-Type, год выпуска: 2009 г., кузов №: SAJAE51349BJ58923, идентификационный н",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$S1mmPeYJsPQXf0bn29KSve00JSFEurv0w4eEYF2GlxkkPea.3kJRK.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ht.r9GOn4fGuHde1BnGJOJaRHXEIwQLsr5.IPVnNCfyxcIdyb2iG.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$4tBeuSx2iy7ohjNAVPP8.tfWMNQMmLydI2K9ko4uLRLcxGeLtpGO.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$jPKPwh6PIs6e4ZtSa5NcjujtJRBMOl8DDkUKFTn3n0NNuCpohQ4C.jpeg"
  ]
 },
 {
  "lot_id": "7160714",
  "title": "Легковой автомобиль марки: HONDA, модель: PILOT, год выпуска: 2008г., идентификационный номер (VIN): 5FNYF48409B404773 (",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$hiYJWjAEvLOBZKqU6DwgYusSZdFqL4JXmQbm9IJNovnbNsTclzy6.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$74PoVqaOoZh4oRLWSyFtuWs1lenhSmGoT8rHINwLXqBvXxBhRo1W.jpeg"
  ]
 },
 {
  "lot_id": "7225620",
  "title": "транспортное средство: ШЕВРОЛЕ ЛАЧЕТТИ, Идентификационный номер (VIN номер): KL1NF356J7K723093, Год изготовления: 2007 г",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$lDVIYBEiVeXz4mQQ9UF3Y.6vOpngJQZUpUPv8713hWhtV1l3HlfW.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$VAQ696g7GlwSkvP.BP1OYewWuZShURJViDG8tMt4.jMZ2A4gVskFW.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$swoMU6gdSxfocGiuREyweu2kpzGwG1wldQUiwH6bBykukCYOVgce.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$2mRAXL3IIFn8p3i2mF5hpunN73s7cuGLkhIuhjQNpqjH2pCGFkzzS.jpg"
  ]
 },
 {
  "lot_id": "7175452",
  "title": "Автомобиль: марки ШЕВРОЛЕ КРУЗ, год выпуска: 2012, идентификационный номер (VIN): XUFJA696JC3050821, цвет кузова: черный",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$OC6S0UU0fwORTnMmCYtePa04KXxfmeupc21jnCrXCEkpWOd5jPy.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$jRBMRa7pHBhQPcJWLSm09OYhZ22ivDg0WDi.JVh4u7TCkILMZQ9zW.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Lf1M8sfOs4GvjqzKUiugbeTWi7gRXh8gUIKMTj921JrUZDZyUoDAe.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$b77a9TgXv4kMOzSt1NOeEzMg.uBrX3nXetUDr9e8YRNuqV6zRq.jpeg"
  ]
 },
 {
  "lot_id": "7167330",
  "title": "Автомобиль ХЕНДЭ ТУССОН 2.0 GLS 2006 г.в., VIN: KMHJN81BP6U409963",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$eLdp.BDuCWwy7eEa19U.uefgPvOjo6N4tozJqKF8SikAwtCDiU5e.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Akh6KL1gXQX2BtMHSbToguaEUFj58b0orSNPusEAxn5POi1vzs2A..png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Z2hE2xjDJDtzeH9L2QNyyu9Iedn63dYGx0i8XUcLbFc97DAcMDzSu.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$oUSEOtrmI7RLvLTiXOUO9OkSuoqzkPVTTjvcK2PuqmEB.3R.jAzRa.png"
  ]
 },
 {
  "lot_id": "7232464",
  "title": "Audi A6, 1998 года, 165 лс, 238102 км",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$bIZtMJMGwuDfn.TRV9K14eIM3Q2oQeVJtGiTu8rdhHu6rCAHP6wS.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$q35EcYKQC9b8McrhUJ1tweFRYby5Jiy4mRZbNdUzb8xh95KuFVmq.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$DloWJFzefGrozdUd7Duuueh6KFHiGMlwLLsY7HOBDKdXaMMVVfZgC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$v2ukNb93Tyg7FWsqZEslTeJNstHpXLVAo8Uh63yB194OLiiMSaC0..jpeg"
  ]
 },
 {
  "lot_id": "7179366",
  "title": "Автомобиль, марки ФОЛЬКСВАГЕН ПОЛО, 2019 г. в., идентификационный номер (VIN) XW8ZZZ61ZKG031979, номер кузова (кабины) X",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$DbLSDK0lt2vAz.q0YkGYMOkRtWC9vHPACIpYXDDRWxIvaPzx8gf0K.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$pMBKAjZYnDwmMwMxgX64GedqQtIslIOK0ONCWwknSpewB6NI8Iq1S.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$jx4fXvV9GJEjm8hbqKSFesHRtrI90IU.OBC1cLiEUg1Ye0Bk1ES.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$z8F2bYFonqPmMoulnyPo.GROCr2Sz9nR0KuBgXgEF8WYfekr4h0..jpeg"
  ]
 },
 {
  "lot_id": "7219863",
  "title": "Повторные торги по реализации имущества Бугаева А.В. Лот №2",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$pF6Se49CZteSg8FT9CljH.dANljrHHoeoOVoegho3LyQYuMiRGC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$4SUWVpCkk55j2mpwb1N6OOHVr5pytVR7nkb3jp37lie77rEQQGtCe.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Y5ylHTKMWTaEgqK80kW94udbRR7YfuVxhMgMM8F.F.LOGSAxfWuIa.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$H5z1WT5QAQ6z5VBCnNMI2.EedniEVGz7h1FJ41vbtFSs7rMu.3GJW.jpeg"
  ]
 },
 {
  "lot_id": "7223704",
  "title": "Транспортное средство Ситроен С4 2011 г.в., WIN: Z8TNC5FS0BM500953 Лот №1",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$BaRPA1huOK.Lbw3uzRBVvOGxIwFDm7i9p7b2bmoTqAItyDMVViMtm.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Ula5CVA0gvVTl85zXh7eGuv3XSaZ62bcRjwBu0ltreBcclEZMKh2a.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$OstBHxJ3UbeffzFxfGus.caXRtb1dps9Op4.2jxPS0l1qMIHGH0q.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$w62ndyM8JzxiBGrFAbE21OVKEUZRTBoLJluB0S930luR2W23NEQLC.jpeg"
  ]
 },
 {
  "lot_id": "7136898",
  "title": "Автомобиль RENAULT DUSTER, г/в 2014, г/н О 061 РМ 163, VIN Х7LHSRDJD51434935, автошина Nokian Nordman S 2 SUV R16 215/65",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$m9IIScQAZ37KaipaGbUYjeqZxEvKj9OhrkW50IT2zBPcbyGdo3VUm.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$gXJkcycxriNpkH4JDXkeyMCikFqRNLb6kd7Bl51IVhnhvH.0Ry.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$zjnQ4RMYXDxF88xrHb8be.ZdtDkcBR.IZwnWJKUPVjooieiyJBV2.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$VEZpL.FHvgh7x70Wa7doO6wTjqMFW3ruXzDCc50Pb8KMdgSq1nu.jpg"
  ]
 },
 {
  "lot_id": "7149760",
  "title": "Легковой автомобиль марки: SSANG YONG, модель: Kyron II, год выпуска: 2011 г., № шасси (рамы): KPTSOA1KSBP142776, кузов ",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ssmaevIUKvjpZqeMHKFHeuRPscWMr3Ig4W72BUifvXh8klqK1GW9S.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$774BWg.gx3gqD.fUhLUcc.20xmYwEGTZO5c4wky83dZI2K46hWEoW.jpeg"
  ]
 },
 {
  "lot_id": "7233531",
  "title": "Легковой автомобиль OPEL Astra (A-H/NB), год изготовления – 2010 г.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$EFeINN8BvTWCMBi9hPcORamAImYCoHpW87AjcU4ZPqreJXncaq.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$vO.42ATY5RdhJVpoRX.cM.mv4xsa2jTawI5osG7bKi0re54HVzOy.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$.MZwcKAPic0NDxpu5au9reU1F5BL93WxYnp26HeiGe7hIURQdlzhO.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$fJW7ku2TW8rZfZOtmhbr4eBoyR.Kj5q65V6QiKHAnWQffU3Ywq3G.jpeg"
  ]
 },
 {
  "lot_id": "7219081",
  "title": "Транспортное средство",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$rMWpk4JFjaPVtCXc6JNrmekCMHURwVuXiYcNgkOwVCluDjZ42R292.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$cDEgg3DhPtZltptxwVPHEeFDBOpVt22SWpgTcEyQUOtNiPXPwqh4K.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$.CXxIRhUTZsn7wCsxv6eICcR6Hnlmx498sOJlmWKlfzf4I11Pa.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$uGVqXtnEzO.ZuHbda5D6.utOOxgQCCMMqrfwFgmhrMlTrLNGHQGr2.jpeg"
  ]
 },
 {
  "lot_id": "7219814",
  "title": "Транспортное средство: Автомобиль SKODA OCTAVIA, VIN: XW8AN2NE8LH017757, ГРЗ А508BT 761, 2019 года выпуска\n\nС имуществом",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$YDV9sZ0498vUUvpJd48KaufIwY7kMYiUTSBUCiMR9XoTvWWhVhE6S.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$GNx1o2pdiC1OZO6hBpM1QuFKxdN45NAWi6b3XVUfv58.LdA3RDoW.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Bj4fEwIXsZG9UltO4CRODf80b8j7z7PA3pVnrzoKflPq2CFn1u.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$oVUwRGAyD9qcIiHqYVyFfec5jChI.X8ZfjsDQ0vdrxlbU17Vy4Mm.jpeg"
  ]
 }
]
```
