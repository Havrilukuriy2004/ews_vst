# EWS Group Financials Package

Пакет містить технічне завдання, Excel-шаблон і кодові артефакти для збору, нормалізації та агрегації фінансової звітності групи клієнтів.

## Бізнес-вимога

1. Забрати фінансову звітність по двох компаніях / юридичних особах.
2. Для конкретного року застосувати конкретний matching: які ЄДРПОУ входять до групи саме у цьому році.
3. Скласти по групі wide-financials: сума всіх рядків фінзвітності за однаковою звітною датою та формою.
4. Зберегти Excel з:
   - company-level financials;
   - group-level aggregated financials;
   - full financials;
   - ratio / EWS-ready indicators;
   - transformation rules;
   - validation checks.

## Ключовий принцип

Фінансові рядки 1000...2650 агрегуються сумою по учасниках групи. Метадані не сумуються:
- КВЕД групи: основний КВЕД головної компанії або КВЕД компанії з найбільшою виручкою;
- Користувач / версія / дата збереження: ETL metadata;
- ЄДРПОУ групи: synthetic group id або список ЄДРПОУ;
- середня чисельність працівників: сума.

## Вміст архіву

- docs/TZ_Group_Financials_EWS.md — детальне ТЗ у текстовому Markdown-форматі.
- templates/*.csv — текстові CSV-шаблони із wide headers, matching, group aggregation inputs.
- sql/*.sql — SQL Server / Oracle / staging / aggregation scripts.
- python/build_group_financials.py — ETL skeleton.
- vba/ProcessReports_GroupAggregation.bas — VBA skeleton.
- data/field_codes_catalog.csv — каталог рядків фінзвітності.
- data/metric_mapping.csv — мапінг показників.
- extracted_sources/ — витягнуті VBA/SQL джерела з наданих Excel-файлів, якщо доступні.

Generated: 2026-05-18 08:09:02


## Реалізована автоматизація

Цей репозиторій містить завершений ETL-модуль `python/build_group_financials.py`, який читає CSV matching та raw wide financials (Excel підтримується локально, але binary-файли не зберігаються в репозиторії), будує normalized long staging, агрегує group-level financials і розраховує EWS-ready indicators. Детальний опис реалізації див. у `docs/IMPLEMENTATION_REPORT.md`.

Швидкий запуск для текстових CSV-шаблонів:

```bash
python python/build_group_financials.py \
  --matching templates/01_Group_Matching.csv \
  --raw-wide templates/02_Raw_Wide.csv \
  --out-long output/company_financials_long.csv \
  --out-group output/group_financials_long.csv \
  --output-dir output \
  --fail-on-check
```

Згенеровані CSV/JSON deliverables розміщуються в `output/`. Binary outputs навмисно не комітяться.


Повний локальний запуск (ETL + unit tests + перевірка текстових outputs):

```bash
./scripts/run_group_financials.sh
```

Після запуску формується `output/run_manifest.json` з параметрами запуску, застосованими правилами, кількістю рядків і статусами validation checks.


## Графічний dashboard і конектори до БД

Реалізовано dependency-free web dashboard на Python stdlib:

```bash
./scripts/run_dashboard.sh
```

Після запуску UI доступний локально: `http://127.0.0.1:8765/dashboard`. Dashboard показує group KPIs, company drill-down, validation, audit counts і readiness DB connectors.

Перевірка read-only конекторів до ClientProfile SQL Server та Oracle EWS:

```bash
./scripts/check_db_connections.sh
```

Конектори налаштовуються через приватний env-файл на базі `python/config.example.env`. У git зберігається тільки шаблон без секретів. Деталі production deployment описані в `docs/PRODUCTION_READINESS.md`.


### Зовнішні залежності для внутрішніх БД

Усі runtime-залежності для підключення до внутрішніх БД винесені окремо:

- `config/internal_db_dependencies.json` — machine-readable перелік внутрішніх БД, required DB objects, env vars, network ports, allowed/forbidden operations.
- `requirements-db.txt` — optional Python packages для live-підключень (`pyodbc`, `oracledb`, `openpyxl`).
- `scripts/check_internal_db_dependencies.sh` — перевірка dependency manifest, package availability, connector readiness і sanitized config.

```bash
./scripts/check_internal_db_dependencies.sh
```

Базовий CSV ETL і dashboard не потребують цих пакетів. Вони потрібні лише на production host з доступом до ClientProfile SQL Server / Oracle EWS.


## Обовʼязкова фактична вибірка 31.12.2025 / 01.01.2026

До пакета додано повний список 96 клієнтів, які мають бути включені на 100%:

- `data/mandatory_clients_2025.csv` — фактична обовʼязкова вибірка станом на `2025-12-31` з потенційною вибіркою на `2026-01-01`, включно з `ТОП/інші`, кодом клієнта, ЄДРПОУ та назвою.
- `data/group_directory.csv` — наданий довідник груп за ЄДРПОУ / назвою групи.
- `python/build_mandatory_matching.py` — генератор `templates/01_Group_Matching.csv`, який гарантує `inclusion_flag=1` для всіх 96 клієнтів і позначає unmapped entries для ручного уточнення групи.

```bash
python python/build_mandatory_matching.py \
  --mandatory data/mandatory_clients_2025.csv \
  --group-directory data/group_directory.csv \
  --out templates/01_Group_Matching.csv \
  --year 2025 \
  --expected-count 96
```

`templates/02_Raw_Wide.csv` також оновлено на 96 synthetic financial rows для повної перевірки ETL по всій обовʼязковій вибірці без production DB доступу.


## Чистий PR / generated outputs

Щоб pull request не конфліктував через великі згенеровані CSV/HTML/JSON, файли `output/*.csv`, `output/*.json`, `output/*.html` більше не комітяться. У git залишено тільки `output/README.md` з інструкцією. Усі outputs створюються локально командою:

```bash
./scripts/run_group_financials.sh
```
