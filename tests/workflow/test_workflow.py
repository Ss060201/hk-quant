"""Offline regression and end-to-end tests; runnable with unittest or pytest."""
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from hk_quant.data.adapters.tencent import TencentHKProvider
from hk_quant.data.adapters.eastmoney import EastmoneyHKProvider,EastmoneyHKFinancials
from hk_quant.data.normalization import canonicalize_daily_prices
from hk_quant.data.quality import validate_daily_prices,DataQualityError
from hk_quant.workflow.data import merge_prices,DataRouter,writer_lock,prepare_data
from hk_quant.data.storage import DataStorage
from hk_quant.data import models
from hk_quant.workflow.spec import ResearchSpec
from hk_quant.workflow.research import FrozenRepository,make_scorer,preflight,run_frozen,replay,fact_value
from hk_quant.workflow.reference import compare_quotes,import_reference
from hk_quant.backtest.actions import ActionLedger
from hk_quant.backtest.ranking import run_ranking_backtest
from hk_quant.backtest.models import BacktestConfig
from hk_quant.portfolio.positions import Portfolio
from hk_quant.data.adapters.aastocks import parse_quote,capture_samples


def prices(stocks=("0700","0005"), days=6):
    rows=[]
    for stock in stocks:
        for day in pd.bdate_range("2020-01-02",periods=days):
            rows.append(dict(stock_id=stock,trade_date=day,open=10.,high=10.,low=10.,close=10.,
                             volume=1000.,amount=10000.,turnover_rate=.01))
    return canonicalize_daily_prices(pd.DataFrame(rows),"fixture")


def spec(**kwargs):
    data=dict(name="fixture",stocks=["0700","0005"],start="2020-01-02",end="2020-01-09",
              score="close",top_n=1,rebalance=2,commission_rate=0.,slippage_rate=0.)
    data.update(kwargs)
    return ResearchSpec.from_dict(data)


def coverage():
    return {s:dict(verified=True,start="2020-01-01",end="2020-12-31",source_url="https://example.com/fixture") for s in ("0700","0005")}


def repo(frame=None,actions=None,facts=None):
    frame=prices() if frame is None else frame
    return FrozenRepository(frame,pd.DataFrame() if actions is None else actions,
                            pd.DataFrame() if facts is None else facts,sorted(set(frame.trade_date)))


