"""Editorial and factual quality gates for v11.1 public-plan content."""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Dict, List, Optional, Tuple

from engagement import FeedAppealEvaluator


@dataclass
class QualityReport:
    score: float
    valid: bool
    reasons: Tuple[str, ...]
    components: Dict[str, float]


FULL_PLAN_FORMATS: set[str] = {"trade_map", "risk_first"}


class PostQualityEvaluator:
    MIN_LENGTH = int(os.getenv("POST_MIN_CHARS", "220"))
    MAX_LENGTH = int(os.getenv("POST_MAX_CHARS", "430"))

    UNSUPPORTED_CLAIMS = (
        "90% точности", "100% точности", "гарантирован", "без риска",
        "точно вырастет", "точно упадет", "точно пойдёт", "точно пойдет",
        "киты покупают", "киты продают", "инсайд", "листинг скоро",
        "легкая прибыль", "лёгкая прибыль", "вероятность успеха",
        "памп неизбежен", "безусловный сигнал", "обязательно вырастет",
        "обязательно упадет", "точно удержат", "точно пробьют",
    )
    ROBOTIC_PHRASES = (
        "направление у идеи", "граница ошибки:", "диапазон контроля",
        "стоп является технической границей", "параметры сценария",
        "карта исполнения", "правило исполнения:", "факты для выбора:",
        "что вижу сейчас:", "направление:",
    )
    GENERIC_HEADLINES = (
        r"^\$[A-Z0-9]+\s*[—-]\s*(?:LONG|SHORT)\s*:",
        r"^\$[A-Z0-9]+\s*[—-]\s*(?:ЛОНГ|ШОРТ)\s*:",
        r"^СИГНАЛ\s*[|:]",
    )

    def evaluate(self, text: str) -> float:
        return self.report(text).score

    def report(
        self,
        text: str,
        *,
        basic: Optional[str] = None,
        direction: Optional[str] = None,
        levels: Optional[Dict[str, float]] = None,
        content_format: str = "",
        headline: str = "",
    ) -> QualityReport:
        valid, reasons = self.validate(
            text,
            basic=basic,
            direction=direction,
            levels=levels,
            content_format=content_format,
            headline=headline,
        )
        feed_appeal = FeedAppealEvaluator().report(text)
        components = {
            "factual_contract": self._contract_score(valid, reasons),
            "headline": self._headline_score(text, headline),
            "readability": self._readability(text),
            "structure": self._structure(text),
            "human_voice": self._human_voice(text),
            "credibility": self._credibility(text),
            "spam_control": self._spam_control(text),
            "feed_appeal": feed_appeal.score,
        }
        weights = {
            "factual_contract": 0.18,
            "headline": 0.16,
            "readability": 0.12,
            "structure": 0.08,
            "human_voice": 0.12,
            "credibility": 0.10,
            "spam_control": 0.04,
            "feed_appeal": 0.20,
        }
        score = sum(components[name] * weights[name] for name in components)
        return QualityReport(
            score=min(max(score, 0.0), 100.0),
            valid=valid,
            reasons=tuple(reasons),
            components=components,
        )

    def validate(
        self,
        text: str,
        *,
        basic: Optional[str] = None,
        direction: Optional[str] = None,
        levels: Optional[Dict[str, float]] = None,
        content_format: str = "",
        headline: str = "",
    ) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        lowered = text.lower().replace("ё", "е")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        first_line = lines[0] if lines else ""

        if basic:
            ticker_pattern = rf"(?<![A-Za-z0-9_])\${re.escape(basic.upper())}(?![A-Za-z0-9_])"
            ticker_count = len(re.findall(ticker_pattern, text.upper()))
            if not 1 <= ticker_count <= 3:
                reasons.append(f"ticker mentions {ticker_count}")
            if first_line and not re.search(ticker_pattern, first_line.upper()):
                reasons.append("ticker missing from headline")

        if direction:
            variants = ("LONG", "ЛОНГ") if direction.lower() == "long" else ("SHORT", "ШОРТ")
            opposite = ("SHORT", "ШОРТ") if direction.lower() == "long" else ("LONG", "ЛОНГ")
            if not any(item in text.upper() for item in variants):
                reasons.append("missing direction")
            if any(re.search(rf"\b{item}\b", text.upper()) for item in opposite):
                reasons.append("opposite direction mentioned")

        if levels:
            from writer import _fmt_price
            tp1 = levels.get("tp1", levels.get("public_target"))
            stop = levels.get("stop")
            if tp1 is not None and _fmt_price(tp1) not in text:
                reasons.append("missing TP1")
            if stop is not None and _fmt_price(stop) not in text:
                reasons.append("missing stop")
            # v11.1: every plan-valid publication exposes the complete ladder,
            # independent of prose format.
            if levels.get("plan_valid") is not False:
                for target_name in ("tp2", "tp3"):
                    value = levels.get(target_name)
                    if value is not None and _fmt_price(value) not in text:
                        reasons.append(f"missing {target_name.upper()}")
            if levels.get("plan_valid") is False:
                reasons.append("invalid public trade plan")

            # The invalidation is valid when the exact stop is explicitly called a
            # stop, cancellation or line where the idea closes. No need for one
            # canned sentence in every post.
            invalidation_words = (
                "стоп", " sl ", "sl:", "sl ", "отмена", "отменяется", "закрываю", "закрыт", "ломает идею",
                "не открываю", "пропускаю", "не актуален", "сценарий снимаю",
            )
            if stop is not None and not any(marker in lowered for marker in invalidation_words):
                reasons.append("missing invalidation rule")

            mode = str(levels.get("decision_mode", "at_level"))
            if mode in {"at_level", "breakout_confirm", "breakdown_confirm"}:
                if "ретест" in lowered or "после отката" in lowered or "на откате" in lowered:
                    reasons.append("retest wording conflicts with current level state")
            if re.search(r"ретест[^.!?]{0,45}(?:состо|будет|произойд)", lowered):
                reasons.append("predictive retest wording")

        q_count = text.count("?")
        if q_count > 1:
            reasons.append("too many questions")

        if not first_line:
            reasons.append("missing headline")
        else:
            if headline and first_line != headline.strip():
                reasons.append("headline mismatch")
            if len(first_line) < 24:
                reasons.append("headline too short")
            if len(first_line) > 125:
                reasons.append("headline too long")
            if any(re.search(pattern, first_line, flags=re.IGNORECASE) for pattern in self.GENERIC_HEADLINES):
                reasons.append("generic signal headline")

        if len(text) < self.MIN_LENGTH:
            reasons.append(f"post too short {len(text)}")
        if len(text) > self.MAX_LENGTH:
            reasons.append(f"post too long {len(text)}")

        for claim in self.UNSUPPORTED_CLAIMS:
            if claim in lowered:
                reasons.append(f"unsupported claim: {claim}")
        if any(phrase in lowered for phrase in self.ROBOTIC_PHRASES):
            reasons.append("robotic wording")

        hashtags = re.findall(r"#[A-Za-zА-Яа-я0-9_]+", text)
        if hashtags:
            reasons.append("hashtags disabled")
        if len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", text)) > 1:
            reasons.append("too many emojis")
        return not reasons, reasons

    @staticmethod
    def _contract_score(valid: bool, reasons: List[str]) -> float:
        if valid:
            return 100.0
        severe = sum(
            reason.startswith("missing") or "robotic" in reason or "opposite" in reason
            for reason in reasons
        )
        return max(12.0, 90.0 - severe * 14.0 - max(0, len(reasons) - severe) * 5.0)

    def _headline_score(self, text: str, explicit_headline: str) -> float:
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if not first:
            return 0.0
        lowered = first.lower().replace("ё", "е")
        score = 88.0
        if 30 <= len(first) <= 118:
            score += 10.0
        else:
            score -= 18.0
        if "$" not in first:
            score -= 28.0
        if any(re.search(pattern, first, flags=re.IGNORECASE) for pattern in self.GENERIC_HEADLINES):
            score -= 60.0
        if any(word in lowered for word in (
            "но", "почему", "здесь", "сейчас", "после", "уже", "риск", "объем", "объём",
            "цена", "уров", "план", "не беру", "не лез", "не догон", "важнее",
        )):
            score += 6.0
        if explicit_headline and first != explicit_headline.strip():
            score -= 30.0
        return min(max(score, 0.0), 100.0)

    @staticmethod
    def _readability(text: str) -> float:
        paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
        score = 100.0
        if len(paragraphs) < 2:
            score -= 28.0
        if len(paragraphs) > 6:
            score -= min(35.0, (len(paragraphs) - 6) * 7.0)
        if len(text) > 520:
            score -= min(30.0, (len(text) - 520) / 5.0)
        if len(text) < 170:
            score -= min(20.0, (170 - len(text)) / 4.0)
        long_lines = sum(len(line) > 185 for line in text.splitlines())
        score -= min(20.0, long_lines * 7.0)
        return max(score, 20.0)

    @staticmethod
    def _structure(text: str) -> float:
        lowered = text.lower().replace("ё", "е")
        score = 48.0
        score += 18.0 if any(x in lowered for x in ("если ", "пока ", "при ")) else 0.0
        score += 18.0 if any(x in lowered for x in ("tp1", "первая цель", "цель ", "к ")) else 0.0
        score += 16.0 if any(x in lowered for x in ("стоп", "отмен", "закрываю", "пропускаю")) else 0.0
        return min(score, 100.0)

    @staticmethod
    def _human_voice(text: str) -> float:
        lowered = text.lower().replace("ё", "е")
        score = 42.0
        if re.search(r"\b(?:я|мне|мой|моя|для меня)", lowered):
            score += 34.0
        if any(marker in lowered for marker in (
            "беру", "не беру", "смотрю", "проверю", "пропущ", "не лез", "не догон",
            "мне важ", "мой план", "для меня", "интересен", "интересна",
        )):
            score += 18.0
        if any(marker in lowered for marker in ("ошибка", "ловушка", "поздн", "риск", "спеш")):
            score += 6.0
        return min(score, 100.0)

    def _credibility(self, text: str) -> float:
        lowered = text.lower().replace("ё", "е")
        score = 100.0
        score -= sum(35.0 for claim in self.UNSUPPORTED_CLAIMS if claim in lowered)
        if not any(marker in lowered for marker in (
            "стоп", "отмен", "закрываю", "не открываю", "пропускаю", "сценарий снимаю",
        )):
            score -= 22.0
        if "гарант" in lowered or "точно" in lowered:
            score -= 28.0
        return max(score, 0.0)

    @staticmethod
    def _spam_control(text: str) -> float:
        hashtags = len(re.findall(r"#\w+", text))
        emojis = len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", text))
        exclamations = text.count("!")
        score = 100.0
        score -= hashtags * 25.0
        score -= max(0, emojis - 1) * 22.0
        score -= max(0, exclamations - 1) * 12.0
        return max(score, 25.0)
