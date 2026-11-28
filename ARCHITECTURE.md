# Архитектура BTC Market Panel — простыми словами

**Главный принцип:** сбор данных уже работает отдельно в `btc-market-data`. Этот проект **читает** готовый `btc-monitor/data/brief.json` и отдельные исторические архивы, проверяет указанные в нём статусы и показывает значения в браузере.

1. **`btc-market-data` (чужая папка, не изменяется)** — GitHub Actions скачивают данные бирж, FRED, ETF и других источников. Собирают общий снимок `brief.json` с метаданными качества.
2. **`app.py` (интерфейс)** — скачивает `brief.json` по URL либо читает локальный файл. Делает локальную резервную копию и показывает страницы панели, графики стаканов и справочную информацию.
3. **`data_logic.py` (проверка отображения)** — извлекает числовые показатели, учитывает статусы `metric_quality.checks`, не подменяет отсутствующие значения нулями, проверяет полноту CVD и глубины стаканов. Здесь же форматирование чисел, перевод кодов агрегатора на русский, местное время и производные значения (расстояние до уровня, среднее), которые считаются только из проверенных чисел. Не зависит от Streamlit и может тестироваться отдельно.
4. **`tests/` (тесты)** — проверяют плохие данные и риск тихой подмены неполных показателей. Перед изменениями в `data_logic.py` запускайте тесты.
5. **`data/last_good.json`** — последняя успешная копия JSON, создаётся локально, никогда не изменяет исходные данные агрегатора.

## Как добавлять метрику

1. Найдите точный путь значения в JSON, например `derivatives.oi_five_venue_usd`.
2. Найдите связанную проверку `metric_quality.checks`, например `derivatives.oi_five`.
3. Добавьте `card(название, mv(data, путь, проверка), единица)` в нужную функцию страницы в `app.py` (для ончейна — `onchain(data, группа, имя)`).
4. Отдельно обозначьте единицы, период, источник и дату наблюдения.
5. Если статус не `usable` либо `value` равен `null`, покажите «—» и причину.

## Что намеренно отсутствует

- Новые сборщики и дублирующие запросы к биржам.
- Вызов языковых моделей и платные ключи API.
- Прогнозирование, бэктесты и торговые сигналы.
- Исторические линейные графики из одного актуального среза.

## Возможное продолжение

Когда будет нужна история, отдельный адаптер читает архивы из `btc-market-data` в режиме чтения и создаёт проверенные временные ряды. Позже можно добавить страницу «Новости и исследования» с событиями, но без вмешательства в работу текущего мониторинга BTC.

## Переход к BTC Lab (25.11.2026)
Панель перенесена в приватный репозиторий btc-lab.  DATA.md содержит инвентаризацию исходных исторических рядов. Добавлен просмотр истории с явным отображением пропусков. Исследовательские скрипты и локальные архивы появятся после определения первого протокола исследования, а не заранее.

## История рынка
- history_logic.py — адаптеры конкретных архивов, проверка состава OI/CVD, закрытых дней, чисел, времени; формирует ряд с пустыми интервалами.
- history_page.py — отдельная страница Streamlit; загружает только выбранный архив (и цену при сравнении), кэш 5 минут. Данные не сохраняются в Git. Историческая страница независима от доступности brief.json и пока работает только в онлайн-режиме.
- tests/test_history_logic.py — контрольные примеры для пропусков, неверной корзины, Coinbase proof и незакрытых дней.
- Исторические статусы не считаются автоматически verified: это базовая проверка формата и отдельных правил, а не проверка point-in-time. ETF только последние 5 сессий; funding и ликвидации не добавлены без полноценного ряда. FRED/ETF нерегулярные серии показываются без искусственных календарных нулей. CVD — чистый поток за час, не накопительная линия.

## Расширение истории
- extended_history.py: прямой доступ к TFTC, Kote Charts и Coinalyze. Проверяет точные поля, даты и рынок, исключает открытые дни Kote/Coinalyze, атомарно сохраняет успешные локальные JSON с источником и временем загрузки. При ошибке прежний файл остаётся. Не переносит ключи из GitHub Secrets.
- download_history.bat: ручной запуск загрузки; без планировщика и новых серверов. Ключи хранятся локально в игнорируемом data/provider_keys.json, в открытом виде на диске; не публиковать. Только ETF открывается также напрямую без ключа.
- История источников показывается отдельно, не смешивается с прежними рядами. Coinalyze использует дневные данные конкретного Binance BTCUSDT perpetual. Funding close не является дневной суммой или подтверждённой 8h ставкой. Kote не применяется для автоматических сигналов и не публикуется.

