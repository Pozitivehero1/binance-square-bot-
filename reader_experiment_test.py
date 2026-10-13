"""Tests for measured repeat suppression, stable A/B assignment and cohort math."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from reader_experiment import assigned_arm, arm_for_package, repeat_decision, summarize_arms, ARMS, EXPERIMENT_VERSION, writing_brief


def main():
    now = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
    a = SimpleNamespace(change_15m=1.3, volume_spike=2.2)
    m = SimpleNamespace(change_5m=.4, volume_spike_5m=2.1)
    prev = [{"symbol":"CFXUSDT","ts":(now-timedelta(hours=6)).isoformat()}]
    ok, _ = repeat_decision(prev, "CFXUSDT", a, m, now=now)
    assert not ok
    ok, _ = repeat_decision(prev, "CFXUSDT", SimpleNamespace(change_15m=5,volume_spike=3.3), m, now=now)
    assert ok
    ok, _ = repeat_decision(
        [{"symbol":"CFXUSDT","ts":(now-timedelta(hours=2)).isoformat()}],
        "CFXUSDT", SimpleNamespace(change_15m=5,volume_spike=3.3),m,now=now)
    assert not ok
    assert repeat_decision(prev, "ETHUSDT", a, m, now=now)[0]
    assert assigned_arm("CFX", "EVENT", now=now) == assigned_arm("$CFX", "event", now=now)
    assert set(ARMS) == {"risk_map", "what_changed"}
    assert arm_for_package({"market":{"ticker":"$BTC"}}, "TRADE", now=now) == assigned_arm("BTC","TRADE",now=now)
    assert arm_for_package({"market_event":{"ticker":"$BTC"}}, "EVENT", now=now) == assigned_arm("BTC","EVENT",now=now)
    try:
        arm_for_package({"market_event":{"ticker":"BTC"}}, "TRADE", now=now)
        raise AssertionError("trade package without real ticker should be rejected")
    except ValueError:
        pass
    assert all("ФОРМАТ" in writing_brief(arm,"EVENT") for arm in ARMS)
    posts = {}
    for arm in ARMS:
        for i in range(21):
            posts[f"{arm}{i}"]={"editorial_arm":arm,"editorial_experiment_version":EXPERIMENT_VERSION,"published_at":(now-timedelta(days=2)).isoformat(),
             "milestones":{"24h":{"views":120 if arm=="what_changed" else 45}}}
    metrics=summarize_arms(posts,now=now)
    assert metrics["decision_ready"] is True
    assert metrics["arms"][0]["median_views_24h"]==120
    assert metrics["arms"][1]["median_views_24h"]==45
    posts["old"]={"editorial_arm":"what_changed","published_at":now.isoformat(),"milestones":{"24h":{"views":99999}}}
    assert summarize_arms(posts,now=now)["arms"][0]["samples"]==21
    posts["legacy"]={"editorial_arm":"what_changed","published_at":(now-timedelta(days=2)).isoformat(),
                     "milestones":{"24h":{"views":9000}}}
    assert summarize_arms(posts,now=now)["arms"][0]["samples"]==21
    print("READER EXPERIMENT TEST: OK")


if __name__ == "__main__":
    main()
