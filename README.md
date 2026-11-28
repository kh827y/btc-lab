# BTC Lab
Личная лаборатория исследования BTC. Сейчас работает локальная BTC Market Panel v2; добавлен раздел «История» с графиками доступных архивов. Исторические исследования ещё не реализованы.

## Windows
- `start_windows.bat` — запуск панели.
- Перед обновлением кода закрой панель (Ctrl+C), запусти `update.bat`, затем снова `start_windows.bat`.
- Данные панели обновляются отдельно, автоматически.
- `import_panel.bat` — использовался для первоначального переноса; больше запускать не надо.

## Документация
- ARCHITECTURE.md — карта проекта.
- DATA.md — инвентаризация существующей истории и приоритеты.
- AGENTS.md — правила для ИИ-разработчиков.
- PANEL_README.md — инструкция исходной панели.

Публичный btc-market-data работает отдельно. Не хранить в Git ключи и большие локальные архивы. Новые модули добавляем только при практической необходимости.

## Дополнительные бесплатные данные
ETF TFTC открывается в разделе История без ключа. Для Kote Charts и Coinalyze запусти download_history.bat, введи существующие ключи в консоли (ввод скрыт). Enter пропускает источник. Ключи сохраняются в локальном data/provider_keys.json (обычный файл, не шифруется, игнорируется Git); не отправлять этот файл никому. Повторный запуск обновляет данные без повторного ввода. После загрузки нажми «Обновить сейчас» в панели. Данные лежат в data/extended, не отправляются в Git. Coinalyze — только конкретный Binance BTCUSDT perpetual; не заменяет корзину OI. Kote — только личное некоммерческое исследование с указанием источника. Funding пока в исходных единицах API, не нормализован.

## Накопление и проверка
При открытой панели скользящие архивы OI/CVD/опционов накапливаются локально (data/history.sqlite3, примерно каждые 30 минут; закрытая панель ничего не скачивает). Раздел «Качество истории» → «Проверить все исторические ряды» показывает покрытие. download_history.bat теперь также загружает дневную цену и CVD Binance без ключа и сохраняет старые даты дополнительных архивов. Это отдельный рынок; полная история пятибиржевого CVD пока недоступна. Архивы не являются point-in-time данными для бэктеста.

Раздел «История стаканов» — 9 отдельных рынков, 4 полосы, сопоставимые снимки, причины отсутствия глубины. После обновления повтори download_history.bat для исправленного Binance; повреждённые дни будут явно обозначены.

## Минутная история для исследований
После update.bat запусти download_minutes.bat. Бесплатные официальные ZIP Binance BTCUSDT spot сохраняются в data/binance_1m, повторный запуск использует проверенные файлы. Отчёт audit.json перечисляет пропуски и ошибки; начало — 17.08.2017, конец — последний закрытый день UTC. Если архив месяца ещё не опубликован, скачиваются дневные файлы. Можно проверить один день: download_minutes.bat --start 2024-01-01 --through 2024-01-01. Код готов к проверке, фактическое покрытие локальной истории определяется после запуска. Не требуется API-ключ.

Если первый запуск отверг старые месяцы Binance из-за временных границ, обнови код и повтори download_minutes.bat без --refresh. Ранее принятые архивы остаются; нестандартные свечи исключаются поштучно без искусственного восстановления. После повторного запуска проверь audit.json: errors, missing_or_unavailable, rejected_rows. Ненулевые пропуски возможны даже при успешной загрузке всех архивов.

## Первое исследование: подготовка CPI
После update.bat запусти prepare_cpi.bat. Скрипт ищет оригинальный проверенный ZIP BTC-Lab_US_CPI_2018-01_2026-11 в Downloads или data/; можно перетащить ZIP на prepare_cpi.bat. Архив и все производные данные остаются локально. Скрипт проверяет исходные хэши и фактически читает проверенные минутные ZIP из audit.json. При завершении отправь только data/research/cpi/coverage.json, не CSV итогового периода. Это подготовка данных, не бэктест. Никаких API-ключей и запросов к моделям.

После успешного prepare_cpi.bat и проверки coverage.json запусти run_cpi_development.bat. Не обновляй исходный архив перед этим; версия данных закреплена. Пришли только data/research/cpi/development_report.json. Итоговые CSV не открываются этим скриптом; вывод на 2022–2023 не является независимым тестом.

