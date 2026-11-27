# Какие исторические данные уже есть
Инвентаризация 25.11.2026. Это снимок покрытия, а не гарантия отсутствия пропусков или point-in-time пригодности. Даты UTC; для ETF — даты торговых сессий США. Источник: публичный [btc-market-data](https://github.com/kh827y/btc-market-data). Новый приватный btc-lab пока не хранит эти архивы.

| Данные | Файл в btc-market-data | Найденное покрытие | Ограничение |
|---|---|---|---|
| Цена Binance BTCUSDT spot | btc-price/data/history.json | 799 закрытых дневных свечей 2024-09-17 — 2026-11-24; 299 недельных 2021-03-01 — 2026-11-16 | Минутных/часовых свечей здесь нет; USDT не USD |
| OI 5 бирж | btc-derivatives/data/latest.json → results.open_interest.daily_history | 31 дневная запись 2026-10-26 — 2026-11-25 | Последняя дата ещё не закрыта; проверить час и состав бирж; история короткая |
| Funding | тот же файл → results.funding | Сводки 21 расчётного периода за 7 дней для Binance, Bybit, OKX | Сами отдельные исторические ставки не представлены в этом блоке; нужен отдельный архив |
| Ликвидации | тот же файл → results.liquidations.24h | Снимок за 24 часа | Binance + Bybit; не ряд и не полный рынок |
| CFTC CME COT | тот же файл → results.cme_cot.history | 255 недельных записей 2022-01-04 — 2026-11-17 | Дата позиции не дата публикации; для исследований нужен лаг публикации |
| Спот CVD | btc-spot-cvd/data/state.json → hourly | 742 записи на каждую из 6 площадок, 2026-10-25 09:00 — 2026-11-25 06:00 | Скользящая 31-дневная история; проверять complete и Coinbase ID proof; смешанные временные основы |
| Макро FRED | btc-macro/data/fred_history.json → series | 7 рядов примерно за 2 года (498–730 наблюдений, баланс ФРС 104 недели) | Даты наблюдений не равны датам доступности; выходные и ревизии |
| ETF | btc-macro/data/latest.json → etf | 736 сессий заявлено в метаданных с 2024-01-11 по 2026-11-23; доступны последние 5 отдельных записей | Полный ряд в файле не хранится, нужен источник истории TFTC/Farside и учёт ревизий |
| Bitview ончейн | btc-onchain/data/bitview_history.json | 9 рядов по 1484 записи 2022-11-01 — 2026-11-23 | Когорты UTXO 150 дней, не взаимозаменяемы с другими определениями |
| Прочий ончейн | btc-onchain/data/history.json | 15 рядов примерно с ноября 2022; 1462–1484 записи | 5 важных метрик на 2026-11-17; пропуски/методологию проверять отдельно |
| Опционы Deribit | btc-options/data/derived_history.json | 183 снимка 2026-11-02 06:00 — 2026-11-25 08:00 | Нерегулярный ряд; ATM/RR/BF по срокам, не непрерывная почасовая история |
| L2 Bybit | btc-liquidity/data/bybit_independent_history.json | По аудиту: 1382 из 1384 допустимых дат linear, 551 из 552 spot | Снимки, не полная история стакана |
| L2 CryptoHFTData | btc-liquidity/data/hft_history.json | По аудиту 111–185 проверенных дат на рынок из 498–515; последние 30 дат отмечены проверенными | Много ошибок в старой истории; снимки в выбранные часы; 00 UTC не эквивалентно 12 UTC |

## Проверенные новые бесплатные API
[Проверка от 25.11.2026](https://github.com/kh827y/btc-market-data/actions/runs/45579049658):
- Kote Charts: MVRV, MVRV Z-score, NUPL, STH/LTH SOPR — 14 закрытых дней, последний день 24.11.2026. Не смешивать без проверки методологий; проверить лицензию перед хранением/публикацией.
- Coinalyze: 720 из 720 закрытых часовых записей OI для одного тестового рынка; 26 perpetual BTC и 87 spot BTC с buy/sell в каталоге. Это не подтверждение полной истории фиксированной корзины.
- CryptoHFTData: успешное получение токена и проверка архивного файла. Не подтверждает восстановление пропусков; соблюдать условия использования.

Ключи находятся в Secrets исходного репозитория, а не в btc-lab. Для локального сбора в будущем потребуется безопасная локальная настройка либо отдельные секреты в приватном репозитории; секреты не копируются между репозиториями автоматически.

## Приоритеты
1. Исторические графики из имеющихся рядов: цена, OI, Bitview; затем CVD, макро и опционы. Не подменять невалидные значения нулём. Разрывы отображать явно. Показать источник, временную основу, размер выборки и период.
2. До первого исследования новостей: загрузить закрытые минутные BTCUSDT свечи из официального архива, проверить календарь CPI/FOMC/NFP и временные зоны. Для начала не нужны все 201 текущие проверки.
3. Долгую историю OI, funding, ETF и свежий ончейн подключать по мере необходимости. Большие архивы — локально вне Git. Не публиковать лицензируемые данные без разрешения.

## Текущее состояние мониторинга
Снимок bridge 25.11.2026 08:56 UTC: 187 из 201 проверок usable, 5 incomplete, 5 stale, 1 invalid, 1 unavailable, 1 unverified. CVD collector после исправления завершился успешно, но у 60 часов Coinbase всё ещё нет ID proof: текущий бюджет сканирования не позволил закрыть первый проблемный час. 24h и 168h Coinbase ID proof полные на момент снимка CVD. Не объявлять 30d восстановленным. Не менять старый мониторинг ради лаборатории без необходимости.

## Расширение (после первого запуска панели)
Добавлены адаптеры полного TFTC ETF архива, Kote (MVRV, Z-Score, NUPL, STH/LTH SOPR), Coinalyze (Binance BTCUSDT perpetual: OI, funding close, ликвидации long/short). Запросы дневных рядов Kote с 2013, Coinalyze с 2019; реальные даты покрытия определяются ответами, не обещаются заранее. Локальные архивы не публикуются, не используются для бэктестов без проверки публикаций/ревизий. Источник старого мониторинга не заменён. Для новых API нужны существующие ключи локально; GitHub Secrets автоматически не переносятся.

## Результат локального запуска пользователя
ETF 736, Kote 5076 числовых наблюдений по каждому из пяти рядов, Coinalyze 1501 OI, 2500 funding, 1501 long и 1501 short. Это количество, не доказательство непрерывности. Добавлено накопление скользящих архивов и запрос дневного Binance CVD/цены с 2017 года; реальные даты покрытия Binance проверяются после загрузки. Стаканы и минутные свечи остаются следующим этапом.

## Исследовательские данные (27.11.2026)
Astra собрала CPI США с января 2018 по ноябрь 2026: 106 релизов, 105 пригодных месячных сюрпризов, отдельные официальные значения и альтернативные прогнозы. Исходный ZIP доступен владельцу, частные прогнозы не коммитить. Раннее раскрытие 15.05.2024, двухмесячное изменение 18.12.2025 и шесть конфликтующих классификаций прогнозов требуют явного учёта. Загрузчик минут Binance добавлен; покрытие на ПК пока не проверено. Источник: https://github.com/binance/binance-public-data .

### Первый локальный аудит минут (27.11.2026)
2017-08-17 — 2026-11-26 UTC включительно: 4 267 132 из 4 880 160 минут, 14 месячных ZIP отвергнуты из-за нестандартных временных границ, 609 120 минут в этих месяцах (не число реальных отсутствующих свечей); ещё 3 908 пропусков в принятых архивах. Исправление: исключать только свечи с нестандартными границами, не переносить/округлять их, хранить исходный ZIP и причины, повторно использовать валидные файлы. Реальное покрытие после исправления требует повторного локального запуска. Дефекты Binance также описаны в https://github.com/binance/binance-public-data/issues/77 .

### Повторный локальный аудит минут (27.11.2026, schema 2)
Период 2017-08-17 — 2026-11-26 UTC включительно. Приняты все 137 архивов, ошибок 0. 4 849 741 / 4 880 160 строгих минут (99,37668%); восстановлено 582 609 по сравнению с первым аудитом. 30 419 пропущенных минут в 35 интервалах, 21 618 исключённых нестандартных исходных строк (не прибавлять к пропускам). Основные пропуски: декабрь 2017 (20 479), февраль 2018 (3 262); с 2022 только 81 минута, с 2024 пропусков нет на данном срезе. Сопоставление с реальным CPI CSV: для всех 105 событий с core CPI surprise нет пересечений пропусков с диапазоном [релиз−1 мин, релиз+30 мин), минутой +31 и минутой +31 через 7 суток. Для двух (12.01.2018, 14.02.2018) не все необходимые 29 предшествующих дневных закрытий доступны из строгих минут; для шести неполон внутринедельный диапазон оценки максимальной просадки. Это аудит покрытия, не проверка фактических цен или независимого источника. Не заполнять пропуски, не менять времена; проверять достаточность каждого признака и исхода отдельно, неполные экстремумы не выдавать за полные. Данных достаточно для начала CPI; массовое восстановление пропусков отложено до доказанной потребности. Дневную историю Binance и независимую сверку цен проверить при подготовке исследовательского набора.

### Локальная подготовка CPI подтверждена
coverage.json от 27.11.2026: 106 событий, 104 стандартных с парой сюрпризов, 102 пригодных для недельного теста (46/24/32 train/development/test). Реакция, вход и недельные конечные цены есть на всех 106; у двух train отсутствует предшествующее состояние, у шести train неполная внутринедельная просадка. 421 из 424 кандидатов контрольных окон имеют цены, календарь не проверен. Отсутствие некоторых 28-дневных исходов связано также с границами выборок/истории. Сверка независимой биржи и исследовательская эффективность ещё не проверены. Версия данных закреплена в research_cpi_development.py.

### Миграция CPI-v2 подтверждена локально
27.11.2026: complete=true, cpi-v2-development-only, snapshot_sha256=c306087ece415f6473d4c93adf762ebcd2ae4abe7afd48d5c56cb6bcce2b04fb. Восемь хэшей train/development неизменны; 46+24 пригодных, 34 события зарезервированы, test_generated=false. Сам факт доступности сырых архивов не означает доступность для будущих агентных инструментов. Независимая сверка цен и контрольный календарь не выполнены.

### Независимый источник CPI (кандидат, реализация)
Coinbase Exchange BTC/USD spot, public candles API: https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles . Документация разрешает диапазоны 1m/1d, до 300 свечей, предупреждает о неполноте. Запрашиваем только нужные интервалы до 2024, локально сохраняем оригинальные ответы с SHA-256, не заменяем Binance. Kraken OHLCVT полный архив через 30.09.2026 опубликован пятью крупными частями (https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data), поэтому пока не скачиваем. Фактическая доступность исторического Coinbase API из среды пользователя и покрытие требуют запуска; не считать проверенными.

### Независимая сверка подтверждена (27.11.2026)
Присланный coinbase_development_report.json: 45/46 train, 24/24 development, всего 69/70; пропуск 10.08.2018 (минутная реакция и вход). Направление недельного исхода совпало 68/69; медианное абсолютное расхождение 0,0624 п.п., p95 0,6876 п.п., максимум 2,909 п.п. (11.10.2018); медианное расхождение реакции 30m 0,0378 п.п. На общих датах delta RMSE CPI − market: Binance +0,1679 п.п., Coinbase +0,1289 п.п.; прирост количества BTC против market +0,5405/+0,4899 п.п. Нулевой прогноз точнее обеих моделей. Не восстанавливать единичный пропуск; сохранить кэш ответов локально для воспроизводимости. Это сверка измерений и development, не независимые рыночные эпизоды и не итоговый тест.

### Календарь ALFRED (реализация)
https://alfred.stlouisfed.org/release/downloaddates?rid=180 (claims); rid 10 CPI, 46 PPI, 50 Employment Situation, 9 retail, 53 GDP, 54 Personal Income and Outlays. Текстовые выгрузки ff=txt без ключа. Даты могут включать ревизии и первое появление в FRED, а не фактический момент релиза; не источник для точной причинной идентификации. Кэшировать исходный текст с SHA-256, проверять покрытие по годам; фактический запуск ещё нужен. Только 2017-12–2023, плюс оригинальный архив CPI; не брать цены test.

### Календарная проверка завершена
Все семь ALFRED семейств загружены, одна повторная дата retail дедуплицирована, все даты CPI 2018–2023 совпали. 156/288 контрольных окон, 56 событий с контролями; полноценного календаря всех публикаций/минут нет. Кэш локальный, финальный недельный набор не фильтруется по этому календарю.


### CPI-001 итоговая сверка завершена
final_report.json от 27.11.2026, SHA-256 392070c4b42c89cac4821f875d66e60ea50a37dbaec2b9663963916025fd0c55. Хэши исходного ZIP, snapshot и frozen blobs совпадают с CPI_FINAL_LOCK.json. 32/34 пригодных итоговых событий, 32 недельных исхода и просадки, 31/32 28-дневных исхода и просадки (окно последнего релиза не завершилось). Coinbase 69/70 истории и 32/32 финал; совпадение знаков недельной доходности 32/32, медиана абсолютного расхождения 0,0317 п.п., максимум 0,1727 п.п. Сохранить исходный отчёт и кэши локально. Не загружать повторно без причины. См. вывод в ROADMAP.md.

### BUY-001: дневной BTC/USD, загрузчик
Официальный Bitstamp OHLC https://www.bitstamp.net/api/ (step=86400, limit<=1000, диапазон end имеет приоритет, исключить текущую свечу); Coinbase Exchange https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles (до 300 свечей, возможны пропуски и строки вне запрошенного диапазона). Запрашиваем 365/180-дневные окна соответственно, до 27.11.2026 exclusive, оригинальные ответы с хэшами локально. Сохраняем каждую биржу отдельно, 2014-01-01 и 2015-07-20 — выбранные начала, а не подтверждённые первые свечи. Веб-инструмент не получил исторический ответ Bitstamp; реальное покрытие ещё предстоит проверить. Скрининг 98% общего и 95% годового покрытия + последний день, явные пропуски/ноль объёма, межбиржевая разница close в общие даты. Это не доказательство пригодности для каждой гипотезы. Никакой синтетики или склейки. Для личного исследования, публичное перераспространение не предполагается. При недостаточном покрытии искать адресную альтернативу; не загружать многогигабайтный Kraken без необходимости.


### Первый локальный запуск дневной истории
Bitstamp 4713/4713 дней, 2014-01-01–2026-11-26, 3 нулевых объёма, 13 страниц без ошибок. CSV SHA-256 4b733feda6bd69c4810471440d2b53fba69ccdd3af47ca3caae593db75063bf9 закреплён в загрузчике. Coinbase 0/4148: HTTP 403 на первом диапазоне. В CPI ранее успешно работал явный User-Agent BTC-Lab research и Accept application/json; используем тот же формат запроса для повторной попытки, не считаем причину 403 доказанной. Если не поможет, независимая проверка возможна на имеющемся Binance BTCUSDT с 2017 года (другой котируемый актив, не склеивать). При необходимости искать отдельный USD источник; не задерживать BUY-001. Нулевой объём: будущий backtest не должен считать цену гарантированно исполнимой, даты отмечаются отдельно.

### Дневная история подтверждена
Bitstamp 4713/4713, Coinbase 4148/4148, до 26.11.2026 включительно; 100% каждый. Coinbase SHA-256 bc6282765d3e1638522e16422c0e833261c3058c6b7c4f6dbe869c2f3d36766e; обе версии закреплены в BUY-001. Три нулевых объёма Bitstamp 06–08.01.2015, Coinbase нет. Медиана расхождения close 0,02545%, p95 0,616%, max 6,487% в 2017; ранние режимы/различия ликвидности не игнорировать. Тесты восстановления Coinbase успешно пройдены. Не повторять сбор.


### BUY-001: финальная проверка данных завершена
Отчёт buy_final_report.json SHA-256 6d9d9edbfb760e7a109e74ea8065b1bcdff5b8386d2f997c9b0db2ee65de6e47; pinned input hashes и frozen blobs соответствуют BUY_FINAL_LOCK.json. На каждой бирже 148 прогнозных исходов, 144 восьминедельных эпизода, missing_forecast_dates и skipped_purchase_dates пусты. Первое начало покупки 2024-01-01, последнее 2026-09-28; cutoff 2026-11-27 exclusive. Оба рынка отражают одни эпизоды. Сохранить локальные CSV, оригинальные кэши и четыре отчёта BUY; повторный сбор не нужен.

### FLOW-001: данные
Binance public BTCUSDT spot klines: quote asset volume и taker buy quote asset volume, закрытые дни UTC 2017-08-17..2023-12-31. Кэш канонического JSON rows (не байты оригинального HTTP), запрос/хэш/retrieval UTC. Суммарный семидневный дисбаланс нормируется на общий оборот. Старый binance-spot.json содержит net и close, не denominator; поэтому новый небольшой fixed snapshot вместо повторной minute download. Покрытие ещё предстоит проверить локально. Не смешивать с мультибиржевым CVD, не считать proof of initial availability. Исходы из прежних pinned Bitstamp/Coinbase CSV, только development.

### FLOW-001 / VALUE-001
FLOW daily snapshot 2327/2328, malformed 2018-02-08; all 256 evaluation origins per market. Kote mvrv local archive (prior 5076 valid values, actual development coverage still to verify). VALUE-001 preserves prefix snapshot and hashes, no redistribution, no credential access. Kote methodology/docs describe daily valuations after UTC midnight; historical publication/revisions unverified, exact 3/8-day date offsets are assumptions. No live point-in-time claim.

### VALUE-001 / FUND-001
VALUE: Kote MVRV 3652/3652 days 2014–2023, earliest 2013-01-01, local archive source SHA-256 639d1d08f776ae8df1eb9ba1c1ec44e2f7187c3ce66195d18b3c6bf0d2b78554; development snapshot 2066c92e0d9001ddfd57e3c887988f1efa0fbe572fa20a750cb86e1df6fbf1cb. No vintage proof. FUND: new official Binance public monthly fundingRate archives, 2020-01..2023-12, original ZIP/checksums, 8h slots and actual timestamps, no interpolation, coverage not verified until local run. Local only, no keys. OI not included.

### FUND-001 / OI-001
Funding archive complete 4383/4383, snapshot pinned (80b2346eebc93691361d025f9eb113462b58f0e7c6431344a5609668db030d5e). OI downloads only Friday metrics ZIP/checksum, 2020-09-04..2023-12-29, local archive, compare notional/quantity against Bitstamp same Friday range +/-10%. Date-only observations flagged, last timed positive row within 15min of Friday end, reject missing/invalid dates, no interpolation. Historical semantics not confirmed by Binance (issues #509/#211); reconstruction only. Reuse funding archive, don't overwrite previous datasets.


OI first coverage 136/174, all rejected dates before 2021-05-28; prior failed coverage retained as coverage_before_parser_repair.json, valid cached ZIPs reused. Parser repair retains all checksum-verified ZIPs even if schema fails, no accepted snapshot until checks pass. Dense archives and consistent OI duplicates permitted, conflicting chosen timestamp rejected; 90% gate unchanged.

### OI-001 / MACRO-001
OI repaired coverage 173/174, only 2021-02-19 missing; 136 previously valid retained unchanged; 10365 duplicate rows, no conflicting OI timestamps in accepted archives. Snapshot c1d6295a30717177eacf981cb0f046d03003641638551700025a00085ab7b113. No fill. MACRO new public FRED CSV DFII10/DTWEXBGS 2019-02-04..2023-12-31, exact raw bytes/hash/source/retrieval, weekday coverage by year, bounded holiday lookup. H.10 weekly publication and 2019 methodology change documented in MACRO_PROTOCOL.md. Historical vintage not established, no claims of original availability; if candidate, ALFRED check. Coverage yet unverified.


MACRO acquisition retry: FRED primary, same-series ALFRED fixed 2026-11-25 vintage, one FRED retry. Source/header/hash/retrieval recorded; manual imports marked unverified, no claimed download timestamp. Coverage gate unchanged. No source substitutions; late vintage only, not PIT.

MACRO-001 both FRED primary datasets obtained, DFII10 SHA-256 0af5eb83986adf9e813db36a21dc710b1780bae258d5cac93da9a621d8803722, DTWEXBGS b27c757281efcad3cc12557c74b702820a17a9c6f61fe6f943064309b3626b97, 1229/1225 valid observations out of 1280 weekdays, 178 complete forecasts each. No original vintage proof. COMB uses existing pinned MVRV/OI/funding development snapshots only; preserve originals, no additional downloads.

COMB-001 report SHA-256 bb61842cddb8d912868a2607702985e80e094f442eab9c2f852dd4bd2b0d8e22; pinned input identifiers match previous VALUE/OI/FUND and USD snapshots. 86 forecasts and 56 purchase episodes per market; warmup excluded first planned forecast and 27 purchase origins. No new downloads or numeric 2024+ outcomes. Preserve local original reports and caches; no independent source-byte or purchase replay verification in report-only review.

DVOL-001: public Deribit BTC volatility index 1D, 2021-04-01..2023-12-31. Raw JSON, request URL, SHA256, retrieval time; bounded continuation, date/scale and coverage checks, no missing-value fill. Actual production availability and historical publication vintage not verified yet. Annualized implied volatility percent, not realized volatility or physical downside probability.

### Ранние дневные цены: отдельный аудит (28.11.2026)
Bitstamp public OHLC BTC/USD, 2011-08-18..2014-12-31, 365-day bounded windows, same validated parser as daily-usd-v1. Actual earlier coverage not yet established. Retain raw pages with retrieval time and SHA256, report missing/zero-volume days, full OHLCV overlap differences vs pinned 2014, and cross-venue flags on pinned 2015–2023 days (low/high/close ratios outside [0.8,1.25], low below half of candle body or high above twice it). Flags are heuristics, not deletion rules or proof of incorrect trades. Kraken official archive is candidate independent source from 2013 but full archive multipart and large; prefer small auditable independent series if available. No changes to frozen daily snapshot, no combined series or model fit. Local report pending.

### Проверка совместимости спотовых и деривативных данных (28.11.2026)
`research_derivative_sources.py`: фиксированный период 2020-09-01..2024-01-01 exclusive; Binance USD-M BTCUSDT monthly `klines` и `premiumIndexKlines` 1h, daily `metrics` за первый день каждого месяца. Источник https://github.com/binance/binance-public-data и https://data.binance.vision/ ; сохранение исходных ZIP, SHA-256 по CHECKSUM, URL и времени получения; reuse `oi_v1/cache` при совпадении даты и источника без изменения старых файлов. Часовые спотовые данные строятся из существующих проверенных 1m ZIP. Сверяются точные UTC-часы, положительные объёмы, границы свечей, знак taker flow, таймстемпы и дубликаты OI, отношение notional/quantity относительно диапазона цены фьючерса с допуском 10%. Premium index — безразмерная знаковая величина, не funding и не точный basis; метрики OI не доказывают вынужденную ликвидацию. Пропуски не заполняются. Проверка OI выборочная, не полная история. Семантика исторических единиц, UTC для naive timestamp и первоначальная доступность не доказаны. Внешние файлы в среде помощника недоступны (DNS); фактическое покрытие и форматы до локального запуска не подтверждены. Никаких 2024+ данных или оценок исходов.

Проверка source_audit.json владельца завершена: SHA-256 961e715769370f2368767198f49cb89c043a6179a49f8ee3c765b474e3ce9e24; 40 месяцев, 29208/29208 часов фьючерсов, 29039/29208 премии, 29010/29208 совместных часов. На 40 контрольных днях OI 11519/11520 пятиминутных интервалов, 2592 одинаковых дубликата, 0 конфликтов/отклонённых наблюдений/несоответствий единиц, максимальный внутренний разрыв 10 мин. 169 часов премии отсутствуют (120 в 2021-07, 24 в 2022-10, 24 в 2023-02, 1 в 2020-12). Хэш отчёта вычислен из фактических присланных байтов; суммы пересчитаны по месячным строкам. Исходные ZIP независимо не воспроизведены. Полное покрытие OI не установлено. Добавлен `research_derivative_panel.py`: тот же фиксированный период, все 1217 дневных metrics, точное соответствие reviewed audit/spot manifest/месячным SHA и контрольным дням. Сохраняется локальный `hourly_panel.json` и `panel_coverage.json`, точные OI :00/:55 в единицах источника и notional, пропуски null, внутридневные архивы остаются в кэше. Никакой интерполяции, 2024+ данных, причинной атрибуции или расчёта будущих исходов. Полный локальный сбор ещё не проверен.