## Накопление истории
history_store.py сохраняет нормализованные OI 5 бирж, CVD 5 бирж и опционы в локальную SQLite data/history.sqlite3. При активной панели обновляет эти архивы не чаще 30 минут (кэш Streamlit; ручное обновление сбрасывает кэш). Старые даты за пределами нового окна сохраняются, пересекающиеся даты обновляются, включая null при новой неполноте. Сохраняются первое/последнее получение, но не все версии значений: это ещё не point-in-time хранилище. Если панель закрыта, автоматического накопления нет. Качество истории — ручная сводная проверка всех рядов. extended_history.py сохраняет старые даты при загрузке совместимого источника. binance_daily.py получает официальный закрытый дневной ряд цены и чистого такерского оборота в USDT одного рынка. Не объединяет его с пятибиржевым CVD.

## История стаканов и исправление Binance
- depth_history.py проверяет рынок, инструмент, дату и время, обе стороны полосы, долю bid; depth_page.py показывает графики bid/ask и долю, причины пропусков. Независимый Bybit 00:00 + 180 секунд; HFT строго 12:00 ±30 минут. Не объединяем источники или часы. Не рассчитываем дневной средний стакан из снимка. История стаканов не входит в прежнюю сводку 35 рядов, покрытие видно в отдельном разделе.
- binance_daily.py получает фиксированные окна календаря, нормализует точные микросекундные границы, отмечает повреждённые свечи и отсутствующие дни как null, выводит причины. При покрытии ниже 95% сохраняется предыдущий архив; реальный источник проверяется отдельно. Это не подтверждает конкретную причину ошибки на Windows до повторного запуска.

## Минутные архивы
binance_minute.py и download_minutes.bat — отдельный локальный загрузчик Binance BTCUSDT spot. Сохраняет оригинальные ZIP и JSON происхождения/качества, проверяет SHA-256, календарные границы, точные милли-/микросекунды, числовые поля и порядок свечей. Пропуски представлены диапазонами UTC ms [start,stop), не заполняются. Повторный запуск сверяет хэш локального ZIP; --refresh заново проверяет источник. audit.json — отчёт выбранного диапазона, а не индекс всех файлов. Дневные и месячные архивы могут сосуществовать; следующий исследовательский адаптер должен выбирать одну версию, а не объединять дубли. Существующая панель не зависит от минутных файлов.

Минутные архивы v2: исходный ZIP сохраняется с проверенным SHA-256; `iter_klines` исключает нестандартные временные границы (частичные и сдвинутые свечи), не округляет и не переставляет их. Только строгие UTC-минуты допустимы для исследования. Аудит хранит число и примеры исключённых строк, точные интервалы отсутствующих минут; число исключённых строк не равно автоматически числу пропусков. Не читать сырой ZIP в бэктесте напрямую. Неоднозначная дата, нарушенный порядок/дубликаты и неверные числовые поля по-прежнему отклоняют архив. Ранее принятые строгие архивы schema 1 переиспользуются без повторной загрузки.

## Первые исследовательские инструменты
research_prices.py загружает только архивы из завершённого audit.json, проверяет границы, хэши, число свечей и создаёт локальную UTC-сетку OHLC (NaN для пропусков). Точные точки, полные интервалы, реакция, 28-дневное состояние и исходы доступны как отдельные функции. Дневные закрытия берутся только из последней минуты дня. Доходность open-to-open, худшая просадка от цены входа требует полного интервала lows и обеих цен входа/выхода. research_cpi.py читает исходный архив Astra с закреплённым хэшем манифеста, не исполняет вложенный код, сверяет факт, прогноз и время. Отдельные features/outcomes по train 2018–2021, development 2022–2023, test с 2024; исход, пересекающий границу, исключается. Доходности в десятичных долях, CPI в п.п. Волатильность — выборочное стандартное отклонение простых дневных доходностей 28 закрытых дней. +30 реакция, +31 вход, 7/28 суток и +1441 отложенный вход. Четыре предшествующих контрольных окна в том же времени Нью-Йорка — лишь кандидаты, календарь ещё не проверен. coverage.json содержит хэши выходов и покрытие, не результаты эффективности. Файлы test локальны, но не защищены от ручного открытия. До открытия результатов надо заморозить критерии, издержки и правила обучения; проверить независимый источник цены и сопутствующий календарь. Не посылать частные прогнозы внешним API без оценки лицензии.