### Миграция после аудита Opus
После update.bat повтори prepare_cpi.bat **один раз**, не запускай заново download_minutes.bat. Из исходного audit.json сохраняется отдельный price_snapshot.json с идентификатором содержимого, независимым от cached/downloaded_utc. При последующих обновлениях минутного архива исследование использует закреплённый список ZIP. Сверяются все восемь исходных train/development CSV с предыдущими хэшами. Только после успешной сверки автоматически удаляются четыре ранее сгенерированных test CSV (не исходные архивы и не development_report.json). Новые test CSV не создаются. При иной версии или изменении данных программа останавливается, не перезаписывает завершённое исследование. Пришли обновлённый coverage.json. Отдельного финального запуска пока нет; итоговые исходы не открывать.

### Проверка устойчивости CPI
После успешной миграции и update.bat запусти run_cpi_diagnostics.bat. Пришли data/research/cpi/development_diagnostics.json. Скрипт читает только проверенные train/development, не изменяет старый отчёт и не открывает test. Повторная подготовка не нужна.

### Независимая сверка CPI
После update.bat запусти run_cpi_coinbase.bat. Скрипт запрашивает только необходимые дневные и минутные свечи Coinbase BTC/USD на 70 уже известных датах (до 2024), без ключа, кэширует ответы с хэшами; сравнивает цену/реакцию и повторяет неизменные модели на общих датах. При сетевой ошибке повторный запуск использует успешно сохранённые ответы. Пришли data/research/cpi/coinbase_development_report.json либо текст ошибки. Не скачивает весь Kraken, не открывает test.

### Проверка контрольных окон CPI (часть A)
Запусти run_cpi_calendar.bat после update.bat. Скачиваются семь небольших списков дат ALFRED, кэш локальный, никаких ключей. Скрипт проверяет только 2018–2023, исключает контрольные дни с зарегистрированными публикациями из выбранных семейств, считает равновзвешенное описательное сравнение реакции. Пришли data/research/cpi/calendar_development_report.json. Это консервативная проверка дат, не полный календарь новостей и не доказательство причинности.

### Единственный итоговый запуск CPI
После update.bat запусти run_cpi_final.bat. Скрипт проверяет committed lock и неизменность протокола/кода, использует оригинальный CPI ZIP и закреплённые архивы; никаких новых Binance загрузок. При необходимости можно перетащить CPI ZIP на bat. Итоговые CSV не создаются, сохраняется один локальный data/research/cpi/final_report.json. Coinbase сверяется на новых датах через публичный API; при недоступности сохраняется основной результат с ограничением. Пришли final_report.json. Повторный запуск после появления отчёта запрещён. См. CPI_FINAL.md.


**Статус CPI-001: завершён 27.11.2026.** Итоговый отчёт уже получен; `run_cpi_final.bat` больше запускать не требуется. Сохранить `final_report.json`, исходные архивы и кэши локально. Выводы и дальнейшие действия — ROADMAP.md. Код и протокол зафиксированного финала оставлены без изменений.

## Перспективный журнал (первая версия)
`run_forecast_journal.bat` проверяет завершившиеся исходы и формирует один базовый прогноз на следующую полночь UTC, не чаще одного на ISO-неделю целевой даты. Регулярный запуск в воскресенье UTC (понедельник 00:00 UTC начало прогноза), первый внеплановый запуск допустим и помечен. Горизонты 7/28/90 дней (28 вместо 30 для согласованности с будущим BUY-001). Источник — Binance BTCUSDT spot, только закрытые дневные свечи за 1000 суток, публичные endpoints без ключей. Эмпирические вероятности положительного исхода и потери от входа не менее 15%, квантили 10/50/90%, дневная log-волатильность. Простой нулевой прогноз — ориентир ошибки доходности. Перекрывающиеся прошлые окна не независимы. Исход open-to-open, минимум дневных low и конечного open, оценка после закрытия конечного дня. Записи и данные отдельно в data/research/forecast/<дата>/, не перезаписываются. Пришли только forecast.json и его SHA256 из консоли **до начала окна**. Внешняя отметка получения — отдельный комментарий в одном приватном GitHub Issue, только дата начала, версия и хэш, без сырых цен. Скрипт не отправляет ничего в GitHub; серверное время Binance не доказывает получения прогноза. До проверки created_at и неизменности комментария запись локальная, не независимо закреплённая. Не восстанавливать пропущенные выпуски. Пока не автоматизировано, не торговый сигнал.

