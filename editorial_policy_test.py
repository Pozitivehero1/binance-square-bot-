"""Story selection and plain-language quality checks without network access."""
from dataclasses import dataclass
from unittest.mock import patch
from editorial_policy import evaluate_story, review_copy, event_publication_levels


@dataclass
class Attention:
    change_15m: float
    change_45m: float
    volume_spike: float


@dataclass
class Micro:
    change_5m: float
    volume_spike_5m: float
    phase: str = "fresh"


@dataclass
class Opportunity:
    audience_demand: float = 74
    score: float = 78
    event_class: str = "fresh_event"


def main():
    opp = Opportunity()
    assert not evaluate_story(Attention(.09,.23,1.15),Micro(.03,1.1),opp,lane="EVENT").allowed
    assert evaluate_story(Attention(1.9,2.5,2.4),Micro(.9,2.0),opp,lane="EVENT").allowed
    assert evaluate_story(Attention(-4,-8,1.1),Micro(.2,.7),opp,lane="EVENT").allowed
    assert not evaluate_story(Attention(1.4,2.5,2.4),Micro(.2,.7,"stale"),opp,lane="EVENT").allowed
    assert not evaluate_story(Attention(.8,2,2),Micro(.4,2),Opportunity(5),lane="EVENT").allowed
    assert not evaluate_story(Attention(.4,.5,1.1),Micro(.2,.6),opp,lane="TRADE").allowed
    strong = "$BTC — объём вырос x3 после движения +2.4% за 15 минут\n\nРеальный всплеск активности требует проверки уровня."
    assert review_copy(strong).allowed
    weak = "$BTC торгуется по цене 56.4\n\nНаблюдаем за реакцией. Ждём чистую реакцию рынка."
    assert not review_copy(weak).allowed
    broken = "$BTC — объём на\n\n15 минутах вырос x4.0."
    assert not review_copy(broken).allowed
    levels = {"plan_valid":True,"entry":1}
    with patch.dict("os.environ", {"EVENT_OBSERVATION_PREFERRED":"1"}):
        assert event_publication_levels("event", levels) == {"plan_valid":False}
        assert event_publication_levels("trade", levels) == levels
    assert levels["plan_valid"] is True
    print("EDITORIAL POLICY TEST: OK")


if __name__ == "__main__":
    main()
