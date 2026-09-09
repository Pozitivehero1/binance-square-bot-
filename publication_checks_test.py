"""Offline regression coverage for publication failover and uncertain sends."""
from contextlib import ExitStack
from datetime import datetime, timezone, timedelta
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
import requests
import ai_provider
import publication_intent as intents
from publisher import publish
from publication_preflight import check_live_plan
from metric_binding import metric_binding_reasons
from content_metrics import build_content_metrics


class Checks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, {'PUBLICATION_INTENT_FILE': self.tmp.name + '/intents.json',
                                      'SQUARE_PROFILE_UID': '', 'SQUARE_API': 'test'})
        env.start(); self.addCleanup(env.stop)
        ai_provider.start_scan_budget()
        self.addCleanup(ai_provider.start_scan_budget)
        root = Path(self.tmp.name)
        (root / 'scripts').mkdir()
        (root / 'scripts/post-text.mjs').touch()
        skill = patch('publisher.find_skill_dir', return_value=str(root))
        skill.start(); self.addCleanup(skill.stop)

    def test_timeout_never_repeats_send(self):
        with patch('publisher.subprocess.run', side_effect=subprocess.TimeoutExpired('node', 90)) as send:
            self.assertFalse(publish('$BTC — наблюдаю за ценой.'))
            self.assertFalse(publish('$BTC — наблюдаю за ценой.'))
            self.assertFalse(publish('$BTC — новый текст наблюдения.'))
            self.assertEqual(send.call_count, 1)
        self.assertIn('BTC', intents.unresolved_symbols())

    def test_timeout_can_be_confirmed_from_profile(self):
        text = '$BTC — наблюдаю за ценой.'
        row = NS(post_id='123', text=text, published_ms=int(time.time()*1000))
        with patch.dict(os.environ, {'SQUARE_PROFILE_UID': 'uid'}), \
             patch('square_public_stats.BinanceSquarePublicClient.recent_posts', return_value=[row]), \
             patch('publisher.subprocess.run', side_effect=subprocess.TimeoutExpired('node', 90)):
            result = publish(text)
        self.assertTrue(result)
        self.assertEqual(result.post_id, '123')
        self.assertEqual(intents.load_intents()[intents.fingerprint(text)]['status'], 'confirmed')

    def test_old_identical_post_does_not_confirm(self):
        text = '$BTC — наблюдаю за ценой.'
        intent = intents.begin(text)
        row = NS(post_id='old', text=text, published_ms=int((time.time()-86400)*1000))
        with patch.dict(os.environ, {'SQUARE_PROFILE_UID': 'uid'}), \
             patch('square_public_stats.BinanceSquarePublicClient.recent_posts', return_value=[row]):
            self.assertEqual(intents.reconcile(text, intent), '')

    def test_corrupt_journal_blocks_send(self):
        Path(os.environ['PUBLICATION_INTENT_FILE']).write_text('{bad')
        with patch('publisher.subprocess.run') as send:
            self.assertFalse(publish('$BTC — наблюдаю за ценой.'))
            send.assert_not_called()

    def test_confirmed_receipt_cannot_duplicate_send(self):
        with patch('publisher.subprocess.run', return_value=NS(stdout='Success!\nID: 123', stderr='', returncode=0)) as send:
            self.assertTrue(publish('$BTC — наблюдаю за ценой.'))
            self.assertFalse(publish('$BTC — наблюдаю за ценой.'))
            self.assertEqual(send.call_count, 1)

    def test_quote_both_directions_stop_target_drift(self):
        for direction, stop, target in [('LONG', 99, 102), ('SHORT', 101, 98)]:
            for price, expected in [(100.1, True), (stop, False), (target, False), (100.6, False)]:
                with self.subTest(direction=direction, price=price), patch('publication_preflight.requests.get', return_value=Mock(json=lambda: {'price': price})):
                    ok, _ = check_live_plan('BTCUSDT', direction, {'entry':100, 'stop':stop, 'tp1':target}, 100)
                    self.assertEqual(ok, expected)

    def test_quote_unavailable_and_nan_fail_closed(self):
        for mock in [Mock(side_effect=requests.Timeout()), Mock(return_value=Mock(json=lambda:{'price':'NaN'}))]:
            with patch('publication_preflight.requests.get', mock):
                self.assertFalse(check_live_plan('BTCUSDT','LONG',{'entry':100,'stop':99,'tp1':102},100)[0])

    def test_metric_swaps_signs_and_units(self):
        market = {'change_5m':'+1.2%', 'change_15m':'-2.4%', 'relative_volume_5m':'x3.1', 'relative_volume_15m':'x1.8', 'rsi_15m':55, 'adx_15m':28}
        for text in ['Цена за 5м +1.2%; за 15м -2.4%.', 'Объём 5м x3.1; объём 15м x1.8.', 'RSI 55, ADX 28', '$BTC +1.2% за 5 минут: что видно по объёму', 'Короткий участок +1.2% — сверяю с 15 минутами']:
            self.assertFalse(metric_binding_reasons(text,market), text)
        for text in ['Цена за 5м -2.4%.','Цена за 15м +2.4%.','Объём 15м x3.1.', 'Оборот за 5м +1.2%.','RSI 28, ADX 55']:
            self.assertTrue(metric_binding_reasons(text,market), text)

    def test_ai_budget_counts_response_format_retry(self):
        ai_provider.start_scan_budget(time.monotonic()+10, 1)
        reply = Mock(status_code=400)
        with patch('ai_provider.requests.post', return_value=reply) as post:
            with self.assertRaises(ValueError):
                ai_provider._request(url='test',key='k',body={'response_format':{}, 'model':'test'},timeout=50,provider='test',retry_without_response_format=True)
            self.assertEqual(post.call_count, 1)
            self.assertLessEqual(post.call_args.kwargs['timeout'], 10)

    def test_expired_ai_budget_never_calls_provider(self):
        ai_provider.start_scan_budget(time.monotonic()-1, 8)
        with patch('ai_provider.requests.post') as post:
            with self.assertRaises(ValueError):
                ai_provider._request(url='test',key='k',body={},timeout=50,provider='test')
            post.assert_not_called()

    def test_cohorts_exclude_missing_and_wrong_age(self):
        now=datetime.now(timezone.utc)
        def row(direction, lane, milestone):
            return {'published_at':(now-timedelta(days=2)).isoformat(), 'direction':direction, 'lane':lane, 'milestones':milestone}
        store={'posts':{'a':row('LONG','EVENT',{'24h':{'age_minutes':1440,'views':200}}),
                        'b':row('observation','EVENT',{}),
                        'c':row('LONG','OUTCOME',{'24h':{'age_minutes':1200,'views':999}})}}
        groups={g['kind']:g for g in build_content_metrics(store,now)['groups']}
        self.assertEqual(groups['trade_plan']['milestones']['24h']['median_views'],200)
        self.assertIsNone(groups['observation']['milestones']['24h']['median_views'])
        self.assertEqual(groups['outcome']['milestones']['24h']['samples'],0)

    def test_candidate_failover_and_three_attempt_limit(self):
        import main
        for fail_all, send_fails in ((False, False), (True, False), (False, True)):
            candidates=[NS(symbol=s,tf_15m=NS(price=100,volume_relative=2,change_1h=1)) for s in ('AAAUSDT','BBBUSDT','CCCUSDT','DDDUSDT')]
            score=NS(total=80,direction='LONG')
            ranked=[(c,score) for c in candidates]
            metric=NS(score=80,phase='fresh',audience_demand=80,change_15m=1,change_5m=1,volume_spike=2,volume_spike_5m=2,event_class='fresh_event')
            adaptive=NS(total=0,hour_affinity=0,hour_samples=0)
            seen=[]
            def choose(pool,*args):
                if not pool:return None
                c,sc=pool[0];seen.append(c.symbol)
                return c,sc,None,metric,metric,metric,metric,{'plan_valid':False},80,adaptive
            draft=NS(text='Наблюдение',source='test',content_format='test',visual_style='test',signal_type='test')
            generated=[None,None,None] if fail_all else [None,(draft,NS(score=80))]
            patches={'DRY_RUN':not send_fails,'PUBLISH_IMAGES':False,'cleanup_history':Mock(),
                     'PostMemory':Mock(return_value=Mock(get_last_lanes=lambda n:[])),
                     'PublicationGuard':Mock(return_value=Mock(evaluate_candidate=lambda **k:NS(reason='ok',score=80,allowed=True))),
                     'reach_recovery_state':Mock(return_value=(False,0,0)), 'process_outcomes':Mock(),
                     'get_trending_market':Mock(return_value=candidates),'get_recently_published':Mock(return_value=[]),
                     'get_btc_context':Mock(return_value=None),'_fetch_many':Mock(return_value={}),
                     '_preliminary_shortlist':Mock(return_value=[c.symbol for c in candidates]),
                     '_build_full_candidates':Mock(return_value=candidates),'_broad_signal_scores':Mock(return_value={}),
                     'get_top_candidates':Mock(return_value=ranked),'_choose_market_candidate':choose,
                     '_choose_event_candidate':Mock(return_value=None), '_best_post_variant':Mock(side_effect=generated),
                     '_prepare_text_for_square':Mock(return_value=('Наблюдение',())),
                     '_try_outcome_fallback':Mock(), 'write_status':Mock(), 'publish':Mock(return_value=False)}
            with ExitStack() as stack:
                for name,value in patches.items():stack.enter_context(patch.object(main,name,value))
                stack.enter_context(patch('recovery_guard.evaluate_recovery_candidate',return_value=NS(reason='ok',allowed=True)))
                self.assertEqual(main._run_once(),2 if send_fails else 0)
                self.assertEqual(seen,['AAAUSDT','BBBUSDT','CCCUSDT'] if fail_all else ['AAAUSDT','BBBUSDT'])
                self.assertEqual(patches['_try_outcome_fallback'].call_count,int(fail_all))
                self.assertEqual(patches['publish'].call_count,int(send_fails))

if __name__ == '__main__':
    unittest.main()