## Дневная история BTC/USD для BUY-001
`download_daily_usd.bat` после update.bat — фиксированный снимок закрытых дневных OHLCV: Bitstamp BTC/USD с 01.01.2014, Coinbase BTC/USD с 20.07.2015, до 27.11.2026 UTC (не включительно). Без ключей; отдельно по рынкам, без склейки, интерполяции и расчёта будущих доходностей. Кэш оригинальных ответов с SHA-256; повторный запуск переиспользует страницы, при сетевой ошибке продолжит с недостающих. CSV и coverage.json в data/research/daily_usd_v1/ (игнорируется Git). Завершённый CSV не перезаписывается другими данными; при недостаточном покрытии показать ограничения и решить отдельно. Пришли coverage.json; фактическое покрытие ещё проверяется. CPI и журнал не изменяются.

## BUY-001 development
Обе дневные истории успешно получены, повторная загрузка не нужна. `update.bat`, затем `run_buy_development.bat`. Только 2014–2023 для подготовки и оценки, отдельные Bitstamp/Coinbase, фиксированные хэши; 2024+ численные значения не разбираются. Пять правил покупки и M0/M1 риска, условные интервалы, варианты, полный локальный отчёт `data/research/daily_usd_v1/buy_development_report.json`. Пришли этот отчёт. См. BUY_PROTOCOL.md. Итоговая команда пока отсутствует.

### BUY-001: дополнительная проверка риска
`run_buy_risk.bat` после update.bat. Не повторяет скачивание, не меняет исходный отчёт. Добавляет проверку вероятностей по тренду/просадке/доходности, сравнение с волатильностью и простым отложенным DCA, условную доходность cash. Пришли data/research/daily_usd_v1/buy_risk_extension_report.json. Только development; итоговые цены не разбираются.

### BUY-001: контроль после аудита Opus
После update.bat запусти run_buy_audit.bat. Скрипт повторяет только development extension, сверяет числа с предыдущим отчётом, добавляет контроль смещённых графиков покупки и прямое сравнение моделей. Пришли data/research/daily_usd_v1/buy_audit_controls_report.json. Старые отчёты сохраняются. Не запускать финал; его команды пока нет. Журнал BUY-001 отдельно согласуем после проверки.

### BUY-001: перспективный журнал
`run_buy_journal.bat` в воскресенье UTC до 23:50, первый origin 30.11.2026 00 UTC. Bitstamp BTC/USD, закрытая субботняя свеча, общие функции baseline/extension, 28d, бумажные решения на всех восьми слотах. Пришли forecast.json из data/research/buy_journal/<Monday>/ до Monday 00 UTC; SHA-256 фиксируется новым комментарием в приватном issue #2 и tracked buy_journal_receipts.json, затем update.bat для получения ledger. Сам скрипт GitHub не пишет. Без своевременного receipt выпуск считается unanchored/missed, не включается в prospective оценку. При потере закреплённого файла не переиздавать. Исходы автоматически при следующих ручных запусках: 28d и полные восьминедельные когорты только при восьми закреплённых выпусках. Не запускать до воскресенья. Старый Binance журнал отдельный. Никаких торговых сигналов/новой автоматизации.

### BUY-001 финал
После update.bat запусти run_buy_final.bat один раз; пришли data/research/daily_usd_v1/buy_final_report.json. Требуются прежние три отчёта и два CSV. Проверка committed lock до чтения финальных цен, локально, без повторной загрузки. Старые development entrypoints сохраняют guards. См. BUY_FINAL.md. Новый BUY-журнал не требует запуска до воскресенья.


**BUY-001: исторический финал завершён.** Повторный запуск `run_buy_final.bat` не нужен; сохранить отчёты, данные и контрольные суммы. Результаты и ограничения в ROADMAP.md. Журнал BUY запускается отдельно каждое воскресенье UTC. Батники завершённых экспериментов можно позднее организовать в папке с исправлением рабочих путей; пока не удалять вручную.

### FLOW-001 development
`update.bat` затем `run_flow_development.bat`. Скачивает только несколько страниц дневной истории Binance до 2024, использует существующие USD CSV и прежние функции BUY. Прислать `data/research/flow_v1/flow_development_report.json` (при ошибке покрытия — coverage.json). Никаких ключей, новых зависимостей или повторной загрузки BTC history. См. FLOW_PROTOCOL.md. Отчёт не перезаписывается; исходные BUY/CPI не менять.

### VALUE-001
`update.bat`, затем `run_value_development.bat`. Использует data/extended/kote-mvrv.json и имеющиеся USD CSV; без API ключей, без загрузки или изменений исходных архивов. Пришли data/research/value_v1/value_development_report.json, при проблеме покрытия coverage.json; если отсутствует Kote файл — текст ошибки. FLOW-001 завершён development, не повторять. См. VALUE_PROTOCOL.md.

