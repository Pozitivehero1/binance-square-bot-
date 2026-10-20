"""Regressions for published factual errors and misleading reach measurements."""
from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evidence_metrics import measured_views, observation
from fact_consistency import fact_consistency_reasons
from news_evidence import draft_reasons, source_has_event
from story_editor import copy_adjustment, market_story_adjustment, story_brief


class Facts(unittest.TestCase):
    def test_published_wrong_comparison(self):
        package={"market_event":{"current_price":"0.05738","vwap":"0.05651"}}
        bad="Цена 0.05738 слегка превысила уровень 0.05652, однако уже опустилась ниже средней 0.05651."
        self.assertIn("price-level-relation-contradiction", fact_consistency_reasons(bad,package))
        self.assertFalse(fact_consistency_reasons("Цена 0.05738 выше средней 0.05651.",package))

    def test_published_wrong_range(self):
        package={"market_event":{"current_price":"0.1886","support":"0.1839"}}
        self.assertIn("price-outside-claimed-range",fact_consistency_reasons("Цена сейчас между ней и 0.1875.",package))
        self.assertIn("price-outside-claimed-range",fact_consistency_reasons("Цена между 0.1839 и 0.1875.",package))

    def test_other_subject_and_conditional_are_not_current_price_claims(self):
        package={"market_event":{"current_price":"110","support":"100"}}
        for text in ("Цена 110; поддержка ниже 100.","Если цена опустится ниже 100, картину придётся оценить заново."):
            self.assertFalse(fact_consistency_reasons(text,package),text)
        self.assertFalse(fact_consistency_reasons('Объём в 2,14 раза выше обычного, но цена снизилась на 4%.',package))

    def test_volume_cannot_become_count(self):
        self.assertIn("volume-is-not-trade-count",fact_consistency_reasons("Сделок стало больше обычного.",{"market_event":{"relative_volume_5m":"x3.28"}}))
        self.assertFalse(fact_consistency_reasons("Объём за 5 минут x3.28 обычного.",{"market_event":{"relative_volume_5m":"x3.28"}}))

    def test_percentage_or_time_is_not_a_price_boundary(self):
        package={'market_event':{'current_price':'0.01','change_5m':'+1.0%'}}
        for text in ('Цена выше на 1%.','Цена выше, чем 5 минут назад.'):
            self.assertFalse(fact_consistency_reasons(text,package),text)

    def test_hourly_average_is_not_available(self):
        self.assertIn("unprovided-hour-average",fact_consistency_reasons("Цена выше средней за час.",{"market_event":{"vwap":"0.5"}}))

    def test_written_timeframes_are_checked(self):
        package={"market_event":{"change_5m":"+1.0%","relative_volume_15m":"x2.0"}}
        self.assertIn("metric-timeframe-mismatch:change_5m",fact_consistency_reasons("За пять минут цена +9.0%.",package))
        self.assertIn("metric-timeframe-mismatch:relative_volume_15m",fact_consistency_reasons("За пятнадцать минут объём x5.0.",package))

    def test_direction_words_preserve_signed_changes(self):
        package={'market_event':{'change_15m':'-4.0%','relative_volume_15m':'x2.14'}}
        self.assertFalse(fact_consistency_reasons('За 15 минут цена снизилась на 4,0% при объёме x2.14.',package))
        self.assertIn('metric-timeframe-mismatch:change_15m',fact_consistency_reasons('За 15 минут цена выросла на 4,0%.',package))
        self.assertFalse(fact_consistency_reasons('Объём за 15 минут в 2,14 раза выше медианы.',package))


class Measurements(unittest.TestCase):
    def test_lifetime_never_fills_missing_snapshot(self):
        post={"published_at":"2026-10-01T00:00:00+00:00","stats":{"views":9999},"last_stats_at":"2026-10-20T00:00:00+00:00"}
        self.assertIsNone(measured_views(post))

    def test_early_legacy_not_24h(self):
        self.assertIsNone(measured_views({"milestones":{"24h":{"age_minutes":1200,"views":999}}}))
        self.assertIsNone(measured_views({"milestones":{"24h":{"views":999}}}))

    def test_valid_fallback_when_preferred_invalid(self):
        post={"content_milestones":{"24h":{"age_minutes":1200,"views":999}},"milestones":{"24h":{"age_minutes":1440,"views":12}}}
        self.assertEqual(measured_views(post),12)

    def test_capture_timestamp_overrides_claimed_age(self):
        post={"published_at":"2026-10-01T00:00:00Z","content_milestones":{"24h":{"captured_at":"2026-10-03T00:00:00Z","age_minutes":1440,"views":999}}}
        self.assertIsNone(measured_views(post))

    def test_zero_valid_missing_and_nonfinite_invalid(self):
        self.assertEqual(measured_views({"milestones":{"24h":{"age_minutes":1440,"views":0}}}),0)
        for views in (None,float('nan'),float('inf'),-1):
            self.assertIsNone(measured_views({"milestones":{"24h":{"age_minutes":1440,"views":views}}}))

    def test_more_posts_cannot_fake_recovery(self):
        import performance_store
        now=datetime(2026,10,20,tzinfo=timezone.utc)
        def row(hours,views):
            return {"published_at":(now-timedelta(hours=hours)).isoformat(),"content_milestones":{"24h":{"age_minutes":1440,"views":views}}}
        posts={str(i):row(30,10) for i in range(80)}
        posts.update({f'old{i}':row(60+i,30) for i in range(30)})
        with patch.object(performance_store,'load_store',return_value={'posts':posts}):
            enabled,current,baseline=performance_store.reach_recovery_state(now)
        self.assertTrue(enabled)
        self.assertEqual((current,baseline),(10,30))

    def test_news_separate_from_observation(self):
        from content_metrics import content_kind
        self.assertEqual(content_kind({'lane':'NEWS','direction':'OBSERVATION'}),'news')

    def test_mature_measurement_survives_profile_pagination(self):
        from collect_stats import due_post_ids
        now=datetime(2026,10,20,tzinfo=timezone.utc)
        post={'post_id':'123','published_at':(now-timedelta(hours=24)).isoformat(),'tracked_from_publish':True}
        self.assertEqual(due_post_ids({'posts':{'123':post}},set(),now=now),['123'])
        self.assertFalse(due_post_ids({'posts':{'123':post}},{'123'},now=now))


