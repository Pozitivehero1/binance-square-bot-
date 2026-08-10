"""Offline presentation/level-coherence checks for v8."""
import os
import re
from unittest.mock import patch

from attention import compute_attention
from filters import SignalFilter
from indicators import calculate_multi_timeframe
from self_test import _build_setup
from writer import _levels, generate_post_candidates


for side in ("long", "short"):
    frames = _build_setup(side)
    mtf = calculate_multi_timeframe("PRETTYUSDT", frames)
    score = SignalFilter(min_score=0).evaluate(mtf)
    assert score is not None
    levels = _levels(mtf.tf_15m, side)
    decision = levels["decision"]
    if side == "long":
        assert levels["stop"] < decision < levels["public_target"], levels
    else:
        assert levels["public_target"] < decision < levels["stop"], levels

    attention = compute_attention(frames["15m"], mtf.tf_15m, side)
    with patch.dict(os.environ, {
        "CONTENT_MODE": "deterministic",
        "USE_HASHTAGS": "0",
        "EMOJI_RATE": "0.30",
        "QUESTION_EVERY": "7",
    }, clear=False):
        drafts = generate_post_candidates(
            symbol="PRETTYUSDT", basic="PRETTY", mtf=mtf, score=score,
            levels=levels, attention=attention, variant_count=12,
        )
    assert drafts
    for draft in drafts:
        assert len(draft.text) <= 500
        assert len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", draft.text)) <= 1
        assert "#PriceAction" not in draft.text

print("PRESENTATION: OK | coherent decision level | compact copy | emoji/hashtag guard")