### FUND-001
После update.bat запусти run_fund_development.bat. Загружает небольшие месячные Binance funding ZIP и CHECKSUM, использует прежние USD CSV. Пришли data/research/fund_v1/fund_development_report.json, при ошибке покрытия — coverage.json. VALUE development завершён, MVRV остаётся кандидатом для дополнительной проверки. См. FUND_PROTOCOL.md. Ключи не нужны.

### OI-001
`update.bat`, `run_oi_development.bat`. Скачивает только пятничные Binance metrics ZIP/checksums, использует уже полученный funding_snapshot.json и USD цены. Пришли data/research/oi_v1/oi_development_report.json, при ошибке покрытия — coverage.json или текст ошибки. Первичная загрузка примерно 174 небольших ZIP с проверками, не требуются API keys. FUND development завершён. См. OI_PROTOCOL.md.

### MACRO-001
`update.bat` затем `run_macro_development.bat`. Два небольших публичных CSV FRED, прежние BTC USD snapshots; без ключей/новых зависимостей. Пришли data/research/macro_v1/macro_development_report.json (при ошибке coverage.json или текст). OI development завершён, не повторять. См. MACRO_PROTOCOL.md.


MACRO timeout recovery: update.bat and rerun run_macro_development.bat. Automatically tries FRED/ALFRED and FRED once more, keeps successful cache. If all requests fail, coverage.json contains exact official CSV URLs; save CSV to data/research/macro_v1/manual/DFII10.csv or DTWEXBGS.csv (FRED), or DFII10_20261125.csv / DTWEXBGS_20261125.csv (ALFRED), then rerun. Don't rename a different series or edit values. Send coverage.json if unsuccessful.

### COMB-001
`update.bat`, `run_comb_development.bat`, send data/research/comb_v1/comb_development_report.json. Uses existing MVRV/OI/funding snapshots and pinned daily USD prices. No new downloads or keys. Development only, post-selection exploratory; see COMB_PROTOCOL.md. MACRO finished, no rerun.

**COMB-001 development завершён.** Результат в ROADMAP.md. Не повторять расчёт и не подбирать параметры. Сохранить исходные snapshots и report. На данном этапе нужен независимый аудит исследовательской программы, а не очередная выгрузка. Журнал BUY по-прежнему отдельный перспективный эксперимент.

### Новый этап после аудита Fable
См. RESEARCH_POLICY.md / RESEARCH_REGISTRY.json. Новых запусков скрининга не требуется. Первый BUY journal — 29.11.2026 UTC, отправить forecast.json до 30.11 00:00 UTC. Далее новый descriptive drawdown/recovery protocol и synthetic checker; пока не реализованы. Не удалять старые данные и отчёты.

### DD-001
`update.bat`, `run_drawdown.bat`, пришли `data/research/drawdown_v1/drawdown_report.json`. Uses existing pinned BTC/USD CSVs, no downloads, no keys. Descriptive only; see DD_PROTOCOL.md. BUY journal unchanged.

### GATE-001
DD completed. `update.bat`, `run_synthetic_gate.bat`, send `data/research/gate_v1/synthetic_gate_report.json`. Synthetic only; no data/API keys; calculation may be slower than descriptive reports. No new real-market study authorized by this diagnostic. See GATE_PROTOCOL.md.

### RISK-001
GATE-001 did not pass; preserve report, do not rerun. `update.bat`, `run_risk_reference.bat`, send `data/research/risk_reference_v1/risk_reference_report.json`. Existing price snapshots only. Descriptive calibration on development history, no new confirmation or trade rules. See RISK_REFERENCE_PROTOCOL.md.

### RISK-journal-v1
RISK-001 diagnostic completed. Sunday 29 Nov UTC: after update.bat run original run_buy_journal.bat (unchanged), then run_risk_journal.bat. Send both data/research/buy_journal/2026-11-30/forecast.json and data/research/risk_journal/2026-11-30/risk_forecast.json before Monday 00 UTC, separate receipt hashes. Keep source files locally. Later .venv\\Scripts\\python.exe risk_journal.py settle / status (separate commands). No backfill. No new factor confirmations.

### DVOL-001
`update.bat`, `run_dvol.bat`, send `data/research/dvol_v1/dvol_report.json` (or coverage.json on error). Small public Deribit daily archive, no API key, existing BTC/USD data. Data audit and descriptive benchmark only; see DVOL_PROTOCOL.md. Existing journal launch dates unchanged.

### Bounded research tools (local, no AI)
DVOL completed. After update.bat, from the project folder use `.venv\Scripts\python.exe research_tools.py registry`, `study DVOL-001`, `report_integrity DVOL-001`, or `journals` (same command prefix). All read-only. No new downloads or paid calls. No arbitrary file paths accepted. No autonomous agents yet. BUY/RISK Sunday issuance unchanged.