class Editorial(unittest.TestCase):
    def test_story_follows_evidence(self):
        market={'change_5m':'-0.8%','change_15m':'+2.0%','relative_volume_5m':'x2.1'}
        brief=story_brief(market)
        self.assertEqual(brief['kind'],'counter_move')
        self.assertEqual(brief['evidence']['change_5m'],'-0.8%')

    def test_semantic_repetition_ignores_ticker_and_price(self):
        previous='$AAA — цена 1.2 возле уровня. Чистой сделки нет, наблюдать честнее. Полезнее следить за движением.'
        new=previous.replace('AAA','BBB').replace('1.2','45.8')
        self.assertLess(copy_adjustment(new,[previous]*3)[0],copy_adjustment(new,[])[0])

    def test_repeated_story_type_is_a_soft_ranking_penalty(self):
        attention=SimpleNamespace(change_15m=2,change_45m=3,volume_spike=4)
        micro=SimpleNamespace(change_5m=.8,volume_spike_5m=4,phase='fresh')
        opportunity=SimpleNamespace(audience_demand=60)
        fresh=market_story_adjustment(attention,micro,opportunity)
        repeated=market_story_adjustment(attention,micro,opportunity,recent_story_kinds=['volume_shock']*8)
        self.assertLess(repeated,fresh)

    def test_format_follows_actual_event_without_duplicate_requests(self):
        from story_editor import prioritize_formats
        formats=['event_one_price','event_pulse','event_price_volume','event_market_story']*3
        selected=prioritize_formats(formats,'counter_move')
        self.assertEqual(len(selected),len(formats))
        self.assertEqual(len(set(selected[:3])),3)
        self.assertNotIn('event_one_price',selected[:3])

    def test_specific_news_requires_exact_event_evidence(self):
        item={'title':'Strive bought Bitcoin for treasury reserves','summary':'The company bought 335 million dollars of Bitcoin after raising capital.'}
        self.assertTrue(source_has_event(item))
        self.assertFalse(draft_reasons('$BTC: Компания купила биткоины на 335 млн.',item['summary'],item))
        self.assertIn('unsupported-news-number',draft_reasons('$BTC: Покупка на 999 млн.',item['summary'],item))
        self.assertIn('missing-exact-event-evidence',draft_reasons('$BTC: Покупка на 335 млн.','An invented quote about another event',item))

    def test_roundup_is_not_an_event(self):
        self.assertFalse(source_has_event({'title':'Latest crypto news today: Bitcoin DeFi and regulation','summary':'This report covers all the latest developments in the cryptocurrency industry.'}))

    def test_keywords_alone_do_not_make_a_strong_hook(self):
        from engagement import FeedAppealEvaluator
        weak=FeedAppealEvaluator().report('$ALT — сейчас цена возле уровня, и это важнее самого движения.\n\nНаблюдаем за рынком.').components['hook']
        strong=FeedAppealEvaluator().report('$ALT — всплеск объёма x3,28, но цена снизилась на 1,7%.\n\nОбъём вырос при снижении цены.').components['hook']
        self.assertLess(weak,60)
        self.assertGreater(strong,weak+20)

    def test_cadence_is_unchanged(self):
        workflow=(Path(__file__).parent/'.github/workflows/run.yml').read_text(encoding='utf-8')
        for expected in ('cron: "*/20 * * * *"','ENABLE_PACING_LIMITS: "0"','MIN_GLOBAL_INTERVAL_MIN: "0"','MAX_POSTS_PER_DAY: "100"','COOLDOWN_MIN: "240"'):
            self.assertIn(expected,workflow)


if __name__=='__main__':
    unittest.main()
