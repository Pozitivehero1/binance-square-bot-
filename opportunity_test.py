"""Offline checks for the Market Attention v7 ranking."""
from attention import AttentionSnapshot
from opportunity import score_market_opportunity
from trend import TrendingMarket


def snap(score, m15, m45, vol, extended=False):
    return AttentionSnapshot(
        score=score,
        change_15m=m15,
        change_45m=m45,
        volume_spike=vol,
        range_expansion=2.0,
        turnover_1h=8_000_000,
        distance_atr=3.0 if extended else 1.2,
        label="test",
        overextended=extended,
    )


universe = [
    TrendingMarket("BTCUSDT", 50, 20_000_000_000, 4_000_000, 1.0, 100_000, 1),
    TrendingMarket("ETHUSDT", 48, 10_000_000_000, 3_000_000, 1.0, 4_000, 2),
    TrendingMarket("TAOUSDT", 42, 900_000_000, 900_000, 3.0, 203, 12),
    TrendingMarket("TSTUSDT", 39, 250_000_000, 500_000, 6.0, 0.02, 20),
    TrendingMarket("PUMPYUSDT", 41, 80_000_000, 150_000, 35.0, 0.2, 34),
    TrendingMarket("QUIETUSDT", 20, 40_000_000, 60_000, 0.2, 1.0, 60),
]
meta = {item.symbol: item for item in universe}

tao_like = score_market_opportunity(
    meta=meta["TAOUSDT"], universe=universe,
    attention=snap(88, 1.2, 2.5, 22.9, True),
    technical_score=76, risk_reward=1.7, strict_setup=True,
)
extreme_pump = score_market_opportunity(
    meta=meta["PUMPYUSDT"], universe=universe,
    attention=snap(90, 18.7, 26.4, 4.0, True),
    technical_score=76, risk_reward=1.7, strict_setup=True,
)
quiet = score_market_opportunity(
    meta=meta["QUIETUSDT"], universe=universe,
    attention=snap(35, 0.18, 0.4, 0.8, False),
    technical_score=85, risk_reward=2.0, strict_setup=True,
)

assert tao_like.score > extreme_pump.score, (tao_like, extreme_pump)
assert tao_like.score > quiet.score + 20, (tao_like, quiet)
assert tao_like.volume_anomaly > 95
assert extreme_pump.saturation_penalty > 10
print(
    "OPPORTUNITY: OK | "
    f"TAO-like={tao_like.score:.1f} extreme-pump={extreme_pump.score:.1f} quiet={quiet.score:.1f}"
)