### Агентный контроллер v1
После update.bat: `.venv\Scripts\python.exe research_controller.py --dry-run`. Тестовые ответы, 4 локальные read-only операции, никакой сети или расходов. Реальные модели пока не подключены; см. AGENT_CONTROLLER.md.

### Первый реальный API pilot
`update.bat`, `run_agent_smoke.bat`, y, затем ключ скрыто в консоли. Только вымышленные данные, не реальные журналы или архивы. Пришли новый JSON из `data/research/agent_smoke/` и изменение баланса, не ключ. При ошибке не повторяй. 200000 — расчётный резерв базовых токенов, не гарантия списания. См. AGENT_CONTROLLER.md.

Тариф аккаунта уточнён после первого успешного pilot: x5 при output > input; в резерве x5 для обеих моделей. Повторный тест не нужен. Реальные данные пока не передаются.

### Проверка реальных метаданных
`update.bat`, `run_agent_review.bat`. Сначала показывается точный ограниченный снимок данных, затем y для разрешения передачи и платного запуска; ключ вводится скрыто. Без согласия сеть не используется. Прислать JSON из `data/research/agent_review/` и списание. Только статусы/итоги GATE/целостность без хешей/счётчики журналов. Без файлов, терминала, прогнозов и новых исследований. Для просмотра без оплаты: `.venv\Scripts\python.exe research_metadata.py --preview`. См. AGENT_CONTROLLER.md.

Подтверждение `y`; первый ввод ключа сохраняется в диспетчере учётных данных Windows. Следующие запуски используют сохранённый ключ. Удалить: `.venv\Scripts\python.exe research_credentials.py --forget`. Заменить: `.venv\Scripts\python.exe research_metadata.py --live-review --replace-key`. Повторять metadata pilot не нужно.

### Актуально: локальный ключ и черновик OI-протокола
Вместо Windows Credential Manager используется `data/.cheapvibecode_key` (открытый текст, игнорируется Git). `update.bat`, `run_agent_protocol.bat`, `y`, при первом запуске ключ. Пришли JSON из `data/research/agent_protocol/`. Не отправляй файл ключа. Резерв 300000, не гарантированный расход. Только проект протокола, без запуска исследования. `--preview` без сети.

**Актуально:** подтверждение `1`, отказ `0` (или Enter). `update.bat`, `run_agent_protocol.bat`: DeepSeek draft, затем отдельное предложение платной критики Sol. Можно отказаться и прислать черновик из `data/research/agent_protocol/` для ручной проверки. Старый запуск не повторять. Резерв 200000, не гарантия списания.

### OI source readiness
Agent protocol v2 reviewed; do not repeat paid pilot. `update.bat`, `run_oi_readiness.bat`, send `data/research/oi_readiness_v1/<UTC-run>/oi_readiness_report.json`. Public data only, no API key or LLM. No market scoring or new forecast. Existing BUY/RISK journal schedule unchanged; see OI_FOLLOWUP_DRAFT.md.

### OI source readiness follow-up
First audit 14/14 passed, but latest completed Friday was Nov 20 (run before Nov 27 UTC close). For Nov 29: existing `run_risk_journal.bat` now runs independent OI availability check **after** saving risk forecast; no extra command or paid API. Send BUY and RISK forecast files before Monday 00 UTC even if OI fails; also send the new `oi_readiness_report.json` if produced. Do not send local key or raw archives. Forecast generation and anchoring unchanged.

### OI-GATE-001
`update.bat`, `run_oi_gate.bat`; send `data/research/oi_gate_v1/oi_gate_report.json`. If stopped, send console error and `oracle_preflight.json` if present. Fixed synthetic diagnostic, no real market data or keys; no repeat for pass. Existing Sunday journals unchanged. See OI_GATE_PROTOCOL.md.

OI-GATE-001 completed, failed overall at every sample size. Do not rerun. No additional bat needed now; Sunday BUY/RISK issuance unchanged. See ROADMAP.md.

### Текущий план: таблица решений
После аудита Fable исторический OI закрыт; новых gate/платных запусков не нужно. В воскресенье update.bat, run_buy_journal.bat, run_risk_journal.bat как прежде. Последний дополнительно создаёт data/research/decision_sheet/<origin>/decision_sheet.md из существующих данных, без платного API. Пришли оба forecast JSON вовремя; OI report и decision_sheet.md если созданы. DVOL пока отдельно. Не откладывай отправку прогнозов из-за дополнительных таблиц.

