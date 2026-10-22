# DATA_MANIFEST: слой первичных point-in-time данных для проверки механизма (тренд/пробой на майорах)

Собрано 2026-10-19 скриптом `research/mech_collect.py` (ветка `mech/data-layer`). Все источники бесплатные, без ключей.
Данные НЕ берутся из `data/market` (survivorship-biased); сверка: дневные close BTCUSDT совпадают с `data/market` (отн. расхождение 0.0).
Время везде UTC. Шарды по символам: `data/mech/raw/<датасет>/<биржа>/<символ>.parquet`; итоговые файлы: `data/mech/<датасет>_<биржа>.parquet` (колонка `symbol` + поля).
Parquet-данные (~790 МБ) в git НЕ коммитятся (ограничение размера репо, в `.gitignore`); воспроизводятся командами ниже. В git: скрипт, манифест, `universe_*.parquet`, `selected.json`, `liquidation_probe.json`.

## Датасеты (фактические диапазоны)

| Датасет | Биржа | Символов | Строк | Диапазон | Гранулярность | Размер | Поля |
|---|---|---|---|---|---|---|---|
| universe_binance | Binance USDM | 927 в exchangeInfo + 140 только в архиве = 1067 | 1067 | - | - | <1 МБ | symbol, base, quote, contract_type, status, onboard_ts, delivery_ts, in_exchangeinfo, in_archive, is_usdt_perp |
| universe_bybit | Bybit linear | 1957 (в т.ч. 327 закрытых перпов) | 1957 | - | - | <1 МБ | symbol, contract_type, status, base, quote, launch_ts, delivery_ts |
| klines_1d | Binance | 689 USDT-перпов (TRADING + SETTLING + 75 архивных делистнутых) | 590 483 | 2019-09-08 .. 2026-10-19 | 1d | 28 МБ | ts, o,h,l,c, volume, quote_volume, trades, taker_buy_volume, taker_buy_quote_volume |
| klines_1h | Binance | 77 (selected) | 2 951 267 | 2019-09-08 .. 2026-10-19 | 1h | 129 МБ | те же |
| klines_1d | Bybit | 76 | 101 856 | 2020-03-25 .. 2026-10-19 | 1d | 4 МБ | ts, o,h,l,c, volume, quote_volume (trades нет в API) |
| klines_1h | Bybit | 76 | 2 228 756 | 2020-03-25 .. 2026-10-19 | 1h | 60 МБ | то же |
| funding | Binance | 77 | 422 742 | 2019-09-10 .. 2026-10-19 | по событию (8ч; у части символов 4ч) | 4 МБ | ts, funding_rate, mark_price (mark только из REST) |
| funding | Bybit | 76 | 348 788 | 2020-03-25 .. 2026-10-19 | по событию (8ч/4ч/1ч) | 1 МБ | ts, funding_rate |
| oi_1h | Binance | 77 | 2 420 101 | 2020-09-01 .. 2026-10-19 (медиана старта символа 2021-12-01) | 1h (срез 5-минутных строк архива metrics на :00) | 106 МБ | ts, sum_open_interest, sum_open_interest_value, count/sum_toptrader_long_short_ratio, count_long_short_ratio, sum_taker_long_short_vol_ratio |
| oi_1h / oi_1d | Bybit | 76 | 2 452 760 / 102 200 | 2020-07-20 .. 2026-10-19 (1h), 2020-08-05 .. (1d) | 1h / 1d | 17 + 1 МБ | ts, open_interest |
| borrow_snapshots | Bybit (spot-margin, публичный эндпоинт) | 3601 строк, 1 снимок | - | 2026-10-19 (один момент) | снимок | <1 МБ | snap_ts, currency, hourly_borrow_rate, borrowable, max_borrowing |

Выборка `selected.json` (77 символов, причины по каждому): топ-40 живых USDT-перпов по 24ч обороту на дату сбора + все 40 символов из `data/market` + топ-20 ДЕЛИСТНУТЫХ (SETTLING/архив) по суммарному историческому обороту (MATIC, FTM, EOS, LUNA, WAVES, MKR, LRC, STORJ, TON, OMG, ...). Дневные свечи собраны для ВСЕХ USDT-перпов, поэтому PIT-ранжирование «топ-N по обороту на дату t» делается из `klines_1d_binance` без выживаемости. Часовые/funding/OI - только по 77 (при необходимости расширить: `select` -> `klines_h funding oi`).

Bybit покрывает 76 из 77 символов Binance (кроме отсутствующих на Bybit); у 22 закрытых Bybit-контрактов история взята с якорем на delivery_ts.

## Как устроено против survivorship
* Binance exchangeInfo сам хранит 133 контракта в статусе SETTLING (делистнуты) с onboardDate/deliveryDate - это основной источник PIT-делистингов.
* Ещё 75 USDT-перпов и 65 датированных/«SETTLED» контрактов исчезли из API, но есть в архиве data.binance.vision (status=DELISTED_ARCHIVE_ONLY; дата делистинга = последний бар архива, delivery_ts не известен).
* Bybit instruments-info со status=Closed отдаёт 327 закрытых перпов с launchTime/deliveryTime.
* После делистинга REST Binance отдаёт плоские нулевые бары - они срезаны (по delivery_ts и нулевому обороту).

