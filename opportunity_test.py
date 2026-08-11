"""Offline checks for the v9 audience/freshness opportunity ranking."""
from attention import AttentionSnapshot, MicroAttentionSnapshot
from opportunity import score_market_opportunity, volume_anomaly_score
from trend import TrendingMarket


def snap(score, m15, m45, vol, extended=False):
    return AttentionSnapshot(
        score=score, change_15m=m15, change_45m=m45, volume_spike=vol,
        range_expansion=2.0, turnover_1h=8_000_000,
        distance_atr=3.0 if extended else 1.2, label="test", overextended=extended,
    )


def micro(score, *, phase="fresh", stale=0.0, vol=3.0, m5=0.8, m15=1.5, age=0):
    return MicroAttentionSnapshot(
        score=score, change_5m=m5, change_15m=m15, volume_spike_5m=vol,
        return_impulse=4.0, volume_impulse=75.0, acceleration=1.8,
        event_age_bars=age, phase=phase, stale_penalty=stale,
    )


def main() -> None:
    universe = [
        TrendingMarket("BTCUSDT", 50, 20_000_000_000, 4_000_000, 1.0, 100_000, 1),
        TrendingMarket("ETHUSDT", 48, 10_000_000_000, 3_000_000, 1.0, 4_000, 2),
        TrendingMarket("TAOUSDT", 42, 900_000_000, 900_000, 3.0, 203, 6),
        TrendingMarket("XRPUSDT", 45, 2_500_000_000, 1_800_000, 2.0, 1.0, 4),
        TrendingMarket("LOWCAPUSDT", 41, 25_000_000, 45_000, 12.0, 0.2, 32),
        TrendingMarket("PUMPYUSDT", 41, 80_000_000, 150_000, 35.0, 0.2, 24),
        TrendingMarket("QUIETUSDT", 20, 40_000_000, 60_000, 0.2, 1.0, 40),
    ]
    meta = {item.symbol: item for item in universe}

    audience_fresh = score_market_opportunity(
        meta=meta["TAOUSDT"], universe=universe,
        attention=snap(84, 1.4, 3.0, 5.0, False), micro=micro(88, vol=5.0),
        technical_score=76, risk_reward=2.0, strict_setup=True,
    )
    stale_x35 = score_market_opportunity(
        meta=meta["LOWCAPUSDT"], universe=universe,
        attention=snap(76, 0.5, 2.1, 35.0, False),
        micro=micro(38, phase="stale", stale=24.0, vol=0.6, m5=0.05, age=5),
        technical_score=82, risk_reward=2.1, strict_setup=True,
    )
    extreme_pump = score_market_opportunity(
        meta=meta["PUMPYUSDT"], universe=universe,
        attention=snap(90, 18.7, 26.4, 4.0, True), micro=micro(80, vol=4.0),
        technical_score=76, risk_reward=1.7, strict_setup=True,
    )
    quiet = score_market_opportunity(
        meta=meta["QUIETUSDT"], universe=universe,
        attention=snap(35, 0.18, 0.4, 0.8, False),
        micro=micro(35, phase="ordinary", stale=0.0, vol=0.8, m5=0.03, age=2),
        technical_score=85, risk_reward=2.0, strict_setup=True,
    )

    assert audience_fresh.score > stale_x35.score + 15, (audience_fresh, stale_x35)
    assert audience_fresh.score > extreme_pump.score, (audience_fresh, extreme_pump)
    assert audience_fresh.score > quiet.score + 18, (audience_fresh, quiet)
    assert stale_x35.stale_penalty >= 20
    # Raw volume intentionally saturates: x35 is not dramatically stronger than x5.
    assert volume_anomaly_score(35.0) - volume_anomaly_score(5.0) < 45
    print(
        "OPPORTUNITY: OK | "
        f"audience_fresh={audience_fresh.score:.1f} stale_x35={stale_x35.score:.1f} "
        f"extreme_pump={extreme_pump.score:.1f} quiet={quiet.score:.1f}"
    )


if __name__ == "__main__":
    main()
