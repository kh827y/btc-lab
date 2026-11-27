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