### TREND-001: подтверждение или покупка просадки
update.bat, run_trend_recovery.bat. Пришли data/research/trend_recovery_v1/trend_recovery_report.json. Только прежние цены до 2024, без сети и платных моделей. Сравнение на одинаковом капитале и 90-дневном горизонте; отсутствие подтверждения означает кэш. Воскресние журналы без изменений.

### Ранняя история BTC и проверка OHLC
После update.bat запусти run_early_history.bat. Четыре небольших запроса к официальному Bitstamp BTC/USD за 2011-08-18–2014-12-31, без ключей, сохраняют отдельный кэш. Сверяются все совпадающие строки 2014 года с закреплённым рядом, проверяются необычные экстремумы Bitstamp/Coinbase до 2024 года. Пришли `data/research/early_usd_v1/early_history_report.json`. Никакой перезаписи исходных CSV, заполнения пропусков или новых бэктестов. При проблемах с сетью повторный запуск использует проверенный кэш.

### Расширенные описательные исследования (2012–2023)
После успешного раннего аудита и update.bat запусти run_extended_description.bat. Скрипт сверяет хэши двух файлов Bitstamp и все 365 общих строк за 2014 год, пересчитывает неизменные методы DD-001 и TREND-001 на более длинном ряду. 2011 остаётся в архиве, но не участвует в расчётах. Отчёт новый, старые не меняются. Пришли data/research/extended_description_v1/extended_description_report.json. Интернет и ключи не нужны. Не запускай повторно после успешного создания отчёта.

### Актуальный DVOL
После update.bat запусти run_dvol_context.bat для проверки последнего закрытого дня UTC. Пришли data/research/dvol_context/<дата из консоли>/dvol.json. Ключи не нужны. Еженедельная таблица после run_risk_journal.bat теперь дополнительно пытается получить DVOL за субботу UTC; отсутствие данных не отменяет сохранённый риск-прогноз. Сохранённые таблицы не перезаписываются. DVOL — годовая опционная волатильность 30-дневного горизонта и соответствующий масштаб колебаний, не вероятность падения или ценовой коридор. Не откладывай отправку журналов ради DVOL.

### TREND-002: проверка восстановления нарушенного тренда
После update.bat запусти run_trend_break_preflight.bat. Отправь data/research/trend_break_v1/trend_break_preflight.json. Использует уже скачанную историю, без интернета и ключей. Сначала считает эпизоды, даты входа и перекрытие окон, не доходность или риск. Старые исследования и журналы не изменяются.

### TREND-002: сравнение покупки после нарушения тренда
После успешного preflight и update.bat запусти run_trend_break_comparison.bat. Скрипт проверит хэш рассмотренного preflight, повторит его расчёт дат и сравнит четыре заранее заданных способа покупки на общей дате оценки. Отправь data/research/trend_break_v1/trend_break_comparison.json. Интернет и ключи не нужны; старые отчёты не перезаписываются.

### EVENT-FACT-001: документы ФРС
После update.bat запусти run_fomc_packages.bat. Скрипт скачивает официальные документы для восьми заседаний 2023 года, проверяет время публикации, сохраняет оригиналы и извлекает тексты без поздних материалов. Пришли data/research/event_fact_v1/fomc_2023_packages.json либо отчёт incomplete_*.json по пути из консоли. Нужен интернет, API-ключи не нужны. Полный файл не передавай тестируемой модели: для неё будет подготовлен отдельный пакет одного события.

### ABSORB-001: реакция цены на исполненные продажи
**Завершено; результат неопределённый.** Повторно запускать исследование не нужно. Код и инструкции ниже сохранены для воспроизводимости, не для текущих рекомендаций.

Описательное исследование: отличается ли цена ожидания (купить через 7 дней вместо сейчас) после недель падения, когда продавцы «по рынку» продавали больше обычного для такого падения, и недель, когда цена падала почти без таких продаж. Это не прогноз и не торговое правило; слабая реакция цены на продажи не доказывает устойчивый спрос. Методика заморожена в ABSORB_PROTOCOL.md до просмотра будущих цен.

1. После update.bat запусти `run_absorb_preflight.bat`. Используется уже скачанная минутная история Binance (data\binance_1m) только до 31.12.2023, без интернета и платных вызовов; чтение архива занимает несколько минут. Скрипт проверяет, что измерение осмысленно и что наблюдений достаточно, и **не считает будущие цены**. Пришли `data/research/absorb_v1/absorb_preflight.json` и показанный SHA-256.
2. Только после проверки preflight: `run_absorb_outcomes.bat`, вставь SHA-256 проверенного файла. Запуск один; результат — `data/research/absorb_v1/absorb_outcomes.json`. Если preflight не разрешает (`outcomes_permitted: false`), второй шаг откажется работать.

