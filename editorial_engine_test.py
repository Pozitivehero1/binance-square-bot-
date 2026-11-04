"""Regression tests for v13 sources, author failover and transactional publishing.

Network and publishing are mocked. These tests never use real account credentials.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from runtime import atomic_write_json
from squarebot import market
from squarebot.author import Author, Provider, parse_candidates, configured_providers
from squarebot.metrics import summarize
from squarebot.models import Draft, Settings, Story, utcnow
from squarebot.news import parse_feed, public_url
from squarebot.pipeline import editorial_pass, shortlist
from squarebot.store import Store, similarity
from squarebot.validation import validate


def candles():
    end = int(utcnow().timestamp())//300*300*1000
    rows = []
    for i in range(300):
        stamp = end-(300-i)*300_000
        value = 100+i*.1
        rows.append([stamp, str(value), str(value+.15), str(value-.15), str(value+.05),
                     '20', stamp+299_999, '2600', 10, '10', '1300', '0'])
    return rows


def story(key='s1', kind='mover'):
    return Story(key, kind, ['BTC'], 'Движение биткоина',
                 {'f1': '$BTC: изменение за час +1.50%.',
                  'f2': '$BTC: изменение за четыре часа -2.00%.'},
                 utcnow().isoformat(), 60, event_key='event-'+key)


def good_draft(key='s1'):
    return Draft(key, 'Биткоин отыгрывает часть снижения. [[f1]] [[f2]]\n\n'
                 'Короткий отскок пока укладывается в более широкое падение: часы здесь рассказывают '
                 'разную историю. Для смены общей картины одного положительного часа мало.',
                 format='context', provider='fixture', model='mock')


class Isolated(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'STATE_DIR': str(self.root), 'BOT_VERSION':'v13.0', 'DRY_RUN':'1'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.analytics = patch('performance_store.ANALYTICS_FILE', self.root/'performance_history.json')
        self.analytics.start()
        self.addCleanup(self.analytics.stop)


class MarketTests(unittest.TestCase):
    def test_closed_contiguous_windows(self):
        rows = candles()
        now = rows[-1][6]+1000
        open_row = [rows[-1][0]+300_000]+rows[-1][1:]
        open_row[6] = rows[-1][6]+300_000
        closed = market.closed_candles(rows+[open_row], now)
        self.assertEqual(len(closed), 300)
        m = market.measure({'base':'BTC','symbol':'BTCUSDT','volume':1e9}, closed)
        self.assertAlmostEqual(m['c1h'], (closed[-1][4]/closed[-13][4]-1)*100)
        self.assertAlmostEqual(m['c4h'], (closed[-1][4]/closed[-49][4]-1)*100)
        self.assertAlmostEqual(m['c24h'], (closed[-1][4]/closed[-289][4]-1)*100)
        with self.assertRaisesRegex(ValueError, 'Missing'):
            market.closed_candles(rows[:-7]+rows[-6:], now)
        with self.assertRaisesRegex(ValueError, 'Stale'):
            market.closed_candles(rows, now+600_000)

    def test_universe_excludes_cash_equities_keeps_bnb(self):
        rows = [dict(symbol=s+'USDT',quoteVolume='100000000',lastPrice='1',priceChangePercent='1')
                for s in ['BTC','ETH','BNB','USD1','USDE','NVDAB','SOXLB','USDC']]
        self.assertEqual({r['base'] for r in market.liquid_universe(rows,40)}, {'BTC','ETH','BNB'})

    def test_breakout_uses_prior_window_not_current_high(self):
        rows = market.closed_candles(candles(), int(utcnow().timestamp()*1000))
        rows[-1][4] = rows[-2][2]+1
        rows[-1][2] = rows[-1][4]+.1
        m = market.measure({'base':'BTC','symbol':'BTCUSDT','volume':1e9},rows)
        stories = market.build_stories([m])
        self.assertIn('range_break', [s.kind for s in stories])
        breakout = next(s for s in stories if s.kind == 'range_break')
        self.assertIn('двадцати четырёх часов', breakout.facts['f5'])
        self.assertNotEqual(m['prior_high'], rows[-1][2])


class ValidationTests(unittest.TestCase):
    def test_fact_substitution_carries_sign_period_and_units(self):
        text, reasons = validate(good_draft(), story(), [])
        self.assertFalse(reasons)
        self.assertIn('за час +1.50%', text)
        self.assertIn('за четыре часа -2.00%', text)
        self.assertNotIn('[[', text)

    def test_raw_numbers_unknown_facts_and_participant_fabrication(self):
        for suffix, expected in [(' Цена 50000.', 'unsupported-market-number'),
                                 (' [[f9]]', 'unknown-fact-token'),
                                 (' Киты покупают монету.', 'unsupported-market-participant-claim')]:
            d = good_draft(); d.text += suffix
            self.assertTrue(any(expected in r for r in validate(d, story(), [])[1]))

    def test_free_prose_keeps_measurements_bound(self):
        d=Draft('s1', '$BTC прибавил за час 1.50%, хотя за четыре часа потерял 2.00%. '
                'Короткий отскок пока не отменил более широкое снижение. Здесь важна разница '
                'между локальным восстановлением и направлением за несколько часов.')
        self.assertFalse(validate(d,story(),[])[1])
        d.text=d.text.replace('за час 1.50%', 'за четыре часа 1.50%')
        self.assertIn('measurement-not-bound-to-asset-unit-and-timeframe',validate(d,story(),[])[1])

    def test_wrong_sign_and_broken_substitution_are_rejected(self):
        d=Draft('s1', '$BTC потерял за час 1.50%. За четыре часа цена потеряла 2.00%. '
                'Короткий отскок пока не отменил более широкое снижение. Здесь важна разница '
                'между локальным восстановлением и направлением за несколько часов.')
        self.assertIn('measurement-direction-contradicts-evidence',validate(d,story(),[])[1])
        d=good_draft();d.text=d.text.replace('[[f1]]', '[[f1]];')
        self.assertIn('broken-measurement-punctuation',validate(d,story(),[])[1])

    def test_truthful_caution_is_not_a_participant_claim(self):
        d=good_draft();d.text+=' Это не доказывает накопление позиций.'
        self.assertNotIn('unsupported-market-participant-claim',validate(d,story(),[])[1])

    def test_changing_numbers_and_tickers_does_not_hide_template(self):
        a = '$BTC вырос на 2%. За коротким отскоком пока нет изменения более широкой картины рынка.'
        b = '$ETH вырос на 5%. За коротким отскоком пока нет изменения более широкой картины рынка.'
        self.assertGreater(similarity(a,b), .9)
        d = good_draft(); text,_ = validate(d,story(),[])
        self.assertIn('repeated-narrative', ' '.join(validate(d,story(),[{'text':text}])[1]))

    def test_news_evidence_required_and_no_invented_amount(self):
        s = Story('n','news',['BTC'],'Company announces Bitcoin fund',{},utcnow().isoformat(),
                  source_text='Company announces Bitcoin fund. The firm said the product will launch next month.')
        d = Draft('n','Компания объявила о новом фонде, связанном с $BTC. По её заявлению, '
                  'запуск продукта планируется в следующем месяце. Это объявление о планах компании; '
                  'оно само по себе не означает, что фонд уже начал работать.',
                  title='Компания объявила о планах запуска биткоин-фонда',
                  evidence_quote='Company announces Bitcoin fund.')
        self.assertFalse(validate(d,s,[])[1])
        d.text += ' Объем фонда 100 миллионов.'
        self.assertIn('unsupported-news-number',validate(d,s,[])[1])
        d.evidence_quote = 'invented quote'
        self.assertIn('missing-verbatim-source-evidence',validate(d,s,[])[1])


class NewsTests(unittest.TestCase):
    def test_feed_without_cover_is_still_a_story_and_old_items_rejected(self):
        now = utcnow()
        def xml(date):
            return ('<rss><channel><item><title>Bitcoin company announces a new fund</title>'
                    '<link>https://example.com/story?utm_source=rss</link>'
                    '<description>The company said it plans to launch a new Bitcoin fund next month.</description>'
                    f'<pubDate>{date:%a, %d %b %Y %H:%M:%S %z}</pubDate></item></channel></rss>').encode()
        rows = parse_feed(xml(now),now=now)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].source_url,'https://example.com/story')
        self.assertEqual(rows[0].image_url,'')
        self.assertFalse(parse_feed(xml(now-timedelta(days=2)),now=now))

    def test_private_cover_urls_rejected(self):
        with self.assertRaises(ValueError):
            public_url('http://127.0.0.1/a')
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError):
                public_url('https://example.com/a')


class AuthorTests(Isolated):
    def test_provider_budget_and_cooldown_survive_next_scan(self):
        p = Provider('test','https://example.com/v1/chat/completions','m','secret')
        author = Author(Settings(max_ai_calls=1),[p])
        response = Mock(status_code=429,headers={'Retry-After':'120'},text='limited')
        with patch('squarebot.author.requests.post',return_value=response) as post:
            self.assertEqual(list(author.drafts([story()],[])),[])
            self.assertEqual(post.call_count,1)
        next_author = Author(Settings(max_ai_calls=1),[p])
        with patch('squarebot.author.requests.post') as post:
            self.assertEqual(list(next_author.drafts([story()],[])),[])
            post.assert_not_called()
        self.assertNotIn('secret',self.path_text())

    def path_text(self):
        return (self.root/'editor_providers.json').read_text()

    def test_empty_reasoning_is_not_publishable_content(self):
        with self.assertRaises(ValueError):
            parse_candidates({'choices':[{'message':{'content':'','reasoning':'{"candidates":[{"text":"leak"}]}'}}]})

    def test_invalid_json_uses_next_provider_and_key_default_supports_official(self):
        ps = [Provider('a','https://example.com/v1/chat/completions','a','x'),
              Provider('b','https://example.com/v1/chat/completions','b','y')]
        bad = Mock(status_code=200,headers={},json=lambda:{'choices':[{'message':{'content':'bad'}}]})
        good = Mock(status_code=200,headers={},json=lambda:{'choices':[{'message':{'content':json.dumps({'candidates':[{'story_id':'s1','text':'draft'}]})}}]})
        author=Author(Settings(max_ai_calls=2),ps)
        with patch('squarebot.author.requests.post',side_effect=[bad,good]) as request:
            gen=author.drafts([story()],[])
            self.assertEqual(next(gen)[0].provider,'b'); gen.close()
            self.assertEqual(request.call_count,2)
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY':'key','DEEPSEEK_BASE_URL':''},clear=True):
            self.assertEqual(configured_providers()[0].url,'https://api.deepseek.com/v1/chat/completions')


class PipelineTests(Isolated):
    def execute(self, dry_run=False, result=None, source=None):
        from publisher import PublishResult
        if result is None:
            result=PublishResult(True,post_id='123456')
        if source is None:
            source=[story()]
        def drafts(*args):
            yield [good_draft()]
        with patch('squarebot.pipeline.configured_providers',return_value=[Mock()]), \
             patch('squarebot.pipeline.find_skill_dir',return_value='/publisher'), \
             patch.dict(os.environ,{'SQUARE_API':'mock'}), \
             patch('squarebot.market.scan',return_value=source), \
             patch('squarebot.news.scan',return_value=[]), \
             patch('squarebot.author.Author.drafts',side_effect=drafts), \
             patch('squarebot.pipeline.visuals.chart',return_value=None), \
             patch('squarebot.pipeline.publish',return_value=result) as send:
            code=editorial_pass(Settings(dry_run=dry_run))
            return code, send.call_count

    def test_confirmed_publication_tracked_once_no_rewrite_resend(self):
        code, calls=self.execute()
        self.assertEqual((code,calls),(0,1))
        state=Store(); self.assertEqual(len(state.data['posts']),1)
        self.assertTrue(state.data['posts'][0]['analytics_recorded'])
        analytics=json.loads((self.root/'performance_history.json').read_text())
        self.assertEqual(analytics['posts']['123456']['engine_version'],'v13.0')
        self.assertEqual(analytics['posts']['123456']['direction'],'OBSERVATION')
        self.assertEqual(self.execute(),(0,0))

    def test_ambiguous_send_keeps_story_reserved(self):
        from publisher import PublishResult
        self.assertEqual(self.execute(result=PublishResult(False,stderr='timeout')),(1,1))
        state=Store(); self.assertIn('s1',state.data['pending'])
        # Mimic the transport journal persisted before the remote call.
        import publication_intent
        publication_intent.begin(state.data['pending']['s1']['text'])
        with patch('publication_intent._recent_posts',return_value=[]):
            self.assertEqual(self.execute(),(0,0))
        self.assertIn('s1',Store().data['pending'])

    def test_dry_run_does_not_reserve_or_send(self):
        self.assertEqual(self.execute(dry_run=True),(0,0))
        self.assertFalse(Store().data['pending'])
        self.assertFalse(Store().data['posts'])
        self.assertEqual(json.loads((self.root/'status.json').read_text())['status'],'dry_run')

    def test_dead_sources_fail_honestly(self):
        self.assertEqual(self.execute(source=[]),(1,0))
        self.assertEqual(json.loads((self.root/'status.json').read_text())['status'],'failed')

    def test_corrupt_state_does_not_reset_send_memory(self):
        (self.root/'editorial_v13.json').write_text('{"posts":[],"pending":null}')
        with self.assertRaises(ValueError):
            Store()

    def test_crash_after_transport_receipt_reconciles_without_resending(self):
        from publication_intent import begin,confirm
        store=Store(); s=story(); d=good_draft();d.text=validate(d,s,[])[0]
        store.reserve(s,d);begin(d.text);confirm(d.text,'456789')
        store=Store();store.reconcile()
        self.assertEqual(store.data['posts'][0]['post_id'],'456789')
        self.assertFalse(store.data['pending'])

    def test_old_poor_performance_never_vetoes_new_topics(self):
        store=Store()
        chosen=shortlist([story()],store,[],[{'engine_version':'v12.8','stats':{'views':0}}]*30)
        self.assertEqual(len(chosen),1)


class MetricsTests(unittest.TestCase):
    def test_lifetime_views_do_not_become_24h_observations(self):
        now=utcnow()
        rows=[{'engine_version':'v13.0','published_at':(now-timedelta(hours=48)).isoformat(),
               'stats':{'views':99999},'last_stats_at':now.isoformat()}]
        report=summarize(rows,now=now)
        self.assertEqual(report['current']['24h']['samples'],0)
        self.assertIsNone(report['current']['24h']['median_views'])
        self.assertFalse(report['comparison_ready'])


if __name__=='__main__':
    unittest.main(verbosity=2)
