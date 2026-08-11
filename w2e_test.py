"""Offline tests for v9 W2E scoring. No network and no publication."""
from monetization import ConversionIntentEvaluator, score_market_monetization


def main() -> None:
    hot = score_market_monetization(
        quote_volume_24h=650_000_000,
        trade_count_24h=1_200_000,
        abs_change_24h=7.5,
        trend_rank=4,
        trend_universe_size=80,
        attention_score=78,
        change_15m=1.3,
        volume_spike=2.8,
        risk_reward=2.2,
        overextended=False,
        micro_freshness=84,
    )
    cold = score_market_monetization(
        quote_volume_24h=9_000_000,
        trade_count_24h=8_000,
        abs_change_24h=0.4,
        trend_rank=70,
        trend_universe_size=80,
        attention_score=26,
        change_15m=0.08,
        volume_spike=0.8,
        risk_reward=1.05,
        overextended=False,
        micro_freshness=30,
    )
    assert hot.score > cold.score + 30, (hot, cold)

    # ENA-like regression: modest 24h rank/liquidity, but a genuinely fresh
    # intraday event. v9 deliberately does NOT require this score alone to clear
    # the hard 56 gate; the selector may admit it through a fresh-event route.
    live_alt = score_market_monetization(
        quote_volume_24h=12_000_000,
        trade_count_24h=53_000,
        abs_change_24h=4.5,
        trend_rank=33,
        trend_universe_size=51,
        attention_score=88.5,
        change_15m=2.92,
        volume_spike=18.08,
        risk_reward=2.0,
        overextended=True,
        micro_freshness=91,
    )
    assert live_alt.freshness_score >= 80, live_alt
    assert live_alt.score > cold.score + 20, (live_alt, cold)

    evaluator = ConversionIntentEvaluator()
    useful = evaluator.report(
        "$TEST: цена уже у рабочей зоны 1.250–1.255.\n\n"
        "Если LONG подтвердится здесь, мой план: вход около 1.252, TP1 1.275, "
        "TP2 1.292, TP3 1.315. Стоп 1.238. Если уровень не удержат, сделку пропускаю.",
        "TEST",
    )
    spam = evaluator.report(
        "СРОЧНО ПОКУПАЙ $TEST! 100% гарантировано без риска! Точно даст иксы!!!",
        "TEST",
    )
    assert useful.score >= 75, useful
    assert useful.score > spam.score + 25, (useful, spam)
    print(
        f"W2E: OK | hot={hot.score:.1f} live_alt={live_alt.score:.1f} "
        f"cold={cold.score:.1f} useful={useful.score:.1f} spam={spam.score:.1f}"
    )


if __name__ == "__main__":
    main()