class AdapterTests(unittest.TestCase):
    def test_aastocks_html_is_sample_not_final_close(self):
        html='<div>TENCENT (00700)</div><div>Last Updated: 2026-11-02 16:08</div><div>Open 387.600 Day High 397.600 Day Low 384.600 Last Price 392.200 Volume 22.62M Turnover 8.54B Lot Size/Currency 100 / HKD</div>'
        row=parse_quote(html,"0700")
        self.assertEqual(row["session_status"],"unconfirmed")
        self.assertEqual(row["volume"],"22.62M")
        self.assertEqual(len(capture_samples(["0700"],fetch=lambda u:html)["rows"]),1)
        with self.assertRaises(ValueError):parse_quote('<html>page not found</html>',"0700")

    def test_holiday_and_short_page(self):
        p=TencentHKProvider()
        with patch.object(p,"_request",return_value=[["2020-01-02","10","10","10","10","100"]]) as request:
            self.assertEqual(len(p.get_daily_prices(["0700"],"2020-01-01","2020-01-02")),1)
            self.assertEqual(request.call_count,1)

    def test_bad_numbers_rejected(self):
        for value in ["bad",None,float("inf"),float("nan"),0,-1]:
            p=TencentHKProvider()
            with self.subTest(value=value),patch.object(p,"_paginate",return_value=[["2020-01-02",value,10,10,10,100]]):
                with self.assertRaises(ValueError):p.get_daily_prices(["0700"],"2020-01-02","2020-01-02")

    def test_pagination_budget(self):
        p=TencentHKProvider()
        with patch("hk_quant.data.adapters.tencent._MAX_PAGES",1),patch("hk_quant.data.adapters.tencent._PAGE_SIZE",1),patch.object(p,"_request",return_value=[["2020-01-03",1,1,1,1,1]]):
            with self.assertRaisesRegex(ValueError,"budget"):p._paginate("0700","2020-01-01","2020-01-03")

    def test_eastmoney_percent_once(self):
        payload={"data":{"code":"00700","klines":["2020-01-02,10,10,11,9,100,1000,20,0,0,0.45"]}}
        p=EastmoneyHKProvider(lambda u,q:payload)
        result=p.get_daily_prices(["0700"],"2020-01-02","2020-01-02")
        self.assertAlmostEqual(result.iloc[0].turnover_rate,.0045)
        self.assertEqual(result.iloc[0].amount,1000)

    def test_financial_failure_not_empty_success(self):
        p=EastmoneyHKFinancials(lambda u,q:{"success":False})
        with self.assertRaises(ValueError):p.fetch("0700","income")

    def test_financial_no_original_pit_claim(self):
        p=EastmoneyHKFinancials(lambda u,q:{"result":{"pages":1,"data":[{"REPORT_DATE":"2019-12-31","NOTICE_DATE":"2020-03-01"}]}})
        self.assertFalse(p.fetch("0700","income")["historical_pit_verified"])

    def test_optional_amount_but_required_turnover(self):
        frame=prices();frame["amount"]=float("nan")
        validate_daily_prices(frame,required_fields=["close"])
        frame["turnover_rate"]=float("nan")
        with self.assertRaises(DataQualityError):validate_daily_prices(frame,required_fields=["turnover_rate"])

    def test_merge_preserves_amount(self):
        old=prices();incoming=old.copy();incoming["amount"]=float("nan");incoming["source"]="tencent"
        merged,conflicts=merge_prices(old,incoming)
        self.assertFalse(conflicts);self.assertTrue((merged.amount==10000).all())

    def test_merge_conflict_never_overwrites(self):
        old=prices();incoming=old.copy();incoming["close"]=9
        merged,conflicts=merge_prices(old,incoming)
        self.assertTrue(conflicts);self.assertTrue((merged.close==10).all())

    def test_merge_keeps_supplement_source_on_rerun(self):
        old=prices();old["turnover_rate"]=float("nan")
        new=prices();new["source"]="eastmoney_hk"
        one,_=merge_prices(old,new);two,_=merge_prices(one,new)
        self.assertEqual(json.loads(two.iloc[0].field_sources)["turnover_rate"],"eastmoney_hk")

    def test_router_falls_back(self):
        class Bad:
            name="bad"
            def fetch_raw_daily_prices(self,*args):raise TimeoutError("fixture")
        class Good:
            name="good"
            def fetch_raw_daily_prices(self,*args):return prices(("0700",))
            def normalize_daily_prices(self,raw,stock):return raw
        with tempfile.TemporaryDirectory() as root:
            frame,failures,issues=DataRouter([Bad(),Good()],attempts=2,delay=0).fetch("0700","2020-01-01","2020-01-09",["close"],pd.DataFrame(),None,None,root)
            self.assertEqual(len(frame),6);self.assertEqual(len(failures),2);self.assertFalse(issues)

    def test_writer_lock(self):
        with tempfile.TemporaryDirectory() as root:
            with writer_lock(root):
                with self.assertRaises(RuntimeError):
                    with writer_lock(root):pass