Признаки позднего входа (+1441) сохраняются отдельно в delayed_features; фактическая цена исполнения и пригодность по будущему исходу относятся к outcomes, не к признакам прогноза. Код подготовки не открывает метрики эффективности, но сам вычисляет и сохраняет метки; доступ к финальным данным пока организационный, а не технический.

research_cpi_development.py — первый детерминированный исследовательский replay, переиспользует данные подготовки и проверяет их хэши. Только train/development, модели OLS со строго прошлыми завершёнными исходами, фиксированные признаки и одинаковые даты; итоговые CSV не читает. Отчёт и отдельный реестр прогнозов остаются в data/research/cpi. Не является полным бэктестом или агентным контроллером. Правила CPI_PROTOCOL.md.

После аудита Opus: research_prices.snapshot/snapshot_hash закрепляют URL, диапазоны, SHA-256 и числа строгих строк; служебные времена/кэш не входят в идентификатор. CPI-v2 использует локальный price_snapshot.json, проверяет оригинальные архивы, не вычисляет ни одного test события и сверяет все восемь development CSV с исходными хэшами. Миграция удаляет только прежние четыре test CSV, не читая их, после проверки совпадения train/development. Raw ZIP остаются локальными и содержат будущие цены: это не песочница ОС и не гарантия отсутствия знания истории. Агентам впоследствии разрешать лишь конкретные development-операции; не давать доступ к raw/файловой системе. Финальный evaluator отдельно после заморозки методологии, пока не реализован.

research_cpi_diagnostics.py — чистая development-диагностика поверх существующего replay, без переопределения моделей или перезаписи исходного отчёта. Парные интервалы и фиксированные проверки устойчивости, отдельный JSON; финальные данные не читает. См. CPI_PROTOCOL.md.

research_cpi_coinbase.py — отдельная сверка development с Coinbase Exchange BTC/USD spot, 3 целевых окна на эпизод, верификация структуры и хэшей ответов, кэш локально, одинаковые даты и неизменный replay. Отсутствующие свечи не синтезируются. Запросы с концом позже 2024-01-01 запрещены, не используется raw Binance и не выдаётся тест. Не является универсальным загрузчиком или новой зависимостью.

research_cpi_calendar.py — отдельный описательный part A, семь фиксированных списков дат ALFRED, кэш в data/research/cpi, проверка формата и минимального покрытия, контрольные окна в том же местном времени, исключение всего дня при совпадении списка. Не изменяет подготовленные CSV или недельную модель, не читает итоговые данные. Ограничения в CPI_PROTOCOL.md.

research_cpi_final.py — отдельный локальный evaluator, сверяет Git lock и committed blobs до чтения исходов; итоговые события только в памяти, один final_report.json без перезаписи. Независимая репликация использует расширенный cutoff только из финального evaluator; обычный Coinbase development сохраняет старое ограничение. Это организационная/техническая защита от случайного изменения, не OS sandbox.

forecast_journal.py — изолированный локальный перспективный журнал; использует существующие binance_daily.parse_klines и extended_history.request_json, публичные UTC daily и exchange time. issue/settle/status, данные под игнорируемым data/research/forecast. Фиксированный empirical-v1 с 7/28/90d, прогноз и source snapshot отдельно от исходов. Независимое время receipt проверяется отдельно по GitHub Issue, не подменяется exchange clock. Никаких ключей, фоновых процессов, вызовов LLM или записи на GitHub из скрипта.

research_daily_usd.py — отдельный фиксированный снимок daily_usd_v1 для BUY-001, официальный Bitstamp/Coinbase OHLCV, проверка UTC, чисел, дубликатов и покрытия; неизменяемый CSV по каждой бирже, оригинальные ответы кэшированы под data/research/daily_usd_v1. Отчёт только качества, без расчёта результатов исследований. Не меняет CPI frozen blobs, не затрагивает панель/мониторинг, не смешивает USD с USDT.

research_buy.py — development-only BUY-001. Проверяет хэши полных CSV, парсит цены только до 2024, вычисляет недельные point-in-time состояния/риски и одинаковые симуляции покупки. BUY_PROTOCOL.md содержит точные правила. Локальный buy_development_report.json, без test CSV, платных вызовов или новых зависимостей. Не менять CPI и журнал.

