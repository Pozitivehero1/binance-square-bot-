"""Offline smoke/regression suite for Audience Author v9.

No market API and no real publication are attempted.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from attention import compute_attention, compute_micro_attention
from card import generate_card
from chart import generate_chart
from filters import SignalFilter, get_top_candidates
from indicators import calculate_multi_timeframe
from memory import PostMemory
from monetization import score_market_monetization
from opportunity import score_market_opportunity
from publisher import publish
from quality import PostQualityEvaluator
from trend import TrendingMarket
from writer import (
    FULL_PLAN_FORMATS,
    _fmt_price,
    _levels,
    _ticker_count,
    generate_post_candidates,
)


def _make_frame(rng, frequency: str, slope: float, rows: int = 260) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=rows, freq=frequency, tz="UTC")
    close = 100 + slope * np.arange(rows) + np.cumsum(rng.normal(0, 0.11, rows))
    open_price = np.r_[close[0], close[:-1]] + rng.normal(0, 0.04, rows)
    high = np.maximum(open_price, close) + rng.uniform(0.08, 0.24, rows)
    low = np.minimum(open_price, close) - rng.uniform(0.08, 0.24, rows)
    volume = rng.uniform(900, 1700, rows)
    volume[-1] = 3300
    return pd.DataFrame(
        {"open": open_price, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def _build_setup(side: str):
    rng = np.random.default_rng(17 if side == "long" else 29)
    slopes = {
        "5m": 0.025 if side == "long" else -0.025,
        "15m": 0.065 if side == "long" else -0.065,
        "1h": 0.14 if side == "long" else -0.14,
        "4h": 0.30 if side == "long" else -0.30,
        "1d": 0.55 if side == "long" else -0.55,
    }
    freqs = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1d"}
    frames = {key: _make_frame(rng, freqs[key], slope) for key, slope in slopes.items()}

    current = frames["15m"]
    if side == "long":
        level = current["high"].iloc[-51:-1].max()
        current.iloc[-1] = [level * 1.001, level * 1.012, level * 0.999, level * 1.008, 3300]
    else:
        level = current["low"].iloc[-51:-1].min()
        current.iloc[-1] = [level * 0.999, level * 1.001, level * 0.988, level * 0.992, 3300]

    # Make the 5m event fresh rather than an old historical spike.
    micro = frames["5m"]
    if side == "long":
        micro.iloc[-1, micro.columns.get_loc("close")] *= 1.004
        micro.iloc[-1, micro.columns.get_loc("high")] = max(micro.iloc[-1]["open"], micro.iloc[-1]["close"]) * 1.002
    else:
        micro.iloc[-1, micro.columns.get_loc("close")] *= 0.996
        micro.iloc[-1, micro.columns.get_loc("low")] = min(micro.iloc[-1]["open"], micro.iloc[-1]["close"]) * 0.998
    micro.iloc[-1, micro.columns.get_loc("volume")] = 4800
    return frames


def _market_context(mtf, frames, score):
    attention = compute_attention(frames["15m"], mtf.tf_15m, score.direction)
    micro = compute_micro_attention(frames["5m"])
    universe = [
        TrendingMarket("BTCUSDT", 90, 20_000_000_000, 4_000_000, 1.5, 100000, 1),
        TrendingMarket("ETHUSDT", 85, 9_000_000_000, 2_800_000, 2.1, 4000, 2),
        TrendingMarket("TESTUSDT", 72, 650_000_000, 850_000, 4.2, mtf.tf_15m.price, 8),
        TrendingMarket("ALTUSDT", 50, 90_000_000, 170_000, 8.0, 1, 24),
    ]
    meta = universe[2]
    levels = _levels(mtf.tf_15m, score.direction)
    opportunity = score_market_opportunity(
        meta=meta,
        universe=universe,
        attention=attention,
        technical_score=score.total,
        risk_reward=float(levels["public_rr"]),
        strict_setup=True,
        micro=micro,
    )
    monetization = score_market_monetization(
        quote_volume_24h=meta.quote_volume,
        trade_count_24h=meta.trade_count,
        abs_change_24h=abs(meta.change_pct),
        trend_rank=meta.rank,
        trend_universe_size=len(universe),
        attention_score=attention.score,
        change_15m=attention.change_15m,
        volume_spike=attention.volume_spike,
        risk_reward=float(levels["public_rr"]),
        overextended=attention.overextended,
        micro_freshness=micro.score,
    )
    return levels, attention, micro, opportunity, monetization


def _test_side(side: str) -> None:
    frames = _build_setup(side)
    mtf = calculate_multi_timeframe("TESTUSDT", frames)
    score = SignalFilter(min_score=0).evaluate(mtf)
    assert score is not None and score.direction == side
    assert score.passed_gates, score.gate_reasons
    levels, attention, micro, opportunity, monetization = _market_context(mtf, frames, score)
    assert levels["plan_valid"], levels
    assert levels["rr_tp1"] < levels["rr_tp2"] < levels["rr_tp3"]

    with tempfile.TemporaryDirectory() as td:
        memory = PostMemory(Path(td) / "post_memory.json")
        with patch.dict(os.environ, {"CONTENT_MODE": "deterministic"}, clear=False):
            drafts = generate_post_candidates(
                symbol="TESTUSDT", basic="TEST", mtf=mtf, score=score,
                memory=memory, levels=levels, attention=attention, micro=micro,
                opportunity=opportunity, monetization=monetization, variant_count=9,
            )
        assert len(drafts) >= 6, len(drafts)
        evaluator = PostQualityEvaluator()
        for draft in drafts:
            report = evaluator.report(
                draft.text, basic="TEST", direction=side, levels=levels,
                content_format=draft.content_format, headline=draft.headline,
            )
            assert report.valid, (draft.content_format, report.reasons, draft.text)
            assert _fmt_price(levels["tp1"]) in draft.text
            assert _fmt_price(levels["stop"]) in draft.text
            if draft.content_format in FULL_PLAN_FORMATS:
                assert _fmt_price(levels["tp2"]) in draft.text
                assert _fmt_price(levels["tp3"]) in draft.text
            assert 1 <= _ticker_count(draft.text, "TEST") <= 2

        selected = drafts[0]
        memory.add_post(
            "TESTUSDT", selected.text, post_style=selected.style_id,
            signal_type=selected.signal_type, content_format=selected.content_format,
            visual_style=selected.visual_style, direction=side, levels=levels,
            market_price=mtf.tf_15m.price,
        )
        assert memory.is_similar(selected.text)

    # Test the richest visual mode with the full three-target ladder.
    chart_path = generate_chart(
        "TESTUSDT", frames["15m"], "TEST",
        entry=levels["plan_entry"], entry_zone_low=levels["entry_zone_low"],
        entry_zone_high=levels["entry_zone_high"], tp1=levels["tp1"],
        tp2=levels["tp2"], tp3=levels["tp3"], stop=levels["stop"],
        direction=side, decision_level=levels["decision"],
        decision_mode=levels["decision_mode"], vol_rel=attention.volume_spike,
        indicator=mtf.tf_15m, visual_style="trade_map", headline=drafts[0].headline,
        signal_label=drafts[0].angle_title,
    )
    try:
        assert chart_path and os.path.getsize(chart_path) > 10_000
    finally:
        if chart_path and os.path.exists(chart_path):
            os.remove(chart_path)

    print(
        f"{side.upper()}: OK | tech={score.total:.1f} | micro={micro.score:.1f}/{micro.phase} | "
        f"opportunity={opportunity.score:.1f} | TP3 R/R={levels['rr_tp3']:.2f}"
    )


def _test_content_diversity() -> None:
    frames = _build_setup("long")
    mtf = calculate_multi_timeframe("TESTUSDT", frames)
    score = SignalFilter(min_score=0).evaluate(mtf)
    levels, attention, micro, opportunity, monetization = _market_context(mtf, frames, score)
    with tempfile.TemporaryDirectory() as td:
        memory = PostMemory(Path(td) / "post_memory.json")
        with patch.dict(os.environ, {"CONTENT_MODE": "deterministic"}, clear=False):
            drafts = generate_post_candidates(
                symbol="TESTUSDT", basic="TEST", mtf=mtf, score=score, memory=memory,
                levels=levels, attention=attention, micro=micro,
                opportunity=opportunity, monetization=monetization, variant_count=9,
            )
    assert len(drafts) >= 7
    assert len({d.content_format for d in drafts}) >= 7
    assert len({d.visual_style for d in drafts}) >= 5
    similarities = [
        PostMemory.compare_texts(drafts[i].text, drafts[j].text)
        for i in range(len(drafts)) for j in range(i)
    ]
    assert max(similarities) < 0.62, max(similarities)
    print(
        f"DIVERSITY: OK | formats={len({d.content_format for d in drafts})} | "
        f"visuals={len({d.visual_style for d in drafts})} | max_pair_similarity={max(similarities):.3f}"
    )


def _test_mistral_full_author_and_fact_lock() -> None:
    frames = _build_setup("long")
    mtf = calculate_multi_timeframe("TESTUSDT", frames)
    score = SignalFilter(min_score=0).evaluate(mtf)
    levels, attention, micro, opportunity, monetization = _market_context(mtf, frames, score)
    e = _fmt_price(levels["plan_entry"])
    lo, hi = _fmt_price(levels["entry_zone_low"]), _fmt_price(levels["entry_zone_high"])
    sl = _fmt_price(levels["stop"])
    t1, t2, t3 = (_fmt_price(levels[k]) for k in ("tp1", "tp2", "tp3"))

    payload = {
        "candidates": [
            {"format_id": "hot_take", "text": f"$TEST сегодня интересен мне не свечой, а качеством входа\n\nЗона около {e} уже в работе. Если покупатели сохранят контроль, смотрю LONG к {t1}.\n\nСтоп {sl}: ниже этой цены идею закрываю."},
            {"format_id": "trade_map", "text": f"В $TEST есть план, который можно проверить без гадания\n\nЗона входа {lo}–{hi}, стоп {sl}. Для LONG цели распределяю так: TP1 {t1}, TP2 {t2}, TP3 {t3}.\n\nЕсли условия входа не выполняются, сделку просто пропускаю."},
            {"format_id": "one_level", "text": f"Для $TEST сейчас важнее всего цена {e}\n\nПока рынок держит рабочую область, LONG остаётся для меня вариантом. Первая цель {t1}.\n\nСтоп {sl}; за этой ценой идея больше не актуальна."},
            {"format_id": "no_chase", "text": f"$TEST двигается, но догонять его ценой плохого входа я не хочу\n\nИнтерес к LONG для меня начинается около {e}; ближайшая цель {t1}.\n\nСтоп {sl}. Если рынок не даёт этот сценарий, я остаюсь вне позиции."},
            {"format_id": "two_paths", "text": f"У $TEST сейчас два понятных исхода, и оба мне подходят\n\nЕсли зона {e} остаётся рабочей, рассматриваю LONG к {t1}. Если цена уходит к стопу {sl}, сценарий снимаю.\n\nНичего между этими условиями угадывать не требуется."},
            {"format_id": "risk_first", "text": f"В $TEST я сначала считаю, где ошибусь, а потом смотрю вверх\n\nВход {lo}–{hi}, стоп {sl}. План LONG: TP1 {t1}, TP2 {t2}, TP3 {t3}.\n\nЕсли цена нарушает условие риска, сделка для меня закончена."},
            # This candidate must be rejected because direct tip/donation solicitation is not allowed by our policy guard.
            {"format_id": "hot_take", "text": f"$TEST: рабочий LONG-сценарий уже рассчитан\n\nВход около {e}, TP1 {t1}, стоп {sl}. Если идея полезна, поддержи автора донатом."},
            # This candidate must be rejected because x99 does not exist in facts.
            {"format_id": "hot_take", "text": f"$TEST якобы получил объём x99 — но это проверка валидатора\n\nLONG от {e} к {t1}; стоп {sl}. Такой вариант не должен пройти."},
        ]
    }
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}

    with tempfile.TemporaryDirectory() as td:
        memory = PostMemory(Path(td) / "post_memory.json")
        memory.add_post(
            "OLDUSDT", "$OLD: недавно я ждал подтверждения уровня\n\nЭто тест памяти последних постов. Стоп 1, цель 2.",
            content_format="hot_take", visual_style="event_chart",
        )
        with patch.dict(os.environ, {"CONTENT_MODE": "ai_author", "ORCAROUTER_API_KEY": "", "MISTRAL_API": "test-key"}, clear=False), \
             patch("ai_provider.requests.post", return_value=response) as mocked:
            drafts = generate_post_candidates(
                symbol="TESTUSDT", basic="TEST", mtf=mtf, score=score, memory=memory,
                levels=levels, attention=attention, micro=micro,
                opportunity=opportunity, monetization=monetization, variant_count=9,
            )

    assert mocked.call_count >= 1
    ai = [d for d in drafts if d.source == "mistral"]
    assert len(ai) >= 5, [d.content_format for d in drafts]
    assert all("x99" not in d.text for d in ai)
    assert all("донат" not in d.text.lower() for d in ai)
    request_json = mocked.call_args.kwargs["json"]
    semantic = json.loads(request_json["messages"][1]["content"])["semantic_package"]
    trade = semantic["trade_plan"]
    assert all(key in trade for key in ("entry", "entry_zone", "stop_loss", "tp1", "tp2", "tp3", "rr_tp1", "rr_tp2", "rr_tp3"))
    print(f"AI AUTHOR FACT LOCK: OK | accepted_ai={len(ai)} | full semantic trade plan | fabricated x99 + donation solicitation rejected")


def _test_balanced_fallback() -> None:
    frames = _build_setup("long")
    frames["15m"].iloc[-1, frames["15m"].columns.get_loc("volume")] = 550
    mtf = calculate_multi_timeframe("BALANCEDUSDT", frames)
    strict = SignalFilter(min_score=0, profile="strict").evaluate(mtf)
    balanced = SignalFilter(min_score=0, profile="balanced").evaluate(mtf)
    assert strict is not None and balanced is not None
    assert not strict.passed_gates
    assert balanced.passed_gates, balanced.gate_reasons
    assert not get_top_candidates([mtf], top_n=1, profile="strict")
    assert get_top_candidates([mtf], top_n=1, profile="balanced")
    print("BALANCED FALLBACK: OK")


def _test_publisher_command() -> None:
    with tempfile.TemporaryDirectory() as td:
        skill_dir = Path(td) / "square-post"
        scripts = skill_dir / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "post-image.mjs").write_text("// test stub", encoding="utf-8")
        image = Path(td) / "chart.png"
        image.write_bytes(b"test-image")
        completed = Mock(returncode=0, stdout="Success! ID: test", stderr="")
        with patch.dict(os.environ, {"SQUARE_API": "test-square-key"}, clear=False), \
             patch("publisher.find_skill_dir", return_value=str(skill_dir)), \
             patch("publisher.subprocess.run", return_value=completed) as mocked_run:
            assert publish("$TEST — test post", image_path=str(image))
        command = mocked_run.call_args.args[0]
        assert command[0] == "node" and command[1].endswith("post-image.mjs")
        assert mocked_run.call_args.kwargs["env"]["BINANCE_SQUARE_OPENAPI_KEY"] == "test-square-key"
    print("PUBLISHER COMMAND: OK")


def main() -> None:
    _test_side("long")
    _test_side("short")
    _test_content_diversity()
    _test_mistral_full_author_and_fact_lock()
    _test_balanced_fallback()
    _test_publisher_command()
    print("All v10.1 core offline tests passed. No publication was attempted.")


if __name__ == "__main__":
    main()
