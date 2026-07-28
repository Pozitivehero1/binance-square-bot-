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

    MIN_LENGTH = 320
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
            "completeness": self._completeness(
                text,
                basic,
                direction,
                levels
            ),
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


        score = sum(
            components[k] * weights[k]
            for k in components
        )


        _, reasons = self.validate(
            text,
            basic=basic,
            direction=direction,
            levels=levels
        )


        return QualityReport(
            score=min(max(score,0),100),
            valid=len(reasons)==0,
            reasons=tuple(reasons),
            components=components
        )


    def validate(
        self,
        text: str,
        *,
        basic=None,
        direction=None,
        levels=None,
    ):

        reasons = []

        lowered = text.lower()


        labels = [
            ("вход", "entry"),
            ("стоп", "stop"),
            ("tp1",),
            ("tp2",),
            ("tp3",),
            ("r/r", "rr"),
        ]


        for group in labels:

            if not any(
                word in lowered
                for word in group
            ):
                reasons.append(
                    f"missing required label: {group[0]}"
                )


        if (
            "не финансовая рекомендация"
            not in lowered
            and
            "не является финансовой рекомендацией"
            not in lowered
        ):
            reasons.append(
                "missing disclaimer"
            )


        if "?" not in text:
            reasons.append(
                "missing audience question"
            )


        if basic:

            ticker = f"${basic.upper()}"

            if ticker not in text.upper():

                reasons.append(
                    "missing ticker"
                )


        if direction:

            direction_ok = [
                direction.upper(),
                "ЛОНГ" if direction.lower()=="long" else "",
                "ШОРТ" if direction.lower()=="short" else "",
            ]

            if not any(
                x in text.upper()
                for x in direction_ok
                if x
            ):
                reasons.append(
                    "missing direction"
                )


        if levels:

            from writer import _fmt_price


            values = {
                "entry": levels["entry"],
                "tp1": levels["tp1"],
                "tp2": levels["tp2"],
                "tp3": levels["tp3"],
                "stop": levels["stop"],
            }


            for name,value in values.items():

                formatted = _fmt_price(value)

                if formatted not in text:
                    reasons.append(
                        f"missing exact {name}"
                    )


        if len(text) < self.MIN_LENGTH:
            reasons.append(
                f"post too short {len(text)}"
            )


        if len(text) > self.MAX_LENGTH:
            reasons.append(
                "post too long"
            )


        if any(
            x in lowered
            for x in self.UNSUPPORTED_CLAIMS
        ):
            reasons.append(
                "unsupported promotional claim"
            )


        hashtags = re.findall(
            r"#[A-Za-zА-Яа-я0-9_]+",
            text
        )

        if len(hashtags)>5:
            reasons.append(
                "too many hashtags"
            )


        return not reasons, reasons



    def _completeness(
        self,
        text,
        basic,
        direction,
        levels
    ):

        ok,_ = self.validate(
            text,
            basic=basic,
            direction=direction,
            levels=levels
        )

        return 100 if ok else 70



    @staticmethod
    def _readability(text):

        if not text:
            return 0

        return 90



    @staticmethod
    def _structure(text):

        score=0

        if "\n" in text:
            score+=25

        if "сценарий" in text.lower():
            score+=25

        if "план" in text.lower():
            score+=25

        if "отмена" in text.lower():
            score+=25

        return min(score,100)



    @staticmethod
    def _engagement(text):

        score=0

        if "?" in text:
            score+=60

        if "$" in text:
            score+=40

        return min(score,100)



    def _credibility(self,text):

        score=100

        low=text.lower()

        for word in self.UNSUPPORTED_CLAIMS:

            if word in low:
                score-=30


        return max(score,0)



    @staticmethod
    def _spam_control(text):

        hashtags=len(
            re.findall(
                r"#\w+",
                text
            )
        )

        return max(
            100-hashtags*10,
            40
        )


    def _length_score(self,text):

        if 500 <= len(text)<=1400:
            return 100

        return 75