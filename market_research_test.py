"""Regressions from the Oct 21 live feed; research uses closed history only."""
import unittest
from types import SimpleNamespace
import pandas as pd
from market_research import candle_research
from fact_consistency import fact_consistency_reasons
from story_editor import story_brief, market_story_adjustment, copy_adjustment, author_fact_package
from news_evidence import draft_reasons


def candles():
    return pd.DataFrame({'open':[100,100,100,101,103,104],'close':[100,100,100,102,104,106],
                         'high':[101,101,101,103,105,120],'low':[99,99,99,101,103,104],
                         'volume':[10,10,10,10,10,20]},
                        index=pd.date_range('2026-10-21',periods=6,freq='15min',tz='UTC'))


class Research(unittest.TestCase):
    def test_prior_range_excludes_current_spike(self):
        result=candle_research(candles())
        self.assertEqual(result['prior_1h_high'],'105')
        self.assertEqual(result['prior_1h_low'],'99')
        self.assertEqual(result['change_1h'],'+6.00%')
        self.assertEqual(result['previous_change_15m'],'+1.96%')
        self.assertEqual(result['volume_vs_previous_15m'],'x2.00')

    def test_holes_and_short_history_are_not_called_one_hour(self):
        self.assertFalse(candle_research(candles().iloc[:4]))
        hole=candles();hole.index=pd.date_range('2026-10-21',periods=6,freq='30min',tz='UTC')
        self.assertFalse(candle_research(hole))

    def test_zero_volume_never_invents_a_ratio(self):
        frame=candles();frame.loc[frame.index[-2],'volume']=0
        self.assertNotIn('volume_vs_previous_15m',candle_research(frame))

    def test_quote_volume_is_preserved_and_used(self):
        from data import _normalize_ohlcv
        from attention import compute_attention
        frame=pd.concat([candles()]*6,ignore_index=True)
        frame.index=pd.date_range('2026-10-21',periods=len(frame),freq='15min',tz='UTC')
        frame['quote_volume']=1234
        normalized=_normalize_ohlcv(frame)
        self.assertIn('quote_volume',normalized)
        attention=compute_attention(normalized,SimpleNamespace(price=106,ema20=100,atr=10,rsi=50),'long')
        self.assertEqual(attention.turnover_1h,4936)
        self.assertTrue(attention.research)

    def test_large_move_is_not_labelled_as_just_volume(self):
        self.assertEqual(story_brief({'change_15m':'6%','change_45m':'7%','relative_volume_15m':'x4'})['kind'],'price_displacement')

    def test_hour_break_uses_observed_prior_range(self):
        self.assertEqual(story_brief({'current_price':'106','resistance':'130','observed_context':candle_research(candles())})['kind'],'above_range')

    def test_observation_author_sees_research_without_unrelated_levels(self):
        package={'market_event':{'ticker':'$ALT','support':'1','observed_context':candle_research(candles())},'optional_trade_plan':{'available':False},'editorial_brief':{'kind':'above_range'}}
        public=author_fact_package(package,focus_story=True)['market_event']
        self.assertIn('observed_context',public)
        self.assertNotIn('support',public)
        self.assertIn('support',package['market_event'])

    def test_hidden_levels_cannot_leak_through_editorial_evidence(self):
        package={'market_event':{'ticker':'$ALT','support':'1','observed_context':candle_research(candles())},'optional_trade_plan':{'available':False},'editorial_brief':{'kind':'below_range','evidence':{'support':'1','observed_context':candle_research(candles())}}}
        clean=author_fact_package(package,focus_story=True)
        self.assertNotIn('support',clean['editorial_brief']['evidence'])
        self.assertIn('observed_context',clean['editorial_brief']['evidence'])

    def test_sequential_returns_can_name_previous_period_as_first(self):
        package={'market_event':{'change_15m':'-1.9%','previous_change_15m':'-1.46%'}}
        self.assertFalse(fact_consistency_reasons('Сначала 15 минут дали -1.46%, затем следующие -1.9%.',package))

    def test_range_break_does_not_prove_persistence(self):
        package={'market_event':{'observed_context':candle_research(candles())}}
        self.assertIn('range-snapshot-is-not-persistence-history',fact_consistency_reasons('Ниже этой отметки цена не первый отрезок.',package))

    def test_isolated_volume_noise_loses_soft_rank_to_price_event(self):
        opportunity=SimpleNamespace(audience_demand=60)
        flat=market_story_adjustment(SimpleNamespace(change_15m=.1,change_45m=.2,volume_spike=8),SimpleNamespace(change_5m=.05,volume_spike_5m=8,phase='fresh'),opportunity)
        move=market_story_adjustment(SimpleNamespace(change_15m=2,change_45m=3,volume_spike=2),SimpleNamespace(change_5m=.8,volume_spike_5m=2,phase='fresh'),opportunity)
        self.assertGreater(move,flat+10)

    def test_public_window_fallacy_is_rejected(self):
        for text in ('Всплеск не перешёл в более длинное окно.','Через пятнадцать минут объём уже x1.39.','Всплеск оказался коротким.'):
            self.assertIn('different-windows-are-not-event-sequence',fact_consistency_reasons(text,{'market_event':{}}))
        self.assertFalse(fact_consistency_reasons('Если объём будет снижаться, стоит проверить движение заново.',{'market_event':{}}))

    def test_turnover_cannot_establish_liquidity(self):
        self.assertIn('turnover-is-not-orderbook-liquidity',fact_consistency_reasons('Оборот за час $921K означает низкую ликвидность.',{'market_event':{}}))
        self.assertFalse(fact_consistency_reasons('Оборот за час составил $921K.',{'market_event':{}}))

    def test_previous_and_hour_returns_bind_to_their_own_measurements(self):
        market={'change_15m':'+1%','previous_change_15m':'-2%','change_1h':'+6%'}
        for text in ('За предыдущие 15 минут цена -2%.','За час цена +6%.'):
            self.assertFalse(fact_consistency_reasons(text,{'market_event':market}),text)
        self.assertIn('metric-timeframe-mismatch:change_1h',fact_consistency_reasons('За час цена +1%.',{'market_event':market}))
        self.assertIn('metric-timeframe-mismatch:previous_change_15m',fact_consistency_reasons('За предыдущие 15 минут цена +1%.',{'market_event':market}))

    def test_same_frame_volume_comparison_not_bound_to_median(self):
        package={'market_event':{'relative_volume_15m':'x8','observed_context':{'volume_vs_previous_15m':'x2'}}}
        self.assertFalse(fact_consistency_reasons('Объём за 15 минут в 2 раза выше предыдущей свечи.',package))

    def test_empty_disclaimer_is_not_useful_explanation(self):
        empty='$AAA — объём x3, а цена +0.1%. Снимок фиксирует прохождение монет, но не объясняет причины движения. Стоит открыть тикер.'
        useful='$AAA — цена +2% и вышла выше верхней границы предыдущего часа. Однако последнее движение меньше предыдущего, поэтому темп роста снизился.'
        self.assertGreater(copy_adjustment(useful)[0],copy_adjustment(empty)[0])

    def test_news_cannot_publish_prompt_limitations(self):
        item={'title':'FINMA approved a Bitcoin fund for retail investors','summary':'FINMA approved a Bitcoin fund for retail investors with custody safeguards.'}
        self.assertIn('internal-source-instructions-in-public-copy',draft_reasons('Сроки запуска во входных данных не приводятся.',item['summary'],item))

    def test_missing_rss_detail_is_not_company_nondisclosure(self):
        item={'title':'FINMA approved a Bitcoin fund for retail investors','summary':'FINMA approved a Bitcoin fund for retail investors with custody safeguards.'}
        self.assertIn('unsupported-claim-of-nondisclosure',draft_reasons('Условия запуска не раскрываются.',item['summary'],item))
        self.assertNotIn('unsupported-claim-of-nondisclosure',draft_reasons('FINMA одобрила фонд.',item['summary'],item))

    def test_production_records_story_kind_without_breaking_card_signature(self):
        import ast,inspect
        from pathlib import Path
        from card import generate_card
        tree=ast.parse((Path(__file__).parent/'main.py').read_text(encoding='utf-8'))
        memory_calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='add_post']
        self.assertTrue(memory_calls)
        self.assertTrue(all('story_kind' in {k.arg for k in n.keywords} for n in memory_calls))
        for call in (n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='generate_card'):
            self.assertLessEqual({k.arg for k in call.keywords},set(inspect.signature(generate_card).parameters))

    def test_story_history_restores_only_exact_known_publications(self):
        from story_editor import restore_story_kinds
        items=[{'text':'same'},{'text':'different'},{'text':'same','story_kind':'kept'}]
        restore_story_kinds(items,{'1':{'text':'same','fact_package':{'editorial_brief':{'kind':'volume_shock'}}},'2':{'text':'different','fact_package':[]}})
        self.assertEqual([r['story_kind'] for r in items],['volume_shock','','kept'])

    def test_story_kind_survives_disk_reload(self):
        import tempfile
        from pathlib import Path
        from memory import PostMemory
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'memory.json'
            memory=PostMemory(path=path)
            memory.add_post('ALTUSDT','$ALT — measured story',story_kind='below_range')
            self.assertEqual(PostMemory(path=path).items[-1]['story_kind'],'below_range')

    def test_chart_anchor_matches_researched_range(self):
        from event_writer import event_decision_level
        indicator=SimpleNamespace(price=106,support=98,resistance=130,vwap=106.1,ema20=106.2)
        package={'market_event':{'observed_context':{'prior_1h_high':'105','prior_1h_low':'99'}},'editorial_brief':{'kind':'above_range'}}
        self.assertEqual(event_decision_level(indicator,package),105)
        self.assertNotEqual(event_decision_level(indicator),105)


if __name__=='__main__':
    unittest.main()

