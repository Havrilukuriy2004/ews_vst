# Implementation report: EWS Group Financials

## Що реалізовано

1. **Excel/CSV ETL для групової фінзвітності** — `python/build_group_financials.py` читає matching та raw wide financials, нормалізує їх у long staging, агрегує групу та формує EWS-показники.
2. **Year-specific matching** — ключ matching: `matching_year + edrpou`; `edrpou` завжди обробляється як рядок.
3. **Правила консолідації**:
   - `inclusion_flag=1` — компанія входить до групи;
   - рядки фінзвітності `1000...2650` — `SUM`;
   - середня чисельність працівників — `SUM`;
   - КВЕД — головна компанія (`is_main_company=1`) або компанія з найбільшою виручкою;
   - metadata — ETL metadata, не сума.
4. **EWS-ready indicators**:
   - Revenue and revenue growth;
   - Gross profit;
   - EBIT / EBITDA / EBITDA margin;
   - NIE, net income;
   - Net Debt / EBITDA;
   - ICRm;
   - DSO, DIO, DPO and Financial Cycle;
   - average capital need.
5. **SQL layer**:
   - staging tables;
   - ClientProfile read-only extraction examples;
   - group aggregation by matching year;
   - group indicator views;
   - validation checks.
6. **Generated deliverables** in `output/`:
   - `company_financials_long.csv`;
   - `group_financials_long.csv`;
   - `group_financials_wide.csv`;
   - `financial_indicators.csv`;
   - `validation_report.csv`.

## Як запускати

```bash
python python/build_group_financials.py \
  --matching templates/01_Group_Matching.csv \
  --raw-wide templates/02_Raw_Wide.csv \
  --out-long output/company_financials_long.csv \
  --out-group output/group_financials_long.csv \
  --output-dir output \
  --fail-on-check
```

CSV-шаблони містять synthetic demonstration values для перевірки формул, агрегації та валідаторів. Binary workbook/docx/zip файли навмисно не зберігаються у репозиторії.



## One-command run

```bash
./scripts/run_group_financials.sh
```

Скрипт виконує end-to-end ETL, запускає unit tests та перевіряє наявність/валідність згенерованих CSV/JSON outputs. Для аудиту кожного запуску формується `output/run_manifest.json` з правилами консолідації, counts та validation statuses.

## Validation checklist

- Unmatched EDRPOU by `matching_year + edrpou`.
- Duplicate company report keys.
- Balance equation `1300 = 1900` at group level.
- Group rows exist.
- Dashboard-critical group metrics are present.
