"""Feed-appeal scoring for Audience Author v9.

The evaluator rewards a readable opinionated hook, useful trade context and
variation.  It does *not* reward the old repeated 'wait for confirmation'
formula merely for sounding cautious.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict


@dataclass(frozen=True)
class FeedAppealReport:
    score: float
    components: Dict[str, float]


class FeedAppealEvaluator:
    TECHNICAL_TERMS = (
        "rsi", "adx", "vwap", "ema20", "ema50", "r/r", "risk/reward",
        "мульти", "таймфрейм", "относительный объём", "относительный объем",
        "параметры сценария", "карта исполнения", "протокол исполнения",
        "граница ошибки", "диапазон контроля",
    )
    HUMAN_MARKERS = (
        "я ", "мне ", "для меня", "я бы", "мой план", "смотрю", "беру",
        "не беру", "не лез", "не догон", "пропущ", "интересен", "интересна",
        "риск", "ошибка", "ловушка", "мне важнее",
    )
    HOOK_MARKERS = (
        "но", "почему", "здесь", "сейчас", "одна", "ошибка", "ловушка",
        "риск", "не беру", "не лез", "не догон", "после", "уже", "важнее",
        "объем", "объём", "цена", "уровень", "план",
    )
    ROBOTIC_LABELS = (
        "направление:", "направление у идеи", "ключевой уровень:",
        "рабочие уровни", "параметры сценария", "что отслеживаю:",
        "граница ошибки:", "диапазон контроля", "правило исполнения:",
        "факты для выбора:",
    )
    OVERUSED_CAUTION = (
        "дождаться подтверждения", "жду подтверждения", "кто удержит уровень",
        "кто удерживает уровень", "сначала подтверждение", "не спешу входить",
    )

    def report(self, text: str) -> FeedAppealReport:
        first = next((x.strip() for x in text.splitlines() if x.strip()), "")
        lowered = text.lower().replace("ё", "е")
        first_lower = first.lower().replace("ё", "е")
        words = re.findall(r"[a-zа-я0-9$%./+\-]+", lowered)
        word_count = max(1, len(words))
        numbers = re.findall(r"(?<!\w)[+-]?\d+(?:[.,]\d+)?%?", text)
        paragraphs = [x.strip() for x in text.split("\n\n") if x.strip()]

        hook = 44.0
        if "$" in first:
            hook += 16.0
        if any(marker in first_lower for marker in self.HOOK_MARKERS):
            hook += 24.0
        if 30 <= len(first) <= 118:
            hook += 14.0
        if re.match(r"^\$[A-Z0-9]+:\s*[+-]?\d+(?:[.,]\d+)?%", first):
            hook -= 16.0
        if first_lower.startswith(("направление", "сигнал")):
            hook -= 30.0
        hook = max(0.0, min(100.0, hook))

        human = 38.0
        human += min(48.0, sum(1 for marker in self.HUMAN_MARKERS if marker in lowered) * 7.0)
        if re.search(r"\b(?:я|мне|мой|моя|для меня)\b", lowered):
            human += 14.0
        if any(marker in lowered for marker in self.ROBOTIC_LABELS):
            human -= 28.0
        human = max(0.0, min(100.0, human))

        clarity = 100.0
        numeric_ratio = len(numbers) / word_count
        # W2E trade-map posts may legitimately contain entry + stop + 3 targets.
        if numeric_ratio > 0.11:
            clarity -= min(45.0, (numeric_ratio - 0.11) * 340.0)
        tech_hits = sum(lowered.count(term) for term in self.TECHNICAL_TERMS)
        clarity -= min(35.0, max(0, tech_hits - 2) * 7.0)
        if len(paragraphs) > 6:
            clarity -= (len(paragraphs) - 6) * 6.0
        if len(text) > 560:
            clarity -= min(30.0, (len(text) - 560) / 7.0)
        clarity = max(15.0, clarity)

        conversation = 90.0
        q_count = text.count("?")
        if q_count == 1:
            conversation = 94.0
        elif q_count > 1:
            conversation = 42.0

        anti_template = 100.0
        labels = sum(lowered.count(x) for x in self.ROBOTIC_LABELS)
        anti_template -= min(70.0, labels * 14.0)
        caution_hits = sum(lowered.count(x) for x in self.OVERUSED_CAUTION)
        anti_template -= min(30.0, caution_hits * 10.0)
        if len(numbers) >= 12:
            anti_template -= 20.0
        if text.count(":") >= 7:
            anti_template -= 18.0
        anti_template = max(10.0, anti_template)

        length_fit = 100.0
        if len(text) < 180:
            length_fit -= min(35.0, (180 - len(text)) / 3.0)
        elif len(text) > 520:
            length_fit -= min(45.0, (len(text) - 520) / 4.0)
        if not 2 <= len(paragraphs) <= 6:
            length_fit -= 10.0
        length_fit = max(20.0, length_fit)

        components = {
            "hook": hook,
            "human_voice": human,
            "clarity": clarity,
            "conversation": conversation,
            "anti_template": anti_template,
            "length_fit": length_fit,
        }
        score = (
            hook * 0.29
            + human * 0.23
            + clarity * 0.20
            + conversation * 0.07
            + anti_template * 0.13
            + length_fit * 0.08
        )
        return FeedAppealReport(round(max(0.0, min(100.0, score)), 2), components)
