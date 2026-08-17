"""Fact-locked v11.1 copywriter for exact trade outcome follow-ups."""
from __future__ import annotations

import logging
import math
import os
import random
import re
from typing import Dict, List, Optional

from ai_provider import has_ai_provider, request_candidates
from memory import PostMemory

logger = logging.getLogger(__name__)
OUTCOME_AI_ENABLED = os.getenv("OUTCOME_AI", "1").strip().lower() in {"1", "true", "yes", "on"}
BANNED = re.compile(
    r"донат|пожертв|поддержи\s+автора|постав[ьи]?\s+лайк|лайкни|подпиш|напиши\s+комментар|"
    r"гарантир|без\s+риска|точн(?:ая|о)\s+прибыл|заработал[аи]?\s+\d",
    re.IGNORECASE,
)


def _fmt_price(value: float) -> str:
    absolute = abs(float(value))
    if absolute >= 1000: decimals = 1
    elif absolute >= 100: decimals = 1
    elif absolute >= 10: decimals = 2
    elif absolute >= 1: decimals = 3
    elif absolute >= 0.1: decimals = 4
    elif absolute >= 0.01: decimals = 5
    elif absolute >= 0.001: decimals = 6
    else: decimals = 8
    return f"{float(value):.{decimals}f}".rstrip("0").rstrip(".")


def _allowed_numbers(facts: dict) -> List[float]:
    out = []
    for key in ("entry", "reached_price", "stop", "move_pct", "rr", "next_target"):
        value = facts.get(key)
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            out.append(value)
    return out


