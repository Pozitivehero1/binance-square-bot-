# Binance Square Bot — Audience Author v9

Автоматический Binance Square-бот с упором на две задачи: находить **события, на которые у рынка уже есть аудитория**, и превращать их в живые, фактически корректные публикации с полноценным торговым планом.

## Что изменилось в v9

### 1. Audience-first отбор монеты

Бот больше не ставит аномальный `volume xN` во главу угла. Предварительный shortlist собирается из двух корзин — **Audience** (ликвидные/торгуемые активы) и **Live Event** (свежие события), после чего финальный отбор учитывает:

- относительный спрос аудитории: 24h quote volume, число сделок и текущий rank монеты;
- свежесть события на 5m;
- 15m attention;
- техническую состоятельность сетапа;
- качество движения без автоматического бонуса за уже состоявшийся огромный памп;
- пригодность торгового плана для публикации.

Большой объём насыщается: `x30` не получает в несколько раз больший вес, чем уже сильный `x4-x8`. Событие, которое произошло несколько свечей назад и затухает, получает `stale_penalty`.

### 2. 5m Micro Attention

`attention.py` отдельно определяет, происходит ли событие прямо сейчас:

- `fresh` — импульс/объём возник на последней или предпоследней 5m-свече;
- `developing` — событие ещё развивается;
- `stale` — самый сильный всплеск уже остался в прошлом;
- `ordinary` — обычная активность.

Это позволяет не путать «в графике когда-то был x20» с «x20 появился только что».

### 3. Полный Python-owned trade plan

Перед написанием текста Python строит и проверяет:

- `entry`;
- `entry_zone_low / entry_zone_high`;
- `stop_loss`;
- `TP1`;
- `TP2`;
- `TP3`;
- `R/R` для каждой цели;
- процент риска;
- состояние сделки: `decision_now / waiting_retest / waiting_breakout / waiting_breakdown`.

Цифры не придумываются LLM. Если геометрия уровней некорректна, TP3 R/R недостаточен или стоп слишком широк, кандидат отбрасывается **до** генерации поста.

### 4. Mistral теперь полноценный автор

Режим по умолчанию: `CONTENT_MODE=ai_author`.

Python передаёт Mistral не готовый шаблон, а semantic package с рыночными фактами и полным торговым планом. Mistral сам выбирает композицию, ритм, хук и то, какие второстепенные факты стоит упомянуть.

После этого Python проверяет текст:

- cashtag должен быть в первой строке;
- LONG/SHORT нельзя поменять;
- entry/TP1/stop нельзя изменить;
- для `trade_map` и `risk_first` обязательны TP1/TP2/TP3;
- запрещены любые новые числа, которых нет в fact package;
- запрещены обещания будущего и гарантии;
- запрещён «будущий ретест», если цена уже находится у уровня;
- запрещены старые роботизированные обороты;
- не более одного вопроса и одного редкого контекстного emoji;
- текст не должен быть слишком похож на недавние публикации.

Если Mistral не прошёл проверки, бот пробует другой вариант. Если API недоступен, включается fact-perfect deterministic fallback. Если fallback уже начинает повторяться — бот **лучше пропустит цикл, чем отправит дубликат**.

### 5. Content Rotation

Доступны разные смысловые форматы:

- `hot_take`;
- `trade_map`;
- `one_level`;
- `no_chase`;
- `two_paths`;
- `risk_first`;
- `market_story`;
- `micro_note`;
- `volume_read`.

И шесть реально отличающихся визуальных режимов:

- `minimal_chart`;
- `event_chart`;
- `trade_map`;
- `scenario_chart`;
- `context_chart`;
- `clean_chart`.

Соседние посты дополнительно штрафуются за одинаковую композицию, визуал, semantic phrase-family и слишком похожий текст.

## Быстрый запуск

### GitHub Actions

1. Залей содержимое архива в репозиторий.
2. В `Settings → Secrets and variables → Actions` добавь:
   - `SQUARE_API`;
   - `MISTRAL_API`.
3. Workflow уже лежит в `.github/workflows/run.yml`.
4. Внешний cron может вызывать `workflow_dispatch` примерно каждые 20 минут. Это **частота сканирования**, а не обязательная частота публикации: слабый цикл бот пропустит.

`OPENAI_API_KEY` в workflow оставлен только для совместимости и этой версии не требуется.

### Локальная проверка без публикации

```bash
python -m pip install -r requirements.txt
python config_check.py
python self_test.py
python run_tests.py
```

По умолчанию локально `DRY_RUN=1`.

## Основные настройки

```env
CONTENT_MODE=ai_author
MISTRAL_MODEL=mistral-small-latest
AI_VARIANTS=6
AI_RETRIES=2
AI_TEMPERATURE=0.68

POST_MIN_CHARS=150
POST_MAX_CHARS=560
MAX_POST_SIMILARITY=0.46
MIN_POST_QUALITY=84
MIN_FEED_APPEAL=76
MIN_CONVERSION_INTENT=75

MIN_OPPORTUNITY_SCORE=62
MIN_AUDIENCE_DEMAND=24
MIN_W2E_MARKET_SCORE=56
W2E_SOFT_FLOOR=40
HOT_W2E_FLOOR=34

MIN_PUBLIC_TP3_RR=1.55
MAX_PUBLIC_RISK_PCT=8.0

TOP_SYMBOLS=120
SHORTLIST_SIZE=36
FINAL_CANDIDATES=20
COOLDOWN_MIN=240
```

Полный набор есть в `env.example` и в workflow.

## Что означают логи кандидата

Пример:

```text
Candidate XRPUSDT tech=74.1 attention=81.3 micro=88.0/fresh demand=79.4
w2e=72.0 opportunity=77.6 final=84.1 gate=audience breakout ...
```

Ключевые поля:

- `tech` — техническое качество;
- `attention` — 15m текущий интерес;
- `micro` — 5m свежесть;
- `demand` — относительный спрос аудитории;
- `w2e` — пригодность рынка для click-to-market сценария;
- `opportunity` — общий audience-first score;
- `gate` — почему кандидат допущен;
- `plan_R3` — R/R до TP3;
- `state` — состояние сделки.

## Защита от плохих публикаций

Бот пропускает публикацию, если:

- нет связного public trade plan;
- событие уже устарело и спрос аудитории недостаточен;
- opportunity/W2E gate не пройден;
- текст Mistral изменил или придумал число;
- текст слишком похож на недавний;
- feed appeal / conversion intent ниже порога;
- reach gate не пройден;
- монета ещё находится в cooldown.

## Файлы v9

- `main.py` — orchestration и market selection;
- `attention.py` — 15m + 5m freshness;
- `opportunity.py` — audience-first ranking;
- `trade_plan.py` — entry / zone / stop / TP1-3;
- `writer.py` — Mistral author + fact validator + fallback;
- `quality.py` — жёсткая проверка фактов и формы;
- `engagement.py` — feed appeal;
- `monetization.py` — W2E-oriented market/copy scoring;
- `chart.py` — ротация визуальных композиций;
- `memory.py` — анти-повторы и история форматов;
- `.github/workflows/run.yml` — готовый GitHub Actions workflow.

Никакой тест из архива не публикует посты в Binance.