research_buy_risk.py — отдельное development расширение BUY-001, fixed ridge logistic L1/M2, matched rolling evaluation, калибровка, условные парные блоки, одинаковые правила распределения капитала и контроль фиксированной отсрочки, cash sensitivity. Использует load_development и simulate исходного модуля, не меняет исходные результаты, не открывает финальные цены.

research_buy_audit.py — development-only post-audit controls; reuse original replay/simulate, assert previous sample and BTC gain, exact allocation-schedule rotations and model pair deltas, 52-week conditional intervals primary. Raw data unchanged, new local report only. No final guard bypass, journal v1 unchanged.

buy_journal.py — BUY-compatible prospective journal, shared build_signals from research_buy and research_buy_risk, pinned Bitstamp + closed live candles, separate source/forecast and outcomes, tracked hash receipt ledger, paper decision tables. No historical score pass during issuance. Local gate relies on verified manual external receipt, not an immutable remote server. Existing development entrypoints retain 2024 guards; original journal untouched.

research_buy_final.py — отдельный gated historical evaluator, BUY_FINAL_LOCK.json pins committed protocol, code, input CSV hashes and three prior reports; shared forecast/simulation helpers, no change to development cutoffs, local immutable final report. No new dependencies or calls to market API/LLM. BUY journal separate.

research_flow.py — изолированный development-only FLOW-001, фиксированные daily Binance public pages, нормированный taker flow, shared BUY features/logistic/outcome/interval, paired forecast comparison. Кэш и report under data/research/flow_v1. Нет доступа к 2024+ numeric values, не меняет BUY/CPI locks или dashboard.

research_value.py — development-only valuation reconstruction, local Kote MVRV, pinned prefix snapshot, 28/90d matched probability comparisons and descriptive valuation bands, 3/8-day offsets. Reuses BUY features/labels/logistic/interval, no frozen files changed, no new credentials/network. Historical vintages not proven.

research_fund.py — isolated development-only settled funding study; reuse original Binance checksum/ZIP helpers and BUY feature/label/logistic/interval, fixed monthly archive prefix, exact 21 settlement feature, matched comparison, data/research/fund_v1; no original frozen files modified.

research_oi.py — isolated weekly OI reconstruction, verified original ZIPs, conservative Friday timestamps, notional/quantity sanity check, fixed relative OI feature plus existing pinned funding. Shared BUY/FUND calculations, matched sample, local reports only. No final outcomes accessed.

research_macro.py — development-only matched macro probability comparisons, FRED raw snapshots, bounded holidays and publication lag, fixed two financial-condition features, shared BUY/FUND calculations; no historical vintage proof, no changes to frozen code or panel.

research_comb.py — isolated registered post-screening development follow-up, pinned input snapshots, shared BUY/VAL/OI/FUND features and BUY audit rotation; matched labels/models, practical equal-budget comparison, no final data or network. Existing frozen modules untouched.

RESEARCH_REGISTRY.json — machine-readable retrospective study-family inventory and forward registration policy. RESEARCH_POLICY.md — decision objectives, synthetic gate requirements and staged roadmap. Future local tools will enforce registered study specs and budgets; no runtime enforcement or new agent controller implemented in this documentation change.

research_drawdown.py — descriptive DD-001, shared pinned BUY loader/outcomes, observed closing peak and episode inventory, fixed depth groups, censored recovery and illustrative static exposure. No network, no forecast fit or decision confirmation. Separate local report; no frozen files changed.

research_gate.py — isolated synthetic risk-method diagnostic, known regime/latent feature process and exact oracles, numerical batched legacy logistic with parity test, independent null calibration/validation and fixed effects. No arbitrary code or external agents, no market input. Study-specific gate still required.

research_risk_reference.py — descriptive price-only forecast calibration diagnostic, fixed expanding/rolling empirical and volatility-scaled distributions, EWMA variance reference, common BUY price reader/state/outcome, exact empirical CRPS and reliability bins. No fitted factors, post-2023 numeric prices or market confirmation. No network or paid calls.

risk_journal.py — separate prospective price-reference tracking, same live source and matured outcome/state functions, fixed expanding distributions with recorded empirical samples and independent receipt ledger, 7/28/90d settlement. No historical confirmation, trade rules or OI challenger. BUY journal unchanged. Manual anchor workflow, no external credentials.