## ПРОБЕЛЫ (честно)

| Что | Статус | Суррогат / что нужно |
|---|---|---|
| **История ликвидаций (P2, P6)** | НЕТ бесплатно. `allForceOrders` Binance -> 404 (снят), `!forceOrder` - только реалтайм, `data.binance.vision/.../liquidationSnapshot` пуст (0 ключей), Coinalyze -> 401 (нужен ключ, free-ключ даёт ограниченную историю - можно получить регистрацией, не делалось), Coinglass -> "API key missing" (платный/по ключу). Результат пробы: `liquidation_probe.json` | СУРРОГАТ (не данные о ликвидациях): всплески объёма/taker-flow против тренда (`taker_buy_*` + volume из klines) и свечные фитили из часовых OHLC. Для чистой проверки: платный Coinglass/Kaiko/Tardis, либо СТАРТ форвард-записи `!forceOrder` вебсокета сейчас (даст честную историю только вперёд). Имеющийся OI-дроп (резкое падение sum_open_interest_value при движении цены) - второй суррогат кластера ликвидаций |
| **Ставки заёма / стоимость шорта (P4)** | История НЕТ бесплатно (Binance margin interest history - нужен ключ; Bybit interest-rate-history - "apiKey is missing"). Есть только ТЕКУЩИЙ снимок Bybit `spot-margin-trade/data` (borrow_snapshots.parquet) | СУРРОГАТ: funding rate как цена удержания шорта/лонга в перпе (есть полная история). Для заёма: копить снимки ежедневно вперёд (`mech_collect.py borrow` в крон - не заведён, чтобы не трогать крон) либо платный источник |
| Делистинги: полнота | Binance - практически полная (SETTLING + архив), но для архивных символов нет точной даты делистинга/причины; Bybit - 327 закрытых перпов с датами. Нет метаданных причины (делистинг по решению биржи vs ребрендинг, напр. MATIC->POL, RNDR->RENDER, MKR->SKY: у части «делистов» есть преемник, ряд обрывается) | ребрендинги надо вручную склеивать/исключать при тесте |
| OI Binance глубже | REST openInterestHist отдаёт только ~30 дней (проверено: 1h окно ~21 день, 1d - 30 дней); история взята из архива Vision `metrics` (5m, с 2020-09-01, у большинства символов - с 2021-12 или даты листинга). Выкладка в архив отстаёт ~1 день; хвост до сейчас - из REST | У BTC 8 пропусков >2ч (макс 11ч) в OI - не интерполировались. Пропуски по остальным символам не аудировались |
| OI Bybit 1h/1d | Берётся полностью (с запуска контракта), в API = количество контрактов (не $), нет value | $-OI считать как open_interest * close |
| Bybit klines: нет `trades`, нет taker-buy | ограничение API | - |
| Funding Binance: ts с дрожанием ±1 мс | не нормализовано (сырые funding timestamp) | при джойне округлять до минуты |
| Часовая/OI глубина только для 77 символов | осознанный объём; дневные - для 689 | расширяется перезапуском шагов |
| Selection bias остаётся в списке 77: топ-40 «живых» выбран по обороту на 2026-10-19 (знание из будущего). Для PIT-теста выбирать вселенную по `klines_1d_binance` на дату t, а часовые докачать для нужных символов | известный остаточный риск | - |
| **L2-стакан и тики (микроструктура, реалистичный impact)** | НЕДОСТУПНО через free API (исторически) - не пытались | нужен платный Kaiko / Tardis (Binance/Bybit tick + L2). Binance Vision отдаёт aggTrades/bookTicker, но не L2-глубину; в сборе не использовано |
| Спот/маржа-площадки, ритейл-разрез (P3) | не собирались; разрез по монетам делается внутри perps (мем/ритейл-токены по base) и по бирже (Binance vs Bybit) | при необходимости - Coinbase/Kraken спот как «неритейловая» площадка |
| Basis/index/mark klines, long-short ratio Bybit | не собирались (в Binance metrics long/short ratio есть) | можно добрать из Vision indexPriceKlines/markPriceKlines |

## Воспроизведение
```
.venv/bin/python research/mech_collect.py universe   # вселенные Binance+Bybit
.venv/bin/python research/mech_collect.py klines_d   # дневные ВСЕХ USDT-перпов Binance (~15 мин)
.venv/bin/python research/mech_collect.py select     # 77 символов -> selected.json
.venv/bin/python research/mech_collect.py klines_h && ... funding && ... oi   # Binance часовые/funding/OI (~1.5 ч, OI из архива)
.venv/bin/python research/mech_collect.py bybit      # Bybit: свечи/funding/OI
.venv/bin/python research/mech_collect.py borrow     # снимок ставок заёма (можно запускать повторно - дописывает)
.venv/bin/python research/mech_collect.py liqprobe   # проба доступности ликвидаций
.venv/bin/python research/mech_collect.py build      # сборка итоговых parquet
```
Шаги резюмируемые (существующий шард пропускается, `--force` перекачивает). Троттлинг: Binance REST >=0.15-0.7 с между запросами, пауза при used-weight>1800/2400 и Retry-After на 429/418; Bybit >=0.12 с.
