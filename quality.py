"""Post quality scoring and hard validation for automated publishing."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class QualityReport:
    score: float
    valid: bool
    reasons: Tuple[str, ...]
    components: Dict[str, float]


class PostQualityEvaluator:
    MIN_LENGTH = 420
    MAX_LENGTH = 1800

    UNSUPPORTED_CLAIMS = (
        "90% точности",
        "100% точности",
        "гарантирован",
        "без риска",
        "точно вырастет",
        "точно упадет",
        "киты покупают",
        "киты продают",
        "крупные игроки начали",
        "я заработал",
        "легкая прибыль",
        "лёгкая прибыль",
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
    ) -> QualityReport:
        components = {
            "completeness": self._completeness(text, basic, direction, levels),
            "readability": self._readability(text),
            "structure": self._structure(text),
            "engagement": self._engagement(text),
            "credibility": self._credibility(text),
            "spam_control": self._spam_control(text),
            "length": self._length_score(text),
        }
        weights = {
            "completeness": 0.28,
            "readability": 0.14,
            "structure": 0.18,
            "engagement": 0.12,
            "credibility": 0.16,
            "spam_control": 0.07,
            "length": 0.05,
        }
        score = sum(components[name] * weights[name] for name in components)
        reasons = self.validate(text, basic=basic, direction=direction, levels=levels)[1]
        return QualityReport(
            score=min(max(score, 0.0), 100.0),
            valid=not reasons,
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
    ) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        lowered = text.lower()

        for label in ("вход", "tp1", "tp2", "tp3", "стоп", "r/r"):
            if label not in lowered:
                reasons.append(f"missing required label: {label}")

        if "не финансовая рекомендация" not in lowered:
            reasons.append("missing disclaimer")
        if "?" not in text:
            reasons.append("missing audience question")
        if basic and f"${basic.upper()}" not in text.upper():
            reasons.append("missing ticker")
        if direction and direction.upper() not in text.upper():
            reasons.append("missing direction")

        if levels:
            from writer import _fmt_price  # local import avoids an import cycle at module load

            required_numbers = {
                "entry": _fmt_price(levels["entry"]),
                "tp1": _fmt_price(levels["tp1"]),
                "tp2": _fmt_price(levels["tp2"]),
                "tp3": _fmt_price(levels["tp3"]),
                "stop": _fmt_price(levels["stop"]),
                "risk_reward": f"{levels['risk_reward']:.2f}",
            }
            for name, value in required_numbers.items():
                if value not in text:
                    reasons.append(f"missing exact {name} value: {value}")

            entry = float(levels["entry"])
            stop = float(levels["stop"])
            targets = [float(levels[key]) for key in ("tp1", "tp2", "tp3")]
            if direction == "long":
                if not (stop < entry < targets[0] < targets[1] < targets[2]):
                    reasons.append("invalid LONG level ordering")
            elif direction == "short":
                if not (stop > entry > targets[0] > targets[1] > targets[2]):
                    reasons.append("invalid SHORT level ordering")

        if len(text) < self.MIN_LENGTH:
            reasons.append(f"post is too short: {len(text)}")
        if len(text) > self.MAX_LENGTH:
            reasons.append(f"post is too long: {len(text)}")
        if any(claim in lowered for claim in self.UNSUPPORTED_CLAIMS):
            reasons.append("unsupported promotional claim detected")
        if len(re.findall(r"#[A-Za-zА-Яа-я0-9_]+", text)) > 4:
            reasons.append("too many hashtags")
        if len(re.findall(r"[!?]{2,}", text)) > 1:
            reasons.append("excessive punctuation")

        return not reasons, reasons

    def _completeness(
        self,
        text: str,
        basic: Optional[str],
        direction: Optional[str],
        levels: Optional[Dict[str, float]],
    ) -> float:
        checks = [
            "вход" in text.lower(),
            "tp1" in text.lower(),
            "tp2" in text.lower(),
            "tp3" in text.lower(),
            "стоп" in text.lower(),
            "r/r" in text.lower(),
            "не финансовая рекомендация" in text.lower(),
        ]
        if basic:
            checks.append(f"${basic.upper()}" in text.upper())
        if direction:
            checks.append(direction.upper() in text.upper())
        if levels:
            from writer import _fmt_price

            checks.extend(
                _fmt_price(levels[key]) in text for key in ("entry", "tp1", "tp2", "tp3", "stop")
            )
        return sum(checks) / len(checks) * 100.0 if checks else 0.0

    @staticmethod
    def _readability(text: str) -> float:
        sentences = [part.strip() for part in re.split(r"[.!?]+", text) if len(part.strip()) > 4]
        if not sentences:
            return 0.0
        average_words = sum(len(sentence.split()) for sentence in sentences) / len(sentences)
        if 7 <= average_words <= 18:
            sentence_score = 100.0
        elif 5 <= average_words <= 24:
            sentence_score = 75.0
        else:
            sentence_score = 42.0
        paragraphs = [part for part in text.split("\n\n") if part.strip()]
        paragraph_bonus = 100.0 if 5 <= len(paragraphs) <= 10 else 70.0
        return sentence_score * 0.75 + paragraph_bonus * 0.25

    @staticmethod
    def _structure(text: str) -> float:
        lowered = text.lower()
        score = 0.0
        if text.count("\n") >= 8:
            score += 25
        if "сценарий" in lowered:
            score += 15
        if "план" in lowered:
            score += 20
        if "отмена сценария" in lowered:
            score += 20
        if "почему" in lowered or "подтверж" in lowered:
            score += 20
        return min(score, 100.0)

    @staticmethod
    def _engagement(text: str) -> float:
        lowered = text.lower()
        score = 0.0
        if "?" in text:
            score += 55
        if any(word in lowered for word in ("по-вашему", "вы видите", "считаете", "какой уровень")):
            score += 30
        if "$" in text:
            score += 15
        return min(score, 100.0)

    def _credibility(self, text: str) -> float:
        lowered = text.lower()
        score = 100.0
        for claim in self.UNSUPPORTED_CLAIMS:
            if claim in lowered:
                score -= 35.0
        if "вероятность прибыли" in lowered and "не вероятность прибыли" not in lowered:
            score -= 25.0
        if "не финансовая рекомендация" not in lowered:
            score -= 30.0
        if "отмена сценария" not in lowered:
            score -= 20.0
        return max(score, 0.0)

    @staticmethod
    def _spam_control(text: str) -> float:
        hashtags = len(re.findall(r"#[A-Za-zА-Яа-я0-9_]+", text))
        emoji_count = len(re.findall(r"[\U0001F300-\U0001FAFF]", text))
        repeated_punctuation = len(re.findall(r"[!?]{2,}", text))
        score = 100.0
        if hashtags > 4:
            score -= (hashtags - 4) * 18
        if emoji_count > 4:
            score -= (emoji_count - 4) * 12
        if repeated_punctuation:
            score -= repeated_punctuation * 20
        return max(score, 0.0)

    def _length_score(self, text: str) -> float:
        length = len(text)
        if 650 <= length <= 1350:
            return 100.0
        if self.MIN_LENGTH <= length <= self.MAX_LENGTH:
            return 70.0
        return 15.0
