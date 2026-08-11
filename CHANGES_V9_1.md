# Audience Author v9.1 — Dual-Lane Engine

## Почему появился v9.1

Живой лог v9 показал архитектурный перекос: preliminary shortlist содержал 36 монет, но до audience/W2E-оценки дошли только 6, потому что строгие/сбалансированные технические фильтры раньше отбрасывали остальные. Это мешало использовать популярный или свежий тикер как качественный Square-контент, если конкретно сейчас у него не было хорошего ADX/R/R/relative-volume trade setup.

## Что исправлено

### Два независимых потока

**TRADE lane** сохраняет строгую логику:
- strict/balanced technical gates;
- валидный public plan;
- entry zone;
- stop loss;
- TP1 / TP2 / TP3;
- R/R и риск;
- W2E/opportunity gate.

**EVENT lane** проверяет весь shortlist независимо от того, прошла ли монета ADX/R/R/relative-volume gates. Он оценивает:
- audience demand;
- 5m micro freshness;
- 15m attention;
- качество свежего движения;
- насыщение уже состоявшегося движения;
- W2E market quality.

Технический score остаётся небольшим контекстом, но не hard gate.

### Observation-only — это допустимый хороший пост

Если событие сильное, но public trade plan плохой, бот больше не выдумывает сделку. Mistral получает `optional_trade_plan.available=false` и обязан писать только наблюдение. LONG/SHORT, entry, stop и TP в таком посте запрещены валидатором.

Если public plan валиден, EVENT lane всё равно передаёт Mistral полный пакет: entry zone + stop + TP1/TP2/TP3 + R/R. Автор может использовать его естественно, но не обязан превращать каждый event-пост в сигнал.

### Mistral и fact lock

Для EVENT lane создан отдельный `event_writer.py`. Он:
- пишет с нуля по semantic package;
- видит последние посты, которые нельзя копировать;
- не может добавлять новые числа;
- не может придумывать новости/китов/ликвидации/причины движения;
- не может выдумывать торговый план, если Python его отверг;
- использует редкий контекстный emoji только после валидации.

### Визуал observation-only

Если торгового плана нет, график показывает только реальную ключевую цену/контекст и активность. Никаких фальшивых зелёных TP и красного стопа.

### Lane rotation

EVENT lane не должен захватить всю ленту: несколько недавних event-постов получают rotation penalty. При сопоставимых score TRADE остаётся предпочтительным; EVENT должен быть заметно сильнее (`EVENT_LANE_ADVANTAGE`).

## Новые настройки

```env
MIN_EVENT_SCORE=60
EVENT_W2E_FLOOR=42
EVENT_MIN_DEMAND=20
EVENT_LANE_ADVANTAGE=1.5
EVENT_MIN_POST_QUALITY=80
EVENT_MIN_FEED_APPEAL=74
EVENT_MIN_CONVERSION=72
EVENT_AI_VARIANTS=6
EVENT_AI_RETRIES=2
EVENT_AI_TEMPERATURE=0.72
```

## Проверки

Добавлен `dual_lane_test.py`: он моделирует ситуацию, где монета провалила technical gate, но имеет свежий audience event. Такой кандидат обязан пройти EVENT lane; при невалидном public plan текст обязан остаться observation-only.
