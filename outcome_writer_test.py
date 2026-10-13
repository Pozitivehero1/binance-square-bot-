"""Realistic verified-target and stop-loss copy must never fail closed erroneously."""
from unittest.mock import Mock, patch
from outcome_writer import _deterministic, _valid, build_outcome_post


def facts(symbol, kind, *, entry, reached, stop, rr, move, target="", next_target=None):
    return {
        "symbol": symbol, "market_symbol":symbol+"USDT",
        "event_kind":kind,"target_name":target,
        "entry":entry,"reached_price":reached,"stop":stop,
        "rr":rr,"move_pct":move,"next_target":next_target,
        "prior_targets":"",
        "source_post_id":"12345678901234",
    }


def main():
    cases = [
        facts("BTC","target_complete",entry=83000,reached=85000,stop=82000,rr=2.1,move=2.4,target="tp3"),
        facts("SOL","target",entry=188.9,reached=193.2,stop=187,rr=1.2,move=2.28,target="tp1",next_target=198.2),
        facts("ZEC","stop",entry=1200.2,reached=1188.8,stop=1188.8,rr=-1,move=-0.95),
        facts("MUBARAK","stop_after_target",entry=.07823,reached=.07731,stop=.07731,rr=-1,move=-1.18),
        facts("S","stop",entry=.06021,reached=.05993,stop=.05993,rr=-1,move=-.47),
        facts("PEPE","target_complete",entry=.00000251,reached=.00000285,stop=.0000024,rr=3.1,move=13.55,target="tp3"),
    ]
    with patch("outcome_writer.OUTCOME_AI_ENABLED", False):
        for case in cases:
            drafts = _deterministic(case)
            assert any(_valid(t, case) for t in drafts), (case, drafts)
            value, source = build_outcome_post(case, memory=Mock(similarity_score=lambda *a,**k:0))
            assert source=="deterministic_outcome"
            assert _valid(value, case)
            assert "заработали" not in value
    print("OUTCOME WRITER: OK — TP1, final target, stops, small prices")


if __name__=="__main__":
    main()
