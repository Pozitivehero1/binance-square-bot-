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

            "completeness":
                self._completeness(
                    text,
                    basic,
                    direction,
                    levels
                ),

            "readability":
                self._readability(text),

            "structure":
                self._structure(text),

            "engagement":
                self._engagement(text),

            "credibility":
                self._credibility(text),

            "spam_control":
                self._spam_control(text),

            "length":
                self._length_score(text),
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
            components[key] * weights[key]
            for key in components
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



        # обязательные блоки
        required_groups = [

            (
                "entry",
                [
                    "вход",
                    "entry"
                ]
            ),

            (
                "tp1",
                [
                    "tp1",
                    "цель 1",
                    "target 1"
                ]
            ),

            (
                "tp2",
                [
                    "tp2",
                    "цель 2",
                    "target 2"
                ]
            ),

            (
                "tp3",
                [
                    "tp3",
                    "цель 3",
                    "target 3"
                ]
            ),

            (
                "stop",
                [
                    "стоп",
                    "stop"
                ]
            ),

            (
                "risk_reward",
                [
                    "r/r",
                    "rr",
                    "risk/reward",
                    "риск/прибыль"
                ]
            ),
        ]


        for name, variants in required_groups:

            if not any(
                item in lowered
                for item in variants
            ):
                reasons.append(
                    f"missing {name}"
                )



        # дисклеймер

        if (
            "не финансовая рекомендация"
            not in lowered
            and
            "не является финансовой рекомендацией"
            not in lowered
        ):
            reasons.append(
                "missing risk note"
            )



        # вопрос аудитории

        if "?" not in text:

            reasons.append(
                "missing audience question"
            )



        # тикер

        if basic:

            ticker = "$" + basic.upper()

            if ticker not in text.upper():

                reasons.append(
                    "missing ticker"
                )



        # направление

        if direction:


            variants = []

            if direction.lower()=="long":

                variants = [
                    "LONG",
                    "ЛОНГ",
                    "ПОКУПКА"
                ]


            elif direction.lower()=="short":

                variants = [
                    "SHORT",
                    "ШОРТ",
                    "ПРОДАЖА"
                ]



            if not any(
                x in text.upper()
                for x in variants
            ):

                reasons.append(
                    "missing direction"
                )



        # уровни

        if levels:

            from writer import _fmt_price


            for key in (
                "entry",
                "tp1",
                "tp2",
                "tp3",
                "stop"
            ):

                if key in levels:

                    value = _fmt_price(
                        levels[key]
                    )


                    if value not in text:

                        reasons.append(
                            f"missing {key} value {value}"
                        )



            rr = (
                f"{levels.get('risk_reward',0):.2f}"
            )


            if (
                rr not in text
                and
                "r/r" not in lowered
                and
                "rr" not in lowered
            ):

                reasons.append(
                    "missing risk reward value"
                )



        if len(text) < self.MIN_LENGTH:

            reasons.append(
                f"post too short {len(text)}"
            )


        if len(text) > self.MAX_LENGTH:

            reasons.append(
                "post too long"
            )



        for claim in self.UNSUPPORTED_CLAIMS:

            if claim in lowered:

                reasons.append(
                    "unsupported claim"
                )



        hashtags = re.findall(
            r"#[A-Za-zА-Яа-я0-9_]+",
            text
        )


        if len(hashtags)>5:

            reasons.append(
                "too many hashtags"
            )


        return (
            len(reasons)==0,
            reasons
        )



    def _completeness(
        self,
        text,
        basic,
        direction,
        levels
    ):

        valid,_ = self.validate(
            text,
            basic=basic,
            direction=direction,
            levels=levels
        )

        return 100 if valid else 75



    @staticmethod
    def _readability(text):

        return 90



    @staticmethod
    def _structure(text):

        score=0

        low=text.lower()

        if "\n" in text:
            score+=25

        if "сценарий" in low:
            score+=25

        if "план" in low:
            score+=25

        if "отмена" in low:
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

        for claim in self.UNSUPPORTED_CLAIMS:

            if claim in low:

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

        size=len(text)

        if 500 <= size <= 1400:

            return 100

        return 75