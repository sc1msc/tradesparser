# Задание: проверка фото подозрительно дешёвых лотов

Это разовое задание для облачной сессии Claude Code. Код репозитория менять не нужно.
Результат - файл `damage_results.json` в корне этой ветки (`damage-check`), закоммиченный и отправленный (push) в неё же.

## Что сделать

Для каждого из 40 лотов ниже (список - в конце файла, JSON):

1. Скачать его фото во временную папку (например `/tmp/p/`). В ссылках есть символы `$`, поэтому в shell ссылку
   ВСЕГДА брать в одинарные кавычки:
   `curl -sS -L -o /tmp/p/<lot_id>_1.jpg '<url>' -w '%{http_code}
'`
   Если сайт отвечает 502/503/504 или обрывает соединение - повторить до 3 раз с паузой 5 секунд
   (`sleep 5`): в прошлый раз сайт торгов отвечал так на часть фото. 404 - не повторять.
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

Сюда же включены лоты, которые в прошлый раз получили «unclear» - посмотри их заново.

```json
[
 {
  "lot_id": "7232666",
  "title": "Публичное предложение по реализации имущества Альдеева А.В.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$f2geyeoUelTkO8700bmImeRva9WQYfrf5jFmEY5xUiE9YlPNtcQ.G.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Y1TFwmYYJFxhyRjc6wjly.YEebrzVyzGvgFu7ljesld9ZLsTC0O.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$BW0Kjv1E0l462tDqzAEeduxO1Uro5SgQt31cvpn2OJUazirpo10q.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$tHSwzoHcuVHcJGA488KBuuuLXbbqjEHcsh0hBrNyb8NMK7oad6.K.jpg"
  ]
 },
 {
  "lot_id": "7220427",
  "title": "автомобиль легковой Volkswagen Polo, VIN: XW8ZZZ61ZKG023768",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$p4dydTumdg41YucMuRZzOMZc5MmtLrVQnF2R.2bbj3vpyxh6g3e.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$z8kzvZTBDg8DKHH2y2TYAOximZBk2jyWkE4NcxbvTl3YtmBfVN8Qi.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$o.QhbDjNtzpJmYJlBJVAe5ozxiG3HQWOSr76Y.FUEKcSgoB5uy.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$gRXRIhdSiMLq8XylsRpOfYWE7r7Au2JbtjVdJn6MScV297Eoce.jpeg"
  ]
 },
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
  "lot_id": "7187382",
  "title": "ВАЗ модель LADA LARGUS,  (VIN)  - XTARS045LK1130807",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ZNfDfc6pRFOUmmj2V4zM3e1cx2SXq3vJO0QBmq7uQkSWfY1GHVTTK.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$3nLeKPIMwAUTrD1HSv6AgefHSEWqo9wPlrKTPnWGwWJeaDpQjk9F6.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$cPTxjPXx64pxqO51hkZWOeIJL0uhE1fz.lVJxZdMUdtEAVtbQRpO.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$UFPUXnfWY0NYU6B.egoi5.omAiJ0idLXWsrtHY40EX8lGXq1CeMO.jpeg"
  ]
 },
 {
  "lot_id": "7186033",
  "title": "Автомобиль",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ycwLpc5I3lwuX1zOVtabxeVqSWowXlv58VGAAH62a9JXROI2YdSXO.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$K22tYXQD8sxYNl2V5ibw5eoiz952oifjuqiC7fj2p97FGCsZY9cu..png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$XfI4xTdsxCF.MrmIIcCNNO8ML4D6KQ0zIdGdDN2lwd8k7gwwt8n1a.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$nzoF6J349xYhzzoGvogaOe931QMZAdmz0D7N41p41jxHaHRCsPfS.png"
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
  "lot_id": "7228828",
  "title": "Renault Duster, 2012 года, 90 лс",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$iYq7wT1YHWT3kwoWTj9DE.4aTC5vhUdgNQ1o2Q0Yy4OSoHLWGu.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$XNDtOWr5InehvGG6OuSfYecP0FAVUFu6uhf6A3vmNkiqrUFQDYtFi.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$EdMT4RJReHVgjqZ66cW10.71rsOyJx.E1cRk7qEu7CzEtWaubu.7O.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$sItoa2sI5Yyrpyso3cBIUef13tuPhtUdSos63ILDJonEA5YjJ6nhC.jpeg"
  ]
 },
 {
  "lot_id": "7179675",
  "title": "Торги по продаже имущества Должника: Елкиной Любови Юрьевны",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$46Ip.Yu1gsw2PERFcOGYQ.ZcHTBfEeoAsN1zjN7Zx3Ld2mlc4HNbe.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$rcrhb5cDcgCBEaROnYyiew46RnPPubBRLCoN0Vxd7TPHCDyZ.6C.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$bzmSNmwEekKa1a9smYiKO6.uV4wzCamjUyzaxGI91Fsdvx6G5y.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$w1kYHcgOszZEeS3DuK9q.TqXq9gBItyARxqFpHPmSGqdkGf26ojK.jpeg"
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
  "lot_id": "7230080",
  "title": "BMW 3 серии, 1996 года, 102 лс, 350000 км",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$w2iwtNwQcMUl8oy5eeZNV.AjHfc.EXOInneUATiOiJWMfbuTJpopu.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$cQlymiEgLIL81F.AbAKx8OzQdD1sRN66.x.d1pvsDK48rEysgWntC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$tr1YnwNkuXAXSYEV4fciP.51SzfoDFOXsteXl6Id0ckJwQJw0dTLC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$eTeJdUp5G9d.oTEKMa67eHfUoRhGd7Ppjv8hUddQBciMoVKZbB0K.jpeg"
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
  "lot_id": "7152048",
  "title": "Электронные торги- публичное предложение по продаже имущества Бернацкой Л.А.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$iMMfRgZ3T.QjVHVcoRXpY.OURpm46xTAwUsjCAFKA0FR5N9C9Nrca.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ao96By0GSDPyuK9se3zDW.B8i1zTOZkgC8e44hpS9gLIrpzQ9kay.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$deeQOFPp5tlE0XZIJTnxCOu6PuwNePm2pL2Amj8kkWaVyTiBNoWFK.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$20HIJTipv.Xu7D25eoLvT.0qIB6Q3c.fNho125mHBcdAGzl051he.jpeg"
  ]
 },
 {
  "lot_id": "7229645",
  "title": "Бегахмедова Ф.М. Автомобиль ПЕЖО 308",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$KsB7R44ziKC8S7zeq9vtAuByUv.0Po6bhylHfv.6UAR9YpzigX6.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$E6xJss.OgEGE1SCqA0JAEO1B1MXY4UMXcmCsLD0Y9tc7EdOXZHW.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Jtg4p78Z9av2W8oKty0FOb0cewH1chG.8GTxznHDEfsUW9EXtwDC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$6XzEz1fDrABswQ1tCEby2uCLmaFyg2JBaRrG1N7Km9GItLwc7ycFW.jpeg"
  ]
 },
 {
  "lot_id": "7195602",
  "title": "Транспортное средство: Автомобиль Пежо 308, VIN - VF34H5FWF55402964, 2009 г.в.,зарегистрированный за супругой должника – Турковой Ириной Владимировной.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$8vxVHwDw9BmxeEkND3ucmOdv2lq2XGgNz39ZjRpSwAnzLewc9dwFu.webp",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$gGnS8KmPTgvXADju2nioutguahRF7.KeDG5IRU8A9QT.z85zg7u.webp",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$10NGqe62Xge0aGpb8kEUTeK6qJaXhYhC5H7UG2Sr1bstPwHFSo4jW.webp",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$24zc.A06Rgpyg9e6efnnEeWsATmB1Kmqgis1f8exZ6VxzFgt3k8LG.webp"
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
  "lot_id": "7221030",
  "title": "Автотранспортного средства ТОЙОТА ЯРИС, 2008 года выпуска, WIN: JTBT923184027174, гос. № Т339РМ77",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$GXiKEzpkvlUkGNCyeHqW3uErjYu4kiZ6KKHZiXSWqN3Lrxy3xseI6.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$4vyI1LF1dykgxqATU9POpuAUvaX5r1A3hmLSbg5RZzBBec.H8TKzi.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$I3e7F2h8X2ScgYfcrYh3O4OV8q29ptqVCUbDjiY2.QN01yB6rtOG.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$c7XxLyM1KCB6Yxz4heNMrOlskjTs03.SyjiV2P8nNeiLrTSHjyiIW.png"
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
  "lot_id": "7227466",
  "title": "Легковой автомобиль марки: NISSAN, модель: PRIMERA 1.6 ELEGANCE, год выпуска: 2006 г., идентификационный номер (VIN): SJNBAAP12U2302265.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$QWozXAkVHLhcD2FsRJP00ON.7rB3sAYIBwhuXqKUgPLlFYjolC1km.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$nv7BeBPUX8sCddwSdaefD.sY0rUpuoVTvrVRBaSrVTkaIXwf6eA2.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$6lZv1lrHgeqs6qc46SYuKOFD2vjTvLljYqObVS3IO.PonudMSTwCC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$9roajjzJzqEz11vEwVYMF.0nKkRUzy7OZxtSKuUyMIA8aJW1pdVr2.jpeg"
  ]
 },
 {
  "lot_id": "7225620",
  "title": "транспортное средство: ШЕВРОЛЕ ЛАЧЕТТИ, Идентификационный номер (VIN номер): KL1NF356J7K723093, Год изготовления: 2007 гос.номер Т206КЕ05",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$lDVIYBEiVeXz4mQQ9UF3Y.6vOpngJQZUpUPv8713hWhtV1l3HlfW.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$VAQ696g7GlwSkvP.BP1OYewWuZShURJViDG8tMt4.jMZ2A4gVskFW.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$swoMU6gdSxfocGiuREyweu2kpzGwG1wldQUiwH6bBykukCYOVgce.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$2mRAXL3IIFn8p3i2mF5hpunN73s7cuGLkhIuhjQNpqjH2pCGFkzzS.jpg"
  ]
 },
 {
  "lot_id": "7175452",
  "title": "Автомобиль: марки ШЕВРОЛЕ КРУЗ, год выпуска: 2012, идентификационный номер (VIN): XUFJA696JC3050821, цвет кузова: черный, модель, кузов номер: XUFJA696JC3050821, гос. регистрационный номер: Е099МО777, Москва, Зеленоград, д. 3, стр. 1",
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
  "lot_id": "7229452",
  "title": "Легковой автомобиль, ЛАДА 111930 КАЛИНА, 2012 г.в., VIN: XTA111930C0219558.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$15Km.Q8Uz77d85wrJlsgIuOSsZ9cGxNmyLqwriWTwGPK7EtATKn0..png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$5CDpcjLtWnqSEgkY1ts.TujLVMIfkHI9..x4UWavL0lfz5NIS2Se.png"
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
  "lot_id": "7070431",
  "title": "Автомобиль марки FORD модель FOCUS 2007 г.в. VIN-номер WF04XXWPD47U32455",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$GTZERtgC4MtPTTvDTcPkpOO3D.61hjcxtwBImIvatyvM3y9A2eYy.jpeg"
  ]
 },
 {
  "lot_id": "7160721",
  "title": "Легковой автомобиль марки: HONDA, модель: Civic, год выпуска: 2008г., идентификационный номер (VIN): SHHFK28808U037082",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$fW8SPA81pRM7MyzuxK8TeOswgbdEZBriMo0A5on1pwUHy9WMZ.BVq.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$G9uOcNb5gQD0ZQyakEfDE.14jwB.VHcr8s.eg4V6U90tX.aypiVC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$wvwJXoJAUFvaR0WnZ1qwXeQAd9V65OSV0UitM7zpNlp.mk0GeLz6m.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$kR3FdWkKl7O7ndnoyrYCIujwfqc.rTJZYlH0P2Ymau8AID6FgFam.jpeg"
  ]
 },
 {
  "lot_id": "7198560",
  "title": "Автомобиль УАЗ Patriot",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$RynbFDsDQ62uSVcHu694beemxpGZ2shJEsUg8Gy4K5x.tcL84iLSG.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$HUmFnr6B6lBYQYsTULPTSOEU5J51BuEssnb9iMzyEA8t4kfDVOf6.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$cL4hUlSu6s1IOuxVT42eY.eCIc.Rc.Z6rByZqrOwQqiBSV2j9jH76.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$.mfHeU6jMe7tND4s4Gd93Ol9ILCpX2uiyI6IjI5..oDUg6YsHDwe.jpg"
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
  "lot_id": "7164389",
  "title": "SsangYong Rexton, 2012 года, 186 лс, полный привод, АКПП",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ZsFBzmUV9PXoA1HAfjkuSunyWiV9FedOXxyYS9pzmi3b9N2tbsAiC.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$OhBfrMGhWcVF303ZlzggujFurX.FQw2.thwOJd0S.RQ2XHgbe.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ZTK2X4UnKtJNuw3.pTffP.dFFInxB.fb44OW7oIuj0JV9l8529NG.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$1URAWvkb2CwxO0NrYXxFKe41J1DOVYIOJl4U1LcaWMwlsdHlxv9FO.png"
  ]
 },
 {
  "lot_id": "7218629",
  "title": "Hyundai Accent, 2006 года, 75 лс, 250000 км",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$iHFbvBmCJndNZkvd1fLxxeJcGWCyW358Ab9qi2hUlzHk4MTcj.Lcm.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$IkBHCDRb06plR5CBNbBXluVjJH1oWsnmu5Thhg9J7InBMgmQIW0Ze.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$WigBejqDbLww0ylTzKNUN.Exjt1.B6Zh6bAH1yJ7wtLOwSbGzfAEm.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$n3D8rXvi2MyIJ.Zf0.FEdugPzvpKyIIYaxJm6yGzs6RMY5DsTgEG.jpeg"
  ]
 },
 {
  "lot_id": "7186432",
  "title": "Право (требование) к ПАО «ЛК «ЕВРОПЛАН» ОГРН 1177746637584 (Лизингодатель)1 на получение в собственность Предмета лизинга по договору финансовой аренды (лизинга) №2638351-ФЛ/ОРК01-21 от 06.04.2021, а именно: Марка, модель ТС: Lada Largus, Идентификационный номер (VIN): XTAKS035LM1365730, Модель, №двигателя: –, № 11189 4545570, Шасси (рама): отсутствует, Кузов №: XTAKS035LM1365730, ГРЗ: А779УА799.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$qZISvjgL82sFgZxYiKVduKhiNAkDtqc6B0Na4O.rJv9nQTFLBhq.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$q6MD1TjgJD1nrPasOYJlBuLd6Wt84XhAPKAPxa5Ya3P7nPdmMBIy.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$VqyaMLfdKpfXEU.i98HAuBpTIuPatZe4By3U2WDduwBcPUHFd36.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$MErhsOVao6vMgGe5yNVdpexXYvmlgTRe2t2o4sAeC9vxUQUijK0a.png"
  ]
 },
 {
  "lot_id": "7149760",
  "title": "Легковой автомобиль марки: SSANG YONG, модель: Kyron II, год выпуска: 2011 г., № шасси (рамы): KPTSOA1KSBP142776, кузов №: Z8US0A1KSB0011925, идентификационный номер (VIN): Z8US0A1KSB0011925. В залоге у ПАО «Совкомбанк».",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ssmaevIUKvjpZqeMHKFHeuRPscWMr3Ig4W72BUifvXh8klqK1GW9S.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$774BWg.gx3gqD.fUhLUcc.20xmYwEGTZO5c4wky83dZI2K46hWEoW.jpeg"
  ]
 },
 {
  "lot_id": "7157450",
  "title": "Volvo S60, 2013 года, 180 лс, 168761 км, АКПП",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$DxPZfDCT6GL8OCuMMv.qBeI0CkColcsNk5PfcaC6BM11Fotamhpq.jpeg"
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
  "lot_id": "7199338",
  "title": "Volkswagen Polo, 2011 года, 105 лс, 250000 км",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$VXFki4UGp0Xgi.7f7pcHuIImOvCYmuhqLKfEHn0CmoXPx7Xdpc2..png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$bTKOIW7Juw0v3.PlP900ul0SvQou0ndxqWyxqVQYbAt7UzravVDG.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$X.S4s8TJ25ek46gO4t4XOuyAVZOMXIWd8qSraBE.CncdRkSUf2tu.png"
  ]
 },
 {
  "lot_id": "7182272",
  "title": "Автомобиль марки NISSAN модель Almera 2016 г.в. VIN-номер Z8NAJL10055242528",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$3zexZBsdeKTba2qPMfAHMuWBUVX6HIPTzvUerUYZXCHJ4xj4ykma.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$C41yt7dVu9Yx6BapvCXKUuamQzdpYx40R.B95oYaHQQ2VXfumQeDy.jpeg"
  ]
 },
 {
  "lot_id": "7227943",
  "title": "Автомобиль марки: МЕРСЕДЕС-БЕНЦ ML320 BLUEГод выпуска:2008Государственный регистрационныйзнак: У663СН790Идентификационный номер:4JGBB25E29A489426Тип ТС: Легковой универсалШасси (рама) №: отсутствуетКузов: 4JGBB25E29A489426Цвет кузова: КрасныйРазрешенная максимальная масса, кг:2830Масса без нагрузки, кг: 2256",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$dPZqlHN3YQU8qVjBhoUqjuBwOd.QJNOHNITvKZkWki5hrMKVPoVvu.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$dEHBn2IPzHoDVnsr3.PVG.TZFXIg.LIma1wRPCPQsBpFRAF7DZoN6.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$hKHvRcT6bG1SApYmsYqwCOsuHPBGgbq57pu5WBPTTbMc4ToXu0u.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$moTEGaLLZ7ICCWm0UayfeegUsVSLuSCInft8udvtKXn3EnYLjVaK.png"
  ]
 },
 {
  "lot_id": "7136898",
  "title": "Автомобиль RENAULT DUSTER, г/в 2014, г/н О 061 РМ 163, VIN Х7LHSRDJD51434935, автошина Nokian Nordman S 2 SUV R16 215/65 (4 шт.) (г. Москва).",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$m9IIScQAZ37KaipaGbUYjeqZxEvKj9OhrkW50IT2zBPcbyGdo3VUm.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$gXJkcycxriNpkH4JDXkeyMCikFqRNLb6kd7Bl51IVhnhvH.0Ry.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$zjnQ4RMYXDxF88xrHb8be.ZdtDkcBR.IZwnWJKUPVjooieiyJBV2.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$VEZpL.FHvgh7x70Wa7doO6wTjqMFW3ruXzDCc50Pb8KMdgSq1nu.jpg"
  ]
 }
]
```