research_dvol.py — official public Deribit daily DVOL acquisition and coverage audit, cached raw pages and normalized snapshot; fixed descriptive comparison to 30-day realized variance and price EWMA, no model fit or new confirmation. Existing price loader/fetch helpers reused.

research_tools.py — narrow local read-only dispatch, explicit operations/argument allowlist, fixed metadata and report paths, 24 KB output limit, bounded reads, journal receipt hash checks; no raw report contents, shell, network, writes, API calls or held-out outcome access. Host controls root/date, never expose those to model. Not a general filesystem sandbox or complete agent system.

research_controller.py — host-side sequential three-call controller with strict JSON and explicit tool/evidence allowlist, bounded payloads, no retry, human review required. DryRunTransport is deterministic local stub only. No provider API, credentials, or execution capability. See AGENT_CONTROLLER.md.

research_provider.py — separate owner-launched synthetic-only CheapVibeCode transport, fixed routes, bounded requests and responses, estimated base-unit reservation, usage validation, no retry/redirect, ephemeral key. No real registry or journal reads in pilot. No provider-side spending guarantee.

research_metadata.py — fixed local projection and preview before explicit paid consent; frozen in-memory tool results, no model-directed filesystem access, limited enumerated fields only. Separate real-metadata pilot reuses controller/provider. No raw outcomes, paths, receipts or hashes exported; no execution or new research authorization.

research_credentials.py — host-only Windows Credential Manager adapter; no plaintext fallback or model access. Paid confirmation before retrieval; fixed credential target, replace/delete support. No keys in Git/report. Not a defense against malicious same-user processes.

research_credentials.py now uses a project-local ignored plaintext key file instead of Windows Credential Manager. research_protocol_design.py — fixed OI protocol proposal, curated static evidence, three model calls, zero tools, strict schema, advisory only; no execution or registration.

OI protocol v2 uses a second fixed host-only transport schedule (worker draft, optional supervisor critique). No plan call; saved draft remains available on review failure/decline. All paid confirmations via 1/0.

research_oi_readiness.py — separate source-readiness audit, latest 14 completed Fridays, checked Binance archives and approximate price unit check; unique local source record/report. Reuses oi_feature and source helpers without altering old parser/cutoff. No outcome data access for scoring or agent invocation.

Risk journal launcher also runs the independent OI readiness audit after successful forecast issuance; forecast code, receipts and ledgers unchanged. No OI model, no scoring, no additional agent.

research_oi_gate.py — registered synthetic OI-feature design diagnostic, daily price proxy paths, fixed rolling matched ridge fits, exact finite-path oracle, independent null calibration, reference checks and per-history uncertainty. No real data, paid calls or confirmation authorization. Metadata pilot only exports original approved IDs; extra local studies are not exported.

research_decision_sheet.py — offline presentation using verified DD-001, saved risk forecast and price source pages only. No fitting or new network, separate output, no journal mutation. Optional after existing risk launch; paid agent system deferred.

research_trend_recovery.py — fixed descriptive first-20%-drawdown episode comparison, daily MA50/MA200 level signals, next-open entry, equal budget/common terminal, separate post-entry new-low follow-up and explicit censoring. Reuses peak_history and pinned development prices; no fitting or forecast.

research_absorb.py — ABSORB-001, descriptive price response to executed spot selling. Reads the local checksum-verified Binance minute archive (bars before 2024 only), builds complete UTC hours without filling gaps, scales return and signed taker flow by the prior 28 days (flow also centred on its prior 28-day mean), and classifies weekly states point-in-time: standardized down week, and excess net taker flow orthogonal to the price move. `preflight` writes measurement-validity gates, coverage, covariate balance, a group-comparability gate and sample adequacy without any forward outcome; `outcomes` runs once, only with the reviewed preflight hash, unchanged data manifest and identical origins. No fitting of forecasts, network, LLM, journal or monitoring changes. See ABSORB_PROTOCOL.md.

- Отдельная исследовательская проверка `research_derivative_sources.py` / `run_derivative_sources.bat`: локальный спотовый архив, часовые архивы фьючерса и премии, фиксированная выборка дневных OI ZIP. Кэш и отчёт только в `data/research/derivative_source_v1/`; старые OI архивы читаются без изменения. Не связана с панелью, журналами или мониторингом.