### Проверка источников спот/деривативы
После `update.bat` запусти `run_derivative_sources.bat` и пришли `data/research/derivative_source_v1/source_audit.json`. Нужен интернет, ключи не нужны. Используется локальная минутная история спота, скачиваются часовые свечи бессрочного BTCUSDT USD-M и индекс премии (сентябрь 2020 — декабрь 2023), а OI проверяется только за первый день каждого месяца. Это проверка доступности и качества данных, не новый сигнал или расчёт будущей доходности. Существующий отчёт не перезаписывается.

### Полная часовая история спота и деривативов
После успешной проверки источников и `update.bat` запусти `run_derivative_panel.bat`. Скачиваются недостающие дневные архивы OI за 01.09.2020–31.12.2023 (1217 дней), ранее полученные архивы используются повторно. Интернет нужен, ключи не нужны. Пришли только `data/research/derivative_source_v1/panel_coverage.json`; большой `hourly_panel.json` оставь локально. Программа проверяет контрольную сумму рассмотренного source_audit.json, повторяет проверку исходных данных и не заполняет пропуски. Это сбор данных, не исследование доходности. Не перезапускать готовый сбор и не удалять отчёты. Выпуск BUY/RISK имеет приоритет.

### DELEVER-001: резкие падения и сокращение OI
После `update.bat` запусти `run_delever_preflight.bat` и пришли `data/research/derivative_source_v1/delever_preflight.json`. Используются готовые локальные файлы, без интернета и ключей. Только фиксированные эпизоды и их сопоставимость; будущие доходности не считаются. Отдельное разрешение после проверки, см. DELEVER_PROTOCOL.md. Выпуск BUY/RISK имеет приоритет.

### DELEVER-001: расчёт после рассмотренного preflight
После `update.bat` запусти `run_delever_outcomes.bat`. Разрешён только рассмотренный preflight с закреплённым SHA-256; программа повторно сверяет календарь, эпизоды и исходные хэши. Отправь `data/research/derivative_source_v1/delever_outcomes.json`. Интернет и ключи не нужны. Повторный запуск не перезаписывает отчёт. Это описательное сравнение стоимости ожидания и риска, не торговое правило.

DELEVER-001 завершён как описательное исследование. Повторно запускать не нужно. Результаты сохранены в реестре и ROADMAP; OI — контекст, не доказанный сигнал покупки. Следующий этап — методологический синтез накопленных исследований. Замороженные BUY/RISK журналы продолжаются.

### Внешние модели Hoplite: перенос между репозиториями
Основной репозиторий `kh827y/btc-lab` — единственный источник проекта. Временная приватная копия подключена к Hoplite. Помощник сообщает, какой файл запускать на каждом этапе.

- Перед задачей Fable/Opus: `update.bat` (если есть обновления), затем `sync_hoplite.bat`. При первом запуске вставь HTTPS-ссылку приватной копии, затем `y`; позднее Enter сохраняет последний адрес, новый URL меняет его после успешной синхронизации. Вход в GitHub при необходимости — через обычный Git Credential Manager; токены не вставлять в URL или чат. `SYNC OK` и SHA отправь помощнику. Агент должен читать именно актуальный main приватной копии, а правки делать в отдельной ветке.
- Если агент только исследовал и не изменял код, импорт не нужен. Если разработал код, запусти `import_hoplite.bat`, введи точное имя его ветки. Программа проверяет общую историю, показывает коммиты и создаёт локальный `data/hoplite_review/<SHA>.patch` со всеми входящими патчами. Основной GitHub публичный: прежде чем вводить `PUBLISH`, убедись, что в коммитах, включая промежуточные, нет приватных данных или секретов; если не уверен, отмени и проверь патч локально (не отправляй секреты в чат). Ограниченная проверка имён файлов не гарантирует отсутствие секретов. После подтверждения переносится только ветка `review/hoplite/...`. Отправь помощнику строку `IMPORT OK` с именем ветки и SHA. Если ветка уже существует с другим SHA, остановись и пришли ошибку. Не запускай код агента до проверки. После одобрения и объединения помощником — `update.bat`.

Скрипты не переключают рабочую ветку, не объединяют ветки, не используют force push и не добавляют локальные данные в Git. GitHub Actions существующего main не меняются. Если синхронизация отклонена из-за расхождения истории, не применяй force push, пришли ошибку. Swarm для Fable/Opus не использовать; задания и отчёты только на английском.

