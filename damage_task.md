# Задание: проверка фото подозрительно дешёвых лотов

Это разовое задание для облачной сессии Claude Code. Код репозитория менять не нужно.
Результат - файл `damage_results.json` в корне этой ветки (`damage-check`), закоммиченный и отправленный (push) в неё же.

## Что сделать

Для каждого из 43 лотов ниже (список - в конце файла, JSON):

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
  "lot_id": "7227636",
  "title": "транспортное средство – легковой автомобиль марка – BMW 523I, год выпуска – 2010, VIN – WBAFP31020C256349, цвет – темно-",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Q54t4cJxRjax6Thmkpmq.PpLKKGkIUZ69XcU7VppNj6S.y2dlpsi.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ymIu3rUGki8LlNUDbPHSu1RyLqUkzrLO7Eu.iaNn619gCIXTcmS.png"
  ]
 },
 {
  "lot_id": "7181241",
  "title": "BAIC X35, 2023 года, 136 лс, 180000 км, АКПП",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Ew5HqacwXYvN.A4pmFBC2eg7M4fOgMPQyiViTlsbM14QJJNsCFM7y.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$UjCnRJeqhExbhOkiqdPg1eqG2YCAkdm9ZbggfQqIyWtFaS6g4DFa.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$hK0sDhWZBjLjcsdT8SpqeuihhMupydaS5Ed9ocDc8I3jG3wAOwTS.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$cES27K3DzGmhCQhlRuugOUhx9nDdq6ODc.3uhQU89rGfcE.8UlLy.jpeg"
  ]
 },
 {
  "lot_id": "7191864",
  "title": "Opel Astra, 2011 года, 115 лс, 250000 км",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$acd38xDYXBCapgECxn7a0uIk4BZExdI2cXn4Bb1F4SR80ozA9mh.K.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$XAh4Wk7t4Vz4N8GgCPpteO7mPm9UnMJW9WvBDR6lEvbezixK4pC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Eh7BAThMPDgcfxvckkhu7IvASeuh6i95F4Z1K2XrGeGiFp3eHvG.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$AoIrhnBeP8EPK0wKSpn8QuNAPkFRNGvc8GXKL6wcKXnueOE4TyeC.jpeg"
  ]
 },
 {
  "lot_id": "7190555",
  "title": "ШКОДА OCTAVIA, 2019 г.в., Не на ходу, разукомлектован.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$H7liVlrAk.4r04bdcJVuC3gHp8XKhO.XJ8eHJtzqMdSEB3t7RlK.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$w0oz3O9YMlFptahJoGRhYuql8B77TjF40.SCBAtDyBiRprI7B4KOS.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$lXBAzVO3Odl5ZHL50nKyee27tyA3dDhZqmIBcZ8inrte.VglRhjW6.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$hUCQIFUKeEVd0YWagBSh1Os1epjUZKyylHa.WBAappE09SlvznHL2.jpeg"
  ]
 },
 {
  "lot_id": "6704757",
  "title": "Лот №3: MAZDA BT-50, 2008 г.в., VIN № JMZUN8F128W678742",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$nbbptZts5MC6qDWkubXGIOgKHmLk2DWTJICC8.wZs0zkBGWdSAEG.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$S0IBufZZ9VggDg1MlNi0ugmkwbIix.jn8Fnhz.uPfppsCap.myK.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$FHb5yhEoXWOgEmZIVccGeg9pC7kev46uTXqnmbRq815PguMuNWda.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ntQnDZmcDF0j1Hcqrm2ZHOZN77iPAx6VpBKwjjQC2F8hNGia39W.png"
  ]
 },
 {
  "lot_id": "7173123",
  "title": "Публичное предложение имуществом Максиевой Э.И.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$xRkzTSgaPmBvUCsL0X5XOe74lF7wIe91Y8Lv814SpLKfASIstU.BW.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$1MHAvEBUvxfp.VLCIyQLZew7QHSCprc0gh67nq9Any30eZ0vakmy.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$9R9D9pvzRXwSlg4AvXPNv.vM1gT.PCuI3YlCaXjW8I5l1prTxILgW.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$sYy3vgclYSvULAvCxIio.d2IGZZCzdGerfqj9.nRQzxHRTZ705a.png"
  ]
 },
 {
  "lot_id": "6962706",
  "title": "Транспортное средство: легковой автомобиль BMW 320d xDrive, год выпуска: 2017 г., цвет: белый, идентификационный номер (",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$GvSfb6w1dAL4YWXdVngM.t3BhMTLiPy83LGCjBH2deb5OTfdm1W.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$HWUaygW.WieBIZhzK8a.P9nLkL8K2foxov03BuiZCoH179nADqa.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$.fA9zXkJzp58zvbOXJq2pOii2yO2dxTa77k2Lz6RaaM8INUFBZYC6.jpeg"
  ]
 },
 {
  "lot_id": "7212629",
  "title": "Легковой автомобиль Hyundai Solaris (седан), 2021 г.в., 123 л.с., с пробегом 335 тыс. км.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$GEqm.D7AHrGNTjSXEVWDfOHrBeiTxUDA2Kn8o5njvJkmb4.P3Tu7e.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$GDKg88siHzvghEq.Diq9QO37tCEM2VeesZd7QDk4VTBSYdX21VHC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$l3.WFJh9QRK..Zw2tjVByulCNsxn11b6BQMMygWR0f1aiKILr1yey.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$XvHlckkpAGdVEWcqkspQyejp9PUXL.tbJ4vn8ervVOPKqVwEzkK.jpeg"
  ]
 },
 {
  "lot_id": "7189002",
  "title": "Легковой автомобиль, АУДИ 80, 1988 г.в., VIN: WAUZZZ89ZKA015828.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$CM.YMSGArIjdkBZrX5YE6uuloiRHjAukLSiajqzrJL4qGAu.x2U..png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$EHtH0kW8DiF1NDe4O9LA9OOZQmlWV3dTOE8irkhhk9E5.wsIl.s1C.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$gyhBoXhJk3vhPeOG7buwcuOozBkYiYY9ppiuTWnfeayNXwHqzbhK.png"
  ]
 },
 {
  "lot_id": "7175463",
  "title": "Автомобиль марки TOYOTA COROLLA, 1996 г.в.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$5o8lSKcQNuvEIHQNpOYnr.VjRi5Cd4Jc6R4PLha1wguTPhHKhfxHO.jpeg"
  ]
 },
 {
  "lot_id": "7196337",
  "title": "Заречнев А.Е.: автомобиль ХЭНДЭ СОЛЯРИС, 2012 г.в., VIN Z94CT41CBCR134064. Лот 1.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$itfgISsDMWdrchWitDGreG316l8ifuocnCcqknfQ659zueeWdHp2.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$1Fx6JLqMHIIBVOwsGk4UferRZ0QamMLwYBpdgGykF8kgPbJ5EYQ9K.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$w14R4a1UjZt1mrvyyXk7Bum1NikzL6sIKNapgs0UGC5owZzWT9aqa.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$w6ogYfTn6KB0aPDWL2OzUO4jiwCbjlmg2R9d612ebF4z1yk3OBGi.png"
  ]
 },
 {
  "lot_id": "7199661",
  "title": "Легковой автомобиль, марка: ФИАТ ДОБЛО, модель: 223АХР1А, год изготовления: 2011, VIN:XU3223000BZ309686",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$wKu3kKgvfgHrNBfMFDfQg.FTVp5ztnWDGzC.iHMmO7SxmL0c3rPcS.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$F2rjPIaRbtctZJSrnxgUOlKghRoVG42Uq3F9Q9ix1gFYffkGOdAW.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Iv29fGjM7s1gUXqqtsAHnO.adfvTqOwySEpyQyzlIqcUdVfvgjaxm.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$6kmDewSIiMd51pnzelU2eChOT0wm4eI2RKBO.5t6NzasXb8UIsha.png"
  ]
 },
 {
  "lot_id": "7179956",
  "title": "Автомобиль легковой. ПЕЖО 308, Мощность двигателя (л/с): 120. Государственный регистрационный знак: Е756МТ199. VIN: VF34",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$bGvRPZea5DfJG5r.mmgFuotz20iXThaennUguflnZ67Hor8ddP5m.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Mj3oDRQ0XOD8DmhuHid5uGCP5Z6DrHRzxKFf1xrQpYSdddnoTS.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$VIzp9QZv.OXpF4mgJTyPv.Cm3GPSi8fd3uYrVsnrcDT.mGVhir4pi.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$oQ.mi8WQT5pbIyB5aqRGTOJqNieF7w6etCCsEg14bm1wkqB1xXF8G.jpeg"
  ]
 },
 {
  "lot_id": "7193819",
  "title": "Легковой автомобиль SKODA OCTAVIA, 2011 г.в., VIN: XW8CK41Z3CK256092, кузов № XW8CK41Z3CK256092, цвет ЧЕРНЫЙ, мощность д",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$E1mt7iMqHjXuPCMx5KvKrOK4k1FhwbQWPnNxQ0H.zTQ0xSd655p9q.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$viCKqOZQn65Y1ShA9ZSYel8ecZ3KEUk3I5.xlwdyRZmgLAJL332.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$4kBEFNTqquu9LRr9ukIlLuhcvntqosrcdlQiGEve8ADltAHdSTNK.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$a7Doyf44yywbL5o3OROu3KgBq6GIRIxgaLc3jkQTUgLkVwY76W.jpg"
  ]
 },
 {
  "lot_id": "7188764",
  "title": "Chery IndiS (S18D), 2012 года, 83 лс, 200000 км",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$mfSrDtbwKygYWt.KEVcNzOCDWMYmJwrYHo86dQnxVW2HvHMogC91q.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$IRtg4yqbECNMF6msIgauuqwaqJgMQuXwrlGa8MfuUi2ROHEm3jV..jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$gAQAvB1CcCfP94TuINL0UuUjPNX1dSdpuMlcLKanLGJ6Rnd8qG.jpeg"
  ]
 },
 {
  "lot_id": "7152351",
  "title": "Renault Duster, 2018 года, 109 лс, полный привод",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$M2YuuG9y7r6qyOxKThP3s.jHR2UoNrc53JUHv60Idp7hDsl7NjW4q.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$o32jJjIb0XRBI5rW6UHHbeNjfnWrpxpvXdStKHW8dluHjly.9WZu.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$CxRW4KC1j8I8TEFK4FOPe.HJoPH1kbYnh6e5UTYQqlVoA6CbUnSRe.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$rOXATnYMUdxSCFTFyN3kJOFwWU6MOM29RKYWEpSeKE1OcsKa6Sl02.png"
  ]
 },
 {
  "lot_id": "7195345",
  "title": "Mitsubishi Montero Sport, 2000 года, 177 лс, 209919 км, АКПП",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$DtUiRiVH1CaeL5AaaX98eOwxC6I3gErPQCqIakrXViwVySdossh1i.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$U2.zkQsL4yigmPaNw00d4uIbYtoBNrnANFYoGx9nYiIMgxGt8EGri.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$S9RQVM1AAFHIvKa3uKRFqus0Pl5RU2zTK5IzpZvKReS0aOoOPdAUa.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$IyhLAyRoq844YbfdtKrrYOwVyPQjR.OaUpF310BjhhmB4hJF.AmdO.jpeg"
  ]
 },
 {
  "lot_id": "7185930",
  "title": "Лот №1: автомобиль OPEL ZAFIRA; 2013 г.в.; VIN XWF0AHM75D0003411; цвет СЕРЫЙ. В залоге у ООО ПКО «КА «Северная Столица»\n",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$VJ2wfAYAQWpYoag5G5tpIO7Hxe2p6rzU6os5rLQGQrPfyAW3GMT..jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$glHKI5FeNyNYcs62XsR1qejUNstfduTO9hTHuZdG2l2FCEDEUn9ia.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$KpyRdBVnYrDYBUJLFgJJZ.DCYkm6qfECvmwqBLmZ.B0qrq82ebUKS.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$K3ZfB0rUY5LKe2E.uDEVuKyrDBe4QK79MMPEDeikgsuIpuAM2RLW.jpeg"
  ]
 },
 {
  "lot_id": "7138501",
  "title": "Автомобиль марки AUDI модель А8L 2011 г.в. VIN-номер WAUZZZ4H5CN004471, регистрационный знак M680XA790.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$n95.Pa5Ac4xTy2ZdP2VdYuOrITO5azDCBacn5lFe8TOmvalEEQhYS.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Zp34.KDKNHy8dxcv8ocx3.xGTpiU6vMDNFaE3XgzPdY2JaI1nMkR..jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$k.SfAIVx5QzK51HnZ79l0OPn4oChOHdCXDXRMCFzE0oqVl9aQZa.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$MzyUz9ZWQUuMS4HwCylyduzqcBXCAz3aAiKeMUC8pQvTKrQbulvY6.jpeg"
  ]
 },
 {
  "lot_id": "7210746",
  "title": "Легковой автомобиль, марка/модель: ФОЛЬКСВАГЕН ДЖЕТТА, год изготовления: 2010, регистрационный знак: Т059ТХ197, VIN: XW8",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$r7wsluePjDuJS8Cp12Hf8eYWTOZ7epPJEiu1Avys1vn2jZk0jBi.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$zSEy9g4Fs5bLp3maITvXDOVEM7Hk7Q3IE8D67WxEDzxI3p8Owvx8i.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$AAuAOyPpctJXPetT1s2TZeKehohlrSKia8DeQI.XH05eM3Dg4K.png"
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
  "lot_id": "7221735",
  "title": "Торги должник Котельников М.А. SSANGYOUNG KYRON, год выпуска: 2013, залог Банк ВТБ.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$14o05KGyQjOg1f3olORpLu1RqBJXQ7wWPmwPuwJ2A0Jb.pgdAtRpu.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$MlN8MIIlG3E7ttKoakqHt.eB1SQ6Szvx.isAduAE7ntw3ObNJ4zk..png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$9BPgQ0IG1Oa.EBOcneBJhuoOyMRgDPBih.Rd1Sxu8Y2JRRZ8bhKkm.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$MUvzl94FS9s33wLwmoaROJKhPOYXeO0Z77wTU8TIzjtQKTyk5Z8O.png"
  ]
 },
 {
  "lot_id": "7181114",
  "title": "Kia Spectra, 2008 года, 101,5 лс, 128773 км, АКПП",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$PLQddLDLvAxd9aqgNm9jPegBrFAXO.zNaJq8UepShAj9sNSAaVnfK.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$7g24mEls4FD7lt2hsu0qemrpmenNc.OgmYwAPhVmm9H1P4WLhUq.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ngiVYz60PGthzn2U9esyXOLoDFo7pGf6rcusU6Q85P5sL5ueSJRVm.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$i3nwV0tMZTjskF.xyi66g.zbISmg0.wzmNdnbW6rfMIdmvmV9BO.jpeg"
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
  "lot_id": "7181933",
  "title": "Chevrolet Cruze, 2012 года, 109 лс, АКПП",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$4r2ZvC9T5OLrj7WPeuUW4OXGOyMF7JmFtXd73VRdjBOiPFwdFPcT..jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$bOgx1h6F2GeRAD7zHDVFI.JSPbQTJnO8.Ki7eWxgJDtRrrqeV5cO.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$p6parEsrLBj8j2cdgj7IR.7.l8MbMXaTR3lIKz9ltlmNeKFSUQSYG.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$.jeS9kKS1a1icnP0PaF7OoIJ1P7bcPIIaMiSxt85yFuaruf0r.H..jpeg"
  ]
 },
 {
  "lot_id": "7196557",
  "title": "Транспортное средство",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Xkvb1d4GEvE1lYvVJqxPAO0MHZwayzcQqfX0xCIsPUyYOkidwmHCO.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$KWALCrl4RPTdjITuNWiCuO.Mg7AyfE7fT0C6twbaHAa96twlBj7m.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$1qbK1HhNhBz7XFb0iwcROiG0.PQpHwJYtPK0S8ZyU.Ola4w052S.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$wbh9onPW4L7EFiffa8H3e5E6iXLOLxVSzLCeCSxgr.DgLQaemrqm.jpeg"
  ]
 },
 {
  "lot_id": "7073272",
  "title": "Автомобиль марки PEUGEOT модель 301 2013 г.в. VIN-номер VF3DDHMY0DJ716632",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ebCOJSrzpzeRfu9ssLxLyepSMKNIigeeRJmXtw1j72GjHbYP09gCy.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$zOfsDleUre0ewpXD33wUC..zekDtPRbbjH9nrFsPmqyuv4Yi4dO.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$emysRrBYoRWp40.y..la..FPf6UEpsPtrcn40Q71h.NK3usvJc7jm.jpeg"
  ]
 },
 {
  "lot_id": "7200122",
  "title": "Автомобиль легковой, марка: LADA 217230, модель: LADA \nPRIORA, VIN: XTA21723080040624, гос. рег. номер: \nУ386ЕР790, год ",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$c5DUv74ctVLTg2r.U1Vub.WOrHrVN2GWWKy8aNacHCQrglllQTBle.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$8rw36rCBalnHCZNe7yRWm.38uJ4LCerX4NkTBix2OQsmavFQbhs8W.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ZBnlVuno6ptkDf7rS8LcHOeaSxB.PfTwRboEPUlBzgIeiI9eS9fyS.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$AuxlpfNjxTruQk7eMwG2.qhejo5YPgRwcyyWbvCy6QlxHszl95O.png"
  ]
 },
 {
  "lot_id": "7069618",
  "title": "Легковой автомобиль марки: MITSUBISHI, модель: Lancer, год выпуска: 2008 г., кузов №: JMBSRCY2A8U007540, идентификационн",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$rSQGx.W6MPmJIZ9CV6JEZeL6DBfvu7CwNBhmB4asGCRBdisPRJS4e.jpeg"
  ]
 },
 {
  "lot_id": "7134732",
  "title": "легковой автомобиль UAZ Piskup, 2020 г.в., ХТТ236320М1000318",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$OxePsQELvT2s92cGDm.8GeHQpskHSMmreuVT7pkAq7jqsPRU8mrC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ynNQgXLzOs6bB3JtrDUeHePKI3jgvZqWgZ3JlHcUXypmyO.wFmRbS.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$5zwj2e80HjWpOG23Nd5sUeVgY3o87qty9SXOWPZGKZ.iNYcSDlk3G.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$BwrI16BmYilLkiM3BvZO.OahHXTfsbijBVG0Sukvpp8mSSgseQvCG.jpeg"
  ]
 },
 {
  "lot_id": "7184825",
  "title": "CITROEN BERLINGO грузовой фургон, год изготовления 2010, идентификационный номер (VIN) VF7GCKFWCAX519902, цвет красный, ",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$fGlL90.0ZPnUZATTFaoEOfGMgGTMa7.qBuzSrJDNRnjhpJEEJ5i.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$3SSjapKARpZHu9RI9DXEugBYFciipSf6VEl6XEQub4AACrt3VFYC.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$O13GIWf2Nyle3C4bvrb53.0RNw7O02KVbSu7Ad6KPouOMZNjI4SW.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$EVMAbgmD5PK5XXIjIV9g9O88gyVUd7tS7UvsKL21hndt.o0pBHgu.png"
  ]
 },
 {
  "lot_id": "7193939",
  "title": "ФОЛЬКСВАГЕН МУЛЬТИВЕН, 2009 г.в.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$E4vHeqqWPLyeaGQRPjPoO..l12P.vwdy2.16nV.uWuq7J6GrAih..jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$I7vwMqURwSBt.KPXU488jOuy6DKOxec6erDIzHB7RdNjkFtZWUd0G.webp",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$lMnuzUYIoiri6JbDtVKqau2FM5zWCT1Zn0pxFjGcHg0vL4gfgm1RC.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$p8HZ1qkdyQVsxQMpygi8OgtH7rWV.yKH2Vc.aYbrnrVlw9Xet.6i.jpg"
  ]
 },
 {
  "lot_id": "7187371",
  "title": "Lada Granta, 2023 года, 89 лс",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$5Hs5nqpftLj5n5mNNOyWfu2.awdYFXyKd9uboTUBPZQRXAZBwaEy.png"
  ]
 },
 {
  "lot_id": "6953629",
  "title": "Автомобиль марки FORD модель FOCUS 2010 г.в. VIN-номер X9FHXXEEDHAY63738",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$tqdt8GP58qZRA892KsQud8XFc9y1qalXqBSAre8TNBK2xK0Dtq.png"
  ]
 },
 {
  "lot_id": "7160307",
  "title": "Audi A6, 1998 года, 165 лс, 238102 км",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$qeiOErUpt3IQEk8vSSMF2uAuoSubhKKfFpT3g81DCaLsFKrrP.x1..jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$FrZJFWmhf27GFwkQr1f2zeIXZ7OirAdDfYdH7U.cHmrST8SJZXOjK.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$MzWH.1VSOGbHVdsalqRGGuKnkptMDhxwikIjwz.yKrmpYYFz96SdW.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$lmTDRVkxp4aP6mTxIORl.wrEM5T9xIclcq8.OmqMLVkfoCFeqVTy.jpeg"
  ]
 },
 {
  "lot_id": "7226569",
  "title": "Легковой автомобиль марки SKODA, модель: Superb, год выпуска: 2012 г., идентификационный номер (VIN): TMBAB83T2D9027351",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$rT0.ovoq.b18Yd5iwXygOMpQ20GBZFxErrFXseegcDqGipn0rm.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$79O5ksQUbmxItLYRy5x8Dupxt91OI8sNFdieYOclzmHWXIoPcpPe2.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$HkOqMjZrk9E4WqDhuHz2XOAniQnY8luh1inQAsSwjN6bQSGhF1PG.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$yVLmJko2PadxU3ku1cnmwe.CenIPYBfjaXhqFftY89SXbLfRx0lu.jpeg"
  ]
 },
 {
  "lot_id": "7188743",
  "title": "Audi A3, 2013 года, 122 лс, 234000 км, АКПП",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$IhrVg.2Wc.ZmETI2w2uWEuOs3H6dNeaIiOnrz6StP0GP3skVTeb5y.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$uSYKbJlmYjkHK0ez181BOeIOQT1.miYYGzLs9Xi0fTNAzu2jk.PZG.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$XgF3ykp39OBxC2BDdQQN8OMUexTeectktREAdwCMsjVY7mx7rWXMC.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$Z.XMyIc8azs0uhv1fbjKZe9udLlwGDJ1soOYVTXdguzN09qmtUBy.jpeg"
  ]
 },
 {
  "lot_id": "7191224",
  "title": "Автомобиль марки OMODA S5 М3ХАЕ00ТL5W3Т0G1, год выпуска 2024, вин LVVDC21B5RD574965., цвет-белый, тип ТС: легковой, нахо",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$lL7Wu7vdxwu91OT92DhsV.lbtPvMkcaodLRs.3V2uaJzrxvPb0ny.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$1feZb3MDkzChC0GBOrzUjeVP20MzhVFKrn4XV2wmig4rCva4KA2le.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$.1Ifs.mQKufN3K289iQddeIxDE7UCpaiSYcgHJlg2DuiDAwy55m.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$MxgpxMUui8d0ig4Lbmwu.N5wgZLSknCe9iX78HSjHQJguIMeOPCG.png"
  ]
 },
 {
  "lot_id": "7193818",
  "title": "ФОРД ФОКУС, 2004 г.в.",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$nnfcxfnio77vLkMsDi81ou4KBrKfdAxee.UnW5.Y9NcFhcSIDyD0S.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$18NcVOPazQzgP76GgLFbuOEnt82F0PdHP.5IH86l7GpeRCOoSse6.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$8U1IyXvJRmhOqz6RjgHMh.UTuiVLy.HFWAjZAFnQfKbun2RleIDO6.jpg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$R0ISGqY92CcK49WnwCnOM.S9vmOmc.YoQaEWlhZcdjLQxbHW67TG.jpg"
  ]
 },
 {
  "lot_id": "7200701",
  "title": "транспортное средство: Cadillac SRX, Идентификационный номер (VIN номер): XWFFN9E51D0000078, Год выпуска: 2013 гос.но",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$2ndLZP1eH3Baunv9TMup7OAvH6SK8JxOvwHbzXS2ups88AtSGzi.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$wzArvjvOrW7ioYRr4udJousWedEAf10OgAJTDSNZbDQdRWt7UTTu.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$VQNTbw0pSeU0fjvSFWRuD9k4Mzisb4VLNkQMRIDs56Zr2F2oaYG.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$AE5jIcGkwpAKG3oCcLeI1.jQQuGXp9SXXWFCQ9YuXmNOhil1B5TFC.png"
  ]
 },
 {
  "lot_id": "7181220",
  "title": "Toyota Previa, 1998 года, 132 лс, 333333 км",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$heY0IyJ4G2aa5X5UF3dX.umIJuClMuoMIE.wsefDJu3Ct4U1qsHa.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$jJITBAnidU4OMPzACGzg.V5pkv0.NRhiPJL5ze7NgqJFWkagGu.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$eCtBRB1UBqDBkMXDz2udSO3a51K.EzhunFh5ndLG17UPznDDT7LF6.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$fbgzoz7cYIVQOyg314iLxutXcjYFe7ixyntmTs1Xmpa905MScLTe.jpeg"
  ]
 },
 {
  "lot_id": "7219230",
  "title": "Ford Explorer, 2013 года, 293,7 лс, полный привод, АКПП",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$qAgqWr31DFKZtWn8trbuOZlr67Wx46FoutR1I3hD7IugAyBceZu.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$rMXGtCpYnU0toHSZK0L6yuLNbLRxxHhVD3n4smHeWWzxI3cEIBFQK.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$ffgAvcoNJeWEJcRJ5oxW.QQm0gCo6hGO.hR2jHoeMoB06BSLUo6q.jpeg",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$6as.l4U4vIM5up4hpR0VJeBGPOgub0XDqk2CeuhBTgpstkA1acVy.jpeg"
  ]
 },
 {
  "lot_id": "7178263",
  "title": "Автомобиль",
  "photos": [
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$dIkPGyZxcylEQk7OfEqEkOzEMvvHlij58wZEEQI0IOWqG90ktX2d..png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$rOg8kM45rfW5Jp2ahYQX7.PkG3Yn0xLR0xm3j6i9dVoUOVjy7ZO.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$QsE5MCIf57ybl57VGTJGKu805ENsJ25lFcwwly5jCPmBo5ly5QAHG.png",
   "https://xn----etbpba5admdlad.xn--p1ai/pictures/$2y$10$HlfI5iWCNDiVx1kRc1r3KugJIyAuKiSan5i3JmyAKEzFbbaUiVC.png"
  ]
 }
]
```
