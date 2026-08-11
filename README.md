# Binance Square Bot — Audience Author v9.1 Dual-Lane

Автоматический Binance Square-бот, который разделяет две разные задачи: **найти хорошую сделку** и **найти событие, которое действительно интересно аудитории прямо сейчас**. В v9.1 эти задачи больше не блокируют друг друга.

## Архитектура

### TRADE lane

Используется, когда рынок даёт нормальную торговую геометрию. Python рассчитывает и проверяет:

- направление;
- entry и entry zone;
- stop loss;
- TP1 / TP2 / TP3;
- R/R каждой цели;
- процент риска;
- состояние сделки (`decision_now`, `waiting_retest`, `waiting_breakout`, `waiting_breakdown`).

Только после этого Mistral пишет пост. Все торговые числа принадлежат Python и не могут быть изменены моделью.

### EVENT lane

Весь preliminary shortlist проходит отдельную audience/event-оценку **даже если ADX, R/R или relative volume не прошли technical gates**.

EVENT lane учитывает:

- относительный audience demand;
- 5m micro freshness;
- 15m attention;
- скорость/качество свежего движения;
- насыщение уже состоявшегося пампа/дампа;
- рыночную пригодность для W2E;
- технический score только как небольшой контекст, а не как hard gate.

Это исправляет ситуацию, когда популярный/интересный тикер даже не доходил до audience engine из-за одного технического порога.

## Если события хватает, а сделки нет

Это теперь нормальный режим, а не ошибка.

Если public trade plan не проходит проверку, EVENT lane выставляет:

```text
optional_trade_plan.available=false
OBSERVATION_ONLY
```

Mistral в таком посте **не имеет права** придумывать LONG/SHORT, entry, stop или TP. Он пишет наблюдение: что изменилось, почему тикер стоит открыть, какую реальную цену/зону стоит смотреть, почему пока нет чистой сделки.

Если public plan валиден, Mistral получает полный пакет:

```text
entry
entry_zone_low / entry_zone_high
stop_loss
TP1
TP2
TP3
R/R TP1 / TP2 / TP3
risk_pct
```

Но даже тогда EVENT-пост не обязан превращаться в сухой сигнал.

## Mistral — автор, Python — редактор фактов

По умолчанию `CONTENT_MODE=ai_author`.

Mistral получает semantic package и последние публикации, которые нельзя копировать. Он сам выбирает хук, ритм, структуру и то, какие факты упомянуть. После этого Python проверяет:

- cashtag в первой строке;
- отсутствие выдуманных чисел;
- отсутствие выдуманных новостей/причин движения/китов/ликвидаций;
- корректность LONG/SHORT, если public plan существует;
- корректность entry/SL/TP;
- отсутствие торгового призыва в observation-only;
- отсутствие обещаний будущего;
- отсутствие роботизированных шаблонов;
- similarity к недавним постам;
- feed appeal и W2E conversion score.

Если текст не проходит — берётся другой вариант. Deterministic copy остаётся только safety net.

## Audience-first shortlist

Сканирование идёт по 5m/15m/1h, затем shortlist собирается из трёх корзин:

- **Audience** — ликвидные/активно торгуемые тикеры;
- **Live Event** — свежие события;
- **Trade Quality** — технически сильные сетапы, чтобы audience/event логика не вытесняла хорошие сделки.

4h/1d подгружаются только для shortlist. Огромный `volume xN` имеет насыщаемый вес: `x30` не считается автоматически в несколько раз лучше `x4-x8`. Stale-события штрафуются.

## Визуалы

TRADE-пост может показывать полный торговый план. Observation-only EVENT-пост не рисует выдуманные TP/SL: остаётся чистый график, реальная ключевая цена и контекст активности.

Используются разные композиции: `minimal_chart`, `event_chart`, `trade_map`, `scenario_chart`, `context_chart`, `clean_chart`. Повтор одинакового формата/визуала получает penalty.

## Быстрый запуск

1. Залей содержимое архива в репозиторий.
2. Добавь GitHub Secrets:
   - `SQUARE_API`;
   - `MISTRAL_API`.
3. Workflow уже находится в `.github/workflows/run.yml`.
4. Внешний cron может запускать `workflow_dispatch` примерно раз в 20 минут. Это **частота сканирования**, а не обязанность публиковать каждые 20 минут.

Локальная проверка:

```bash
python -m pip install -r requirements.txt
python config_check.py
python run_tests.py
```

Длинные stress-тесты повторяемости запускаются отдельно:

```bash
RUN_STRESS_TESTS=1 python run_tests.py
```

По умолчанию локально `DRY_RUN=1`.

## Основные настройки

```env
CONTENT_MODE=ai_author
MISTRAL_MODEL=mistral-small-latest
AI_VARIANTS=6
EVENT_AI_VARIANTS=6

POST_MIN_CHARS=150
POST_MAX_CHARS=560
MAX_POST_SIMILARITY=0.46
MIN_POST_QUALITY=84
MIN_FEED_APPEAL=76
MIN_CONVERSION_INTENT=75

MIN_OPPORTUNITY_SCORE=62
MIN_AUDIENCE_DEMAND=24
MIN_W2E_MARKET_SCORE=56

MIN_EVENT_SCORE=60
EVENT_W2E_FLOOR=42
EVENT_MIN_DEMAND=20
EVENT_LANE_ADVANTAGE=1.5
EVENT_MIN_POST_QUALITY=80
EVENT_MIN_FEED_APPEAL=74
EVENT_MIN_CONVERSION=72

MIN_PUBLIC_PLAN_RR=1.30
MIN_PUBLIC_TP3_RR=1.55
MAX_PUBLIC_RISK_PCT=8.0

TOP_SYMBOLS=120
SHORTLIST_SIZE=36
FINAL_CANDIDATES=20
COOLDOWN_MIN=240
```

## Как читать новые логи

TRADE lane:

```text
Candidate ... profile=strict/balanced ... plan_R3=... gate=...
```

EVENT lane:

```text
Event candidate TSTUSDT ... gate=fresh-event override plan=observation_only tech_gates=bypassed ...
```

Победитель:

```text
LANE WINNER=EVENT symbol=TSTUSDT ... plan=observation_only
```

или:

```text
LANE WINNER=TRADE symbol=XRPUSDT ... plan=valid
```

## Основные файлы

- `main.py` — dual-lane orchestration и финальный выбор;
- `opportunity.py` — TRADE opportunity + независимый audience EVENT score;
- `event_writer.py` — Mistral author/validator для event-контента;
- `writer.py` — Mistral author/validator для trade-контента;
- `trade_plan.py` — entry / zone / stop / TP1-3;
- `attention.py` — 15m attention + 5m micro freshness;
- `monetization.py` — W2E-oriented market/copy scoring;
- `chart.py` — визуалы;
- `memory.py` — анти-повторы;
- `.github/workflows/run.yml` — готовый workflow.

`CHANGES_V9_1.md` содержит краткий список изменений. Ни один offline-тест не публикует посты в Binance.