### Первый ручной пакет состояния рынка
После `update.bat` запусти `run_market_state.bat` в любой день. Отправь `market_state.json` по пути из консоли. Исходный публичный brief.json сохраняется рядом в `data/research/state_packets/<UTC>/`, не отправляется в Git. Нужен интернет, ключи и LLM не нужны. Пакет выбирает факты по цене, споту, ETF, деривативам, опционам, держателям и макро; пропуски и неподходящие значения остаются null с причинами. Время измерения отдельно от времени загрузки; ограничения свежести предварительные, не сигналы. Котировки и OI в единицах источника, разные корзины CVD не подменяются. Пока нет сверки ожидаемых ETF/макро-сессий, новостей и истории изменений между пакетами. Нет изменений существующего мониторинга или журналов.

### Проверка OI в количестве BTC и премии perpetual
После `update.bat` запусти `run_live_derivatives.bat`. Пришли `derivatives_readiness.json` по пути из консоли, даже если есть ошибки. Четыре публичных запроса Binance (две страницы OI, mark price и premium index), ключи не нужны. Точные часовые границы за 1/7/28 дней, пропуски не заполняются. Проверяется отношение стоимости к количеству относительно диапазона mark price; при несоответствии точка исключается. Только Binance USD-M BTCUSDT perpetual, отдельно от пятибиржевого USD OI. Премия — индекс, не funding и не исполненный basis. Пока отдельная проверка источников, не интеграция в пакет; исходные ответы локально. При сетевой блокировке не менять настройки VPN ради скрипта, прислать отчёт.

### Market state v2
Проверка Binance завершена. Теперь `run_market_state.bat` сам собирает OI Binance BTCUSDT perpetual в BTC и премию за 1/7/28 дней, отдельным блоком `binance_perpetual`. Отдельный запуск `run_live_derivatives.bat` больше не требуется для обычного пакета. Пришли `market_state.json`; исходные ответы и отчёт сохраняются рядом локально. Независимые времена наблюдений, покрытие и ошибки указаны явно. При отказе Binance остальной пакет сохраняется, недоступные значения null. Не смешивать с пятибиржевым OI USD.

### Локальный исполнитель (Docker)
См. LOCAL_RUNNER.md. Docker Desktop и основное хранилище WSL на D. GitHub Actions для публичных проверок, offline Docker для локального archive_check. Windows Sandbox удалена из актуального кода. После установки Docker и проверки расположения диска: update.bat, setup_local_runner.bat. Фиксированный Brave/Telegram relay, никаких автоматических запусков нового Python на хосте. Полный цикл ещё не проверен.

### Market state v3
Добавлен контекст спроса: последние 24 часа и предшествующие 144 часа по каждой фиксированной корзине отдельно; число положительных/отрицательных из пяти опубликованных ETF-сессий. Не является сигналом, не доказывает широту спроса. Несопоставимые окна остаются null. Облачный тест Binance Futures ранее получил HTTP 451, поэтому отдельный блок quantity/premium может оставаться недоступным. Не подменять данные и не изменять мониторинг. Первый сквозной Docker/Brave тест archive-probe-003 успешен; автономная работа длительными сериями ещё не проверена.

### Market state v4
Независимый блок direct_macro: DFF, DGS2, DGS10 и DTWEXBGS из официальных CSV FRED, резервная попытка через ALFRED того же ряда. Дата наблюдения и загрузки отдельно; изменение за 7/28 дней относительно последнего опубликованного наблюдения, без заполнения пропусков. Для недельного H.10 отдельный предел свежести. Исходные CSV сохраняются рядом с пакетом. Исходные макрополя мониторинга не заменяются. Фактическая доступность нового блока проверяется облачным заданием.

### Market state v5
FRED/ALFRED недоступны из облака (все восемь запросов по тайм-ауту). Новый direct_macro получает EFFR по рабочим дням из NY Fed (не подменяет DFF), 2/10-летние номинальные доходности из Treasury XML, широкий доллар из H.10 ФРС. Отдельные идентификаторы/источники, без заполнения пропусков. Реальная доступность проверяется облачным заданием.

### Market state v6
Контекст широты спотовых покупок/продаж по существующим часовым данным: семь неперекрывающихся 24-часовых блоков, суммы по каждой бирже и число положительных/отрицательных бирж и дней. Строго фиксированные корзины, проверка часов, Coinbase ID proof и согласование с исходным CVD; пропуски не заполняются. Не сигнал покупки. Локальные тесты через Docker теперь основной способ проверки; облачная полная CI запускается вручную, сетевой сбор — отдельно.