class ResearchTests(unittest.TestCase):
    def test_reference_preserves_revisions(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"input.json"
            rows=[dict(stock_id="0700",metric="roe",value=.1,period_end="2018-12-31",available_date="2019-03-01",currency="ratio",unit="ratio")]
            data=dict(source_url="https://example.com/report",verified=True,rows=rows)
            path.write_text(json.dumps(data));import_reference("facts",path,Path(root)/"data")
            rows[0].update(value=.2,available_date="2019-06-01")
            path.write_text(json.dumps(data));import_reference("facts",path,Path(root)/"data")
            facts=pd.DataFrame(json.loads((Path(root)/"data/reference/facts.json").read_text())["rows"])
            self.assertEqual(fact_value(facts,"0700","roe","2019-04-01"),.1)
            self.assertEqual(fact_value(facts,"0700","roe","2019-07-01"),.2)

    def test_turnover_end_to_end(self):
        r=repo();r.prices.loc[r.prices.stock_id=="0700","turnover_rate"]=.2
        with tempfile.TemporaryDirectory() as root:
            result=run_frozen(spec(score="turnover_rate"),r,root,action_coverage=coverage())
            self.assertEqual(result["status"],"EXPLORATORY")
            trades=pd.read_csv(Path(root)/result["run_id"]/"candidate-trades.csv",dtype={"stock_id":str})
            self.assertEqual(set(trades.stock_id),{"0700"})

    def test_future_change_does_not_change_past_decisions(self):
        r=repo();s=spec(score="momentum_2")
        scorer=make_scorer(s,r)
        cutoff=pd.Timestamp("2020-01-06")
        before=scorer(r.prices[pd.to_datetime(r.prices.trade_date)<=cutoff],"0700")
        r.prices.loc[pd.to_datetime(r.prices.trade_date)>cutoff,"close"]=999
        after=scorer(r.prices[pd.to_datetime(r.prices.trade_date)<=cutoff],"0700")
        self.assertEqual(before,after)

    def test_unknown_strategy_field_rejected(self):
        with self.assertRaises(ValueError):spec(score="eval('bad')")

    def test_snapshot_replay_exact_results(self):
        with tempfile.TemporaryDirectory() as root:
            first=run_frozen(spec(),repo(),root,action_coverage=coverage())
            self.assertEqual(first["status"],"EXPLORATORY")
            second=replay(Path(root)/first["run_id"]/"snapshot.json",root)
            self.assertEqual(first["candidate"],second["candidate"])
            self.assertFalse(first["untouched_final_test"])

    def test_snapshot_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            first=run_frozen(spec(),repo(),root,action_coverage=coverage())
            path=Path(root)/first["run_id"]/"snapshot.json";path.write_text(path.read_text()+" ")
            with self.assertRaisesRegex(ValueError,"checksum"):replay(path,root)

    def test_calendar_detects_joint_missing_day(self):
        r=repo();r.prices=r.prices[r.prices.trade_date!=date(2020,1,3)]
        self.assertTrue(any("missing sessions" in x for x in preflight(spec(),r,action_coverage=coverage())))

    def test_financial_release_not_used_same_day(self):
        facts=pd.DataFrame([dict(stock_id="0700",metric="roe",value=.1,period_end="2019-12-31",available_date="2020-01-03",pit_verified=True,currency="ratio",unit="ratio",source_url="https://example.com")])
        self.assertIsNone(fact_value(facts,"0700","roe","2020-01-03"))
        self.assertEqual(fact_value(facts,"0700","roe","2020-01-06"),.1)

    def test_filters_and_ranking(self):
        r=repo();r.prices.loc[r.prices.stock_id=="0700","turnover_rate"] = .2
        scorer=make_scorer(spec(score="turnover_rate",filters=[dict(field="turnover_rate",op=">",value=.1)]),r)
        self.assertEqual(scorer(r.prices,"0700"),.2);self.assertIsNone(scorer(r.prices,"0005"))

    def test_financial_end_to_end(self):
        facts=pd.DataFrame([dict(stock_id=s,metric="roe",value=v,period_end="2018-12-31",available_date="2019-03-01",pit_verified=True,currency="ratio",unit="ratio",source_url="https://example.com") for s,v in [("0700",.2),("0005",.1)]])
        with tempfile.TemporaryDirectory() as root:
            result=run_frozen(spec(score="fundamental.roe"),repo(facts=facts),root,action_coverage=coverage())
            self.assertEqual(result["status"],"EXPLORATORY")
            trades=pd.read_csv(Path(root)/result["run_id"]/"candidate-trades.csv",dtype={"stock_id":str})
            self.assertEqual(set(trades.stock_id),{"0700"})

    def test_quote_rounding_and_dates(self):
        q={"rows":[dict(stock_id="0700",trade_date="2020-01-02",volume="1.00K",turnover="10.00K",currency="HKD",adjustment="raw_unadjusted",volume_unit="shares",session_status="final")]}
        result=compare_quotes(q,prices());self.assertTrue(all(x["status"]=="MATCH" for x in result["rows"]))
        q["rows"][0]["trade_date"]="2020-01-01"
        self.assertTrue(all(x["status"]=="MISSING_LOCAL" for x in compare_quotes(q,prices())["rows"]))

    def test_missing_actions_block(self):
        self.assertTrue(any("COVERAGE" in x for x in preflight(spec(),repo())))


class ActionTests(unittest.TestCase):
    def test_in_kind_recipient_not_issuer_shares(self):
        p=Portfolio(1000);p.buy("0700",100,10,0,"2020-01-02")
        ledger=ActionLedger(pd.DataFrame([dict(stock_id="0700",event_date="2020-01-03",action_type="distribution_in_kind",recipient_stock_id="9618",recipient_ratio=.1,delivery_date="2020-01-03",verified=True)]))
        ledger.apply(date(2020,1,3),p,{"9618":{"open":20}}, {})
        self.assertEqual(p.positions["0700"].quantity,100);self.assertEqual(p.positions["9618"].quantity,10)

    def test_delayed_distribution_blocks(self):
        p=Portfolio(1000);p.buy("0700",100,10,0,"2020-01-02")
        ledger=ActionLedger(pd.DataFrame([dict(stock_id="0700",event_date="2020-01-03",action_type="distribution_in_kind",recipient_stock_id="9618",recipient_ratio=.1,delivery_date="2020-01-07",verified=True)]))
        with self.assertRaisesRegex(ValueError,"DELAYED"):ledger.apply(date(2020,1,3),p,{"9618":{"open":20}}, {})

    def test_receivable_is_not_spendable_before_payment(self):
        p=Portfolio(1000);p.buy("0700",100,10,0,"2020-01-02")
        ledger=ActionLedger(pd.DataFrame([dict(stock_id="0700",event_date="2020-01-03",action_type="dividend",cash_amount=.5,currency="HKD",payment_date="2020-01-07",verified=True)]))
        ledger.apply(date(2020,1,3),p,{},{});self.assertEqual(p.cash,0);self.assertEqual(ledger.value,50)
        ledger.apply(date(2020,1,7),p,{},{});self.assertEqual(p.cash,50);self.assertEqual(ledger.value,0)

    def test_unknown_currency_blocks(self):
        p=Portfolio(100);p.buy("0700",1,10,0,"2020-01-02")
        ledger=ActionLedger(pd.DataFrame([dict(stock_id="0700",event_date="2020-01-03",action_type="dividend",cash_amount=.5,currency="USD",payment_date="2020-01-07",verified=True)]))
        with self.assertRaises(ValueError):ledger.apply(date(2020,1,3),p,{},{})

    def test_split_preserves_equity(self):
        p=Portfolio(1000);p.buy("0700",100,10,0,"2020-01-02")
        ledger=ActionLedger(pd.DataFrame([dict(stock_id="0700",event_date="2020-01-03",action_type="split",factor=2,verified=True)]))
        marks={"0700":10};ledger.apply(date(2020,1,3),p,{},marks)
        self.assertEqual(p.positions["0700"].quantity,200);self.assertEqual(marks["0700"],5)

    def test_unsupported_rights_block(self):
        p=Portfolio(1000);p.buy("0700",100,10,0,"2020-01-02")
        ledger=ActionLedger(pd.DataFrame([dict(stock_id="0700",event_date="2020-01-03",action_type="rights",verified=True)]))
        with self.assertRaisesRegex(ValueError,"UNMODELED"):ledger.apply(date(2020,1,3),p,{},{})

    def test_rebalance_trims_overweight(self):
        frame=prices();mask=(frame.stock_id=="0700")&(pd.to_datetime(frame.trade_date)>=pd.Timestamp("2020-01-06"))
        frame.loc[mask,["open","high","low","close"]]=20
        result=run_ranking_backtest(repo(frame),["0700","0005"],"2020-01-02","2020-01-09",scorer=lambda h,s:1,top_n=2,rebalance_frequency=1,
                                  config=BacktestConfig(initial_capital=1000,commission_rate=0,slippage_rate=0))
        self.assertTrue(((result.trades.stock_id=="0700")&(result.trades.side=="SELL")).any())


class PrepareTests(unittest.TestCase):
    def test_prepare_is_resumable_and_uses_field_requirements(self):
        class Store:
            _atomic_json=staticmethod(DataStorage._atomic_json)
            def __init__(self):self.frames={}
            def load_daily_prices(self,stock,start,end):return self.frames.get(stock,pd.DataFrame(columns=models.DAILY_PRICE_COLUMNS))
            def save_daily_prices(self,frame):
                for stock,sub in frame.groupby("stock_id"):self.frames[stock]=sub.copy()
        class Provider:
            name="fixture"
            calls=0
            def fetch_raw_daily_prices(self,stocks,start,end):
                self.calls+=1;frame=prices(stocks);frame["amount"]=float("nan");return frame
            def normalize_daily_prices(self,frame,stock):return frame
        class Actions:
            name="fixture"
            def fetch_raw_corporate_actions(self,stock):return pd.DataFrame()
        class Financials:
            reports={}
            def fetch_snapshot(self,stocks):return {"rows":[],"kind":"fixture"}
        store=Store();provider=Provider();sessions=sorted(set(prices().trade_date))
        with tempfile.TemporaryDirectory() as root,patch("hk_quant.workflow.data.expected_sessions",return_value=sessions):
            kwargs=dict(router=DataRouter([provider],attempts=1,delay=0),storage_factory=lambda *a:store,actions_provider=Actions(),financials_provider=Financials())
            one=prepare_data(spec(),root,**kwargs)
            self.assertEqual(one["status"],"READY_FOR_PREFLIGHT")
            calls=provider.calls
            two=prepare_data(spec(),root,**kwargs)
            self.assertEqual(two["status"],"READY_FOR_PREFLIGHT");self.assertEqual(provider.calls,calls)
            self.assertNotEqual(one["run_id"],two["run_id"])
            blocked=prepare_data(spec(score="amount"),root,**kwargs)
            self.assertEqual(blocked["status"],"BLOCKED")


if __name__=="__main__":unittest.main()
