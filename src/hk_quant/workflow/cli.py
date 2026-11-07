"""One entry for plan -> prepare -> preflight -> research -> replay."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

from hk_quant.workflow.spec import ResearchSpec


def read_reference(root,kind,default):
    path=Path(root)/"reference"/f"{kind}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def build_repository(spec,root):
    from hk_quant.workflow.conflicts import conflict_blockers
    blockers = conflict_blockers(spec,root)
    if blockers:
        raise ValueError("; ".join(blockers))
    from hk_quant.data.storage import DataStorage
    from hk_quant.workflow.data import expected_sessions
    from hk_quant.workflow.research import FrozenRepository
    storage=DataStorage(Path(root)/"raw",Path(root)/"processed")
    # Preserve beneficiary instruments needed to value verified in-kind events.
    actions=storage.load_corporate_actions()
    verified=read_reference(root,"actions",{"rows":[]})["rows"]
    if verified:
        manual=pd.DataFrame(verified)
        # Replace entire verified stock/date/type groups, preserving legitimate
        # same-day multiple distributions supplied in that reference group.
        if not actions.empty:
            keys={(r["stock_id"],str(pd.Timestamp(r["event_date"]).date()),r["action_type"]) for r in verified}
            actions=actions[[ (str(r.stock_id),str(pd.Timestamp(r.event_date).date()),r.action_type) not in keys for r in actions.itertuples() ]]
        actions=pd.concat([actions,manual],ignore_index=True)
    recipients={r["recipient_stock_id"] for r in verified if r.get("recipient_stock_id")}
    prices=storage.load_daily_prices(list(set(spec.stocks)|recipients),end_date=spec.end)
    facts=pd.DataFrame(read_reference(root,"facts",{"rows":[]})["rows"])
    sessions=expected_sessions(root,spec.start,spec.end)
    if sessions is None: raise ValueError("independent calendar unavailable; install dependencies or import reference")
    universe=read_reference(root,"universe",None)
    coverage={r["stock_id"]:r for r in read_reference(root,"action_coverage",{"rows":[]})["rows"]}
    return FrozenRepository(prices,actions,facts,sessions,universe=universe),coverage


def execute(spec, root="data", output="experiments/workflows", *, offline=False, refresh=False):
    from hk_quant.workflow.data import prepare_data
    from hk_quant.workflow.research import run_frozen
    if not offline:
        prepared=prepare_data(spec,root,refresh=refresh)
        if prepared["status"]=="BLOCKED": return prepared
    repo,coverage=build_repository(spec,root)
    return run_frozen(spec,repo,output,action_coverage=coverage)


def main(argv=None):
    parser=argparse.ArgumentParser(description="Prepare and run an explicit HK research specification")
    parser.add_argument("command",choices=["plan","prepare","run","update","status","replay","import-reference","compare","capture-quotes","resolve-conflict"])
    parser.add_argument("--spec",type=Path)
    parser.add_argument("--data-root",type=Path,default=Path("data"))
    parser.add_argument("--output",type=Path,default=Path("experiments/workflows"))
    parser.add_argument("--offline",action="store_true")
    parser.add_argument("--refresh",action="store_true")
    parser.add_argument("--file",type=Path)
    parser.add_argument("--kind")
    parser.add_argument("--stocks",nargs="+")
    args=parser.parse_args(argv)
    try:
        if args.command=="resolve-conflict":
            from hk_quant.workflow.conflicts import resolve_conflict
            from hk_quant.workflow.data import writer_lock
            if not args.file: raise ValueError("--file reviewed resolution JSON required")
            with writer_lock(args.data_root):
                result=resolve_conflict(args.data_root,args.file)
        elif args.command=="capture-quotes":
            from hk_quant.data.adapters.aastocks import capture_samples
            from hk_quant.data.storage import DataStorage
            import uuid
            if not args.stocks:raise ValueError("--stocks required")
            result=capture_samples(args.stocks)
            directory=args.data_root/"reference"/"quote_samples"/uuid.uuid4().hex
            directory.mkdir(parents=True,exist_ok=False)
            raw=result.pop("raw_pages")
            DataStorage._atomic_json({"pages":raw},directory/"raw.json")
            DataStorage._atomic_json(result,directory/"quotes.json")
            result={"status":"CAPTURED" if result["rows"] else "BLOCKED","file":str(directory/"quotes.json"),"rows":len(result["rows"]),"failures":result["failures"]}
        elif args.command=="import-reference":
            from hk_quant.workflow.reference import import_reference
            if not args.file or not args.kind: raise ValueError("--file and --kind required")
            result=import_reference(args.kind,args.file,args.data_root)
        elif args.command=="replay":
            from hk_quant.workflow.research import replay
            if not args.file: raise ValueError("--file snapshot.json required")
            result=replay(args.file,args.output)
        elif args.command=="compare":
            from hk_quant.workflow.reference import compare_quotes,validate_reference
            from hk_quant.data.storage import DataStorage
            if not args.file: raise ValueError("--file quote reference required")
            reference=validate_reference("quotes",json.loads(args.file.read_text(encoding="utf-8")))
            storage=DataStorage(args.data_root/"raw",args.data_root/"processed")
            result=compare_quotes(reference,storage.load_daily_prices())
            args.output.mkdir(parents=True,exist_ok=True)
            import uuid
            DataStorage._atomic_json(result,args.output/f"comparison-{uuid.uuid4().hex}.json")
        else:
            if not args.spec: raise ValueError("--spec JSON file required")
            spec=ResearchSpec.from_dict(json.loads(args.spec.read_text(encoding="utf-8")))
            if args.command=="plan":
                result={"status":"PLANNED","spec":spec.to_dict(),"strategy_hash":spec.digest,
                        "required_price_fields":spec.required_prices,"required_financial_metrics":spec.metrics,
                        "universe":spec.universe,"note":"No strategy run and no data downloaded."}
            elif args.command in {"prepare","update"}:
                from hk_quant.workflow.data import prepare_data
                result=prepare_data(spec,args.data_root,refresh=args.refresh)
            elif args.command=="status":
                from hk_quant.workflow.research import preflight
                repo,coverage=build_repository(spec,args.data_root)
                blockers=preflight(spec,repo,action_coverage=coverage)
                result={"status":"BLOCKED" if blockers else "READY_FOR_EXPLORATORY_VALIDATION","blockers":blockers}
            else:
                result=execute(spec,args.data_root,args.output,offline=args.offline,refresh=args.refresh)
    except Exception as exc:
        result={"status":"BLOCKED","blockers":[f"{type(exc).__name__}: {exc}"]}
    print(json.dumps(result,indent=2,ensure_ascii=False,default=str))
    return 2 if result.get("status")=="BLOCKED" else 0


if __name__=="__main__": sys.exit(main())