- `research_derivative_panel.py` / `run_derivative_panel.bat` — отдельный фиксированный исторический набор на основе проверенного `source_audit.json`, повторное использование парсера OI и исходного кэша. `hourly_panel.json` содержит календарные UTC-часы и отдельные поля спота, perpetual, premium, OI :00/:55. `panel_coverage.json` связывает набор с исходными архивами и хэшами. Все данные локально, без изменений прогнозных журналов, панели или мониторинга.

- `research_delever.py` / `run_delever_preflight.bat`: DELEVER-001 fixed descriptive shock inventory, reads verified historical hourly panel and coverage, emits local preflight only. Separate study, no live signal or prediction integration.

- `hoplite_bridge.py`, `sync_hoplite.bat`, `import_hoplite.bat`: ручной мост Git между официальным публичным BTC-Lab и отдельной приватной копией владельца. Последний успешный адрес хранится в локальном remote `hoplite`, не в отслеживаемых файлах. Git Credential Manager и credential.useHttpPath на вызов; отдельный аккаунт для HTTPS копии. Sync отправляет точный SHA свежего origin/main только в main копии, без force, проверяет удалённый SHA. Import получает точную ветку, проверяет общую историю и входящие пути, сохраняет локальный патч истории, требует явного согласия на публичный push в новую review/hoplite/... ветку. Не исполняет код агента, не меняет checkout/main/журналы/мониторинг, не синхронизирует локальные данные. Проверка имён путей не является сканером секретов. Слияние только после отдельного ревью. Дорогие модели без Swarm.

- `market_state.py` / `run_market_state.bat`: независимый ручной read-only снимок из существующего публичного brief.json; переиспользует data_logic, сохраняет точные исходные байты и SHA-256, компактные именованные наблюдения с quality, scope, unit, observation/retrieval times, operational freshness limits. Не запускает LLM, не изменяет мониторинг или BUY/RISK. Первое практическое применение до расширения источников.

- `live_derivatives.py` / `run_live_derivatives.bat`: ручная проверка готовности официальных Binance BTCUSDT USD-M OI history и premium index за 28 дней, отдельный mark-price sanity check, ровно четыре bounded запроса, точные UTC timestamps, отчёт и хэши исходных ответов локально. Не подменяет корзину USD OI, не меняет market_state.py, мониторинг или журналы. Исторические исследования не открываются.

- `market_state.py` v2 переиспользует `live_derivatives.run` для четырёх прямых Binance запросов при ручном запуске; сохраняет исходные ответы под отдельным каталогом с хэшами и ссылкой на отчёт. Общий пакет имеет отдельное время сборки, каждый источник собственное время. Изменение OI по точным endpoints, отдельно покрытие; средняя премия и доля отрицательных часовых закрытий только на полном окне; при ошибках null. Без изменений коллектора btc-market-data, журналов или мониторинга.

- `local_runner.py`, `local_relay.py`, `browser_bridge/`: отдельный owner-installed pilot; fixed copies under ignored data/local_runner, dedicated private mailbox, immutable SHA source staging, bounded Docker execution, loopback authenticated one-event relay to explicit Brave chat and concise Telegram notifications. No remote shell, host credentials, automatic controller updates, historical data mounts, model/API automation or journal/monitor modifications. See LOCAL_RUNNER.md.

- Supersedes Docker pilot: local_runner.py is fixed Windows cloud status relay only, no subprocess or remote code execution. market_state_check.yml on explicit cloud_job.json push runs public research code with read-only permission, bounded runtime, public report/log artifact. Dedicated private mailbox maps exact commit to completed run; Brave and Telegram unchanged. See LOCAL_RUNNER.md.

- `sandbox_probe.py`, `sandbox_guest_probe.py`, `run_sandbox_probe.bat`: однократная owner-run readiness проверка без Docker. Скопированный stdlib runtime и конфигурация на D, offline Sandbox read-only архив Binance 1m и canary, единственная новая writable output папка. До 3 GiB free C preflight, 2 GiB warning floor (не hard quota); ручное закрытие первой сессии. SHA-256 одного ZIP и sidecar, без нового outcome research. Host execution of remote code remains forbidden. Local autonomous archive route pending actual compatibility check.

- local_sandbox.py / sandbox_archive_task.py: отдельный offline archive_check, точный current main SHA, два фиксированных исходных файла, read-only Binance 1m, отдельный output, фиксированный runtime, штатный wsb.exe own UUID lifecycle; fail-closed halt on uncertain stop. No remote host execution; cloud market_state retained. Windows CLI compatibility still unverified.