def _numbers_ok(text: str, facts: dict) -> bool:
    allowed = _allowed_numbers(facts)
    for raw in re.findall(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?", text):
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            continue
        # TP labels (TP1/TP2/TP3) are handled by regex word boundaries and do not
        # count as market numbers when glued to letters.
        if any(abs(value - ref) <= max(abs(ref) * 0.003, 0.015 if abs(ref) >= 1 else 1e-8) for ref in allowed):
            continue
        return False
    return True


def _valid(text: str, facts: dict) -> bool:
    clean = str(text or "").strip()
    symbol = str(facts["symbol"]).upper()
    if len(clean) < 90 or len(clean) > 520:
        return False
    if f"${symbol}" not in clean[:100].upper():
        return False
    if BANNED.search(clean):
        return False
    if not _numbers_ok(clean, facts):
        return False
    event_kind = str(facts.get("event_kind") or "")
    reached = _fmt_price(float(facts["reached_price"]))
    normalized = clean.replace(",", ".")
    if reached.replace(",", ".") not in normalized:
        return False
    if event_kind == "target":
        target_name = str(facts.get("target_name") or "").upper()
        if target_name not in {"TP1", "TP2", "TP3"} or target_name not in clean.upper():
            return False
        if not re.search(r"достиг|дош[её]л|отработ|цель|target|tp", clean, re.IGNORECASE):
            return False
    elif event_kind == "target_complete":
        if str(facts.get("target_name") or "").lower() != "tp3":
            return False
        if not re.search(r"(?:tp3|финальн|все\s+(?:публичн\w+\s+)?цели|весь\s+план)", clean, re.IGNORECASE):
            return False
    else:
        if not re.search(r"стоп|отмен|инвалид|границ[ау]\s+риска", clean, re.IGNORECASE):
            return False
    return True


def _deterministic(facts: dict) -> List[str]:
    s = str(facts["symbol"]).upper()
    price = _fmt_price(facts["reached_price"])
    entry = _fmt_price(facts["entry"])
    rr = float(facts.get("rr") or 0.0)
    move = abs(float(facts.get("move_pct") or 0.0))
    next_target = facts.get("next_target")
    target = str(facts.get("target_name") or "цель").upper()
    if facts["event_kind"] == "target_complete":
        return [
            f"${s}: опубликованный сценарий дошёл до финальной цели {price}. От точки входа {entry} рынок прошёл {move:.2f}% в сторону идеи — это около {rr:.2f}R по исходному плану. Сетап считаю полностью отработанным.",
            f"${s}: все публичные цели из предыдущего плана достигнуты. Финальный уровень {price}, движение от входа {entry} — {move:.2f}% и примерно {rr:.2f}R. На этом сценарий закрыт; дальше уже нужна новая структура рынка.",
        ]
    if facts["event_kind"] == "target":
        tail = f" Следующий опубликованный уровень — {_fmt_price(next_target)}." if next_target is not None else ""
        return [
            f"${s}: {target} из опубликованного плана достигнута на {price}. От входа {entry} это {move:.2f}% движения и около {rr:.2f}R. Цель отмечаю как выполненную, остальной сценарий не переписываю задним числом.{tail}",
            f"${s}: цена дошла до {target} {price}, который был указан в исходном сетапе. Движение от входа {entry} составило {move:.2f}% — примерно {rr:.2f}R. Дальше смотрю только на оставшиеся уровни плана.{tail}",
        ]
    partial = str(facts.get("prior_targets") or "").strip()
    prefix = f" До этого успели отработать {partial}." if partial else ""
    return [
        f"${s}: сценарий закрыт по границе риска {price}.{prefix} Стоп был частью исходного плана, поэтому после его достижения идея больше не считается активной — без переноса уровня задним числом.",
        f"${s}: цена дошла до стоп-уровня {price}, поэтому предыдущий сетап отменён.{prefix} Здесь важнее зафиксировать исход как есть, а не подгонять план после движения рынка.",
    ]


def build_outcome_post(facts: Dict, memory: Optional[PostMemory] = None) -> tuple[str, str]:
    """Return (text, source). AI is optional; deterministic copy is always available."""
    memory = memory or PostMemory()
    candidates: List[tuple[str, str]] = []
    if OUTCOME_AI_ENABLED and has_ai_provider():
        system = (
            "Ты автор Binance Square. Напиши короткое продолжение УЖЕ опубликованного торгового плана на русском. "
            "Не придумывай новые цены, цели, проценты, PnL, плечо или размер позиции. Не утверждай, что читатель заработал. "
            "Никаких призывов к донатам, лайкам, подписке или комментариям. Не обещай прибыль. "
            "Верни JSON {\"candidates\":[{\"text\":\"...\"}, ...]}. Cashtag должен быть в начале. "
            "Тон спокойный, человеческий, 2 коротких абзаца максимум."
        )
        payload = {
            "task": "trade_outcome_followup",
            "facts": facts,
            "hard_rules": [
                "use only supplied numeric facts",
                "event_kind and target_name are exact: never call TP1 a final/all-target result",
                "say target reached / setup invalidated, not guaranteed profit",
                "no donation/engagement solicitation",
                "do not invent leverage or USDT PnL",
            ],
            "recent_posts": memory.recent_texts(6),
        }
        try:
            result = request_candidates(
                system_prompt=system,
                user_payload=payload,
                temperature=0.58,
                max_tokens=520,
                timeout=int(os.getenv("AI_TIMEOUT", "55")),
            )
            for row in result.candidates:
                text = str(row.get("text") or "").strip()
                if _valid(text, facts):
                    candidates.append((text, result.provider))
        except Exception as exc:
            logger.warning("Outcome AI unavailable; deterministic fallback: %s", exc)

    for text in _deterministic(facts):
        if _valid(text, facts):
            candidates.append((text, "deterministic_outcome"))
    if not candidates:
        raise RuntimeError("No valid outcome copy candidate")

    ranked = []
    for text, source in candidates:
        similarity = memory.similarity_score(text, n=42)
        human_bonus = 0.03 if source != "deterministic_outcome" else 0.0
        score = similarity - human_bonus + abs(len(text) - 250) / 5000.0
        ranked.append((score, random.random() * 0.005, text, source, similarity))
    ranked.sort(key=lambda row: (row[0], row[1]))
    _, _, text, source, similarity = ranked[0]
    logger.info("Outcome copy selected source=%s similarity=%.3f chars=%s", source, similarity, len(text))
    return text, source
