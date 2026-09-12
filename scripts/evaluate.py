from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from trade_copilot.context_engine import ContextEngine
from trade_copilot.domain.models import ConversationTurn, QueryRequest
from trade_copilot.service import get_services


async def run(dataset_path: Path, end_to_end: bool) -> dict:
    started = time.perf_counter()
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    gold_path = dataset_path.with_name(f"{dataset_path.stem}.gold.json")
    gold_by_id = json.loads(gold_path.read_text(encoding="utf-8")) if gold_path.exists() else {}
    services = get_services()
    context_engine = ContextEngine()
    rows = []
    jurisdiction_hits = 0
    retrieval_recalls = []
    reciprocal_ranks = []
    evidence_recalls = []
    status_hits = 0
    request_errors = 0
    for case_index, case in enumerate(cases, start=1):
        request = QueryRequest(
            query=case["query"],
            answer_language=case.get("answer_language", "zh"),
            conversation=[ConversationTurn.model_validate(item) for item in case.get("conversation", [])],
            jurisdictions=case.get("request_jurisdictions", []),
        )
        context = context_engine.build(request)
        jurisdiction_hits += {item.value for item in context.jurisdictions} == set(case["jurisdictions"])
        error = None
        try:
            candidates = (
                []
                if context.needs_clarification
                else await services.workflow.retriever.retrieve(context)
            )
        except Exception as exc:  # noqa: BLE001 - evaluation records and continues per case
            candidates = []
            request_errors += 1
            error = type(exc).__name__
        ids = [item.chunk.document_id for item in candidates]
        expected_ids = case.get("relevant_document_ids", [])
        ranks = [ids.index(expected) + 1 for expected in expected_ids if expected in ids]
        recall = None
        if expected_ids:
            recall = len(ranks) / len(expected_ids)
            retrieval_recalls.append(recall)
            reciprocal_ranks.append(1 / min(ranks) if ranks else 0)
        gold_evidence = gold_by_id.get(case["id"], [])
        evidence_recall = None
        if gold_evidence:
            hits = 0
            for gold in gold_evidence:
                if any(
                    item.chunk.document_id == gold["document_id"]
                    and item.chunk.page in gold["pages"]
                    for item in candidates
                ):
                    hits += 1
            evidence_recall = hits / len(gold_evidence)
            evidence_recalls.append(evidence_recall)
        response = None
        status_match = None
        if end_to_end:
            response = (await services.workflow.invoke(request)).model_dump(mode="json")
            status_match = response["status"] == case.get("expected_status")
            status_hits += bool(status_match)
        rows.append(
            {
                "id": case["id"],
                "retrieved_document_ids": ids,
                "recall_at_5": recall,
                "evidence_recall_at_5": evidence_recall,
                "status_match": status_match,
                "error": error,
                "response": response,
            }
        )
        if case_index % 10 == 0 or case_index == len(cases):
            print(f"progress: {case_index}/{len(cases)}", flush=True)
    count = max(len(cases), 1)
    return {
        "dataset": str(dataset_path),
        "cases": len(cases),
        "jurisdiction_accuracy": jurisdiction_hits / count,
        "document_recall_at_5": sum(retrieval_recalls) / max(len(retrieval_recalls), 1),
        "document_mrr_at_5": sum(reciprocal_ranks) / max(len(reciprocal_ranks), 1),
        "evidence_recall_at_5": sum(evidence_recalls) / max(len(evidence_recalls), 1),
        "evidence_gold_cases": len(evidence_recalls),
        "request_errors": request_errors,
        "request_success_rate": (count - request_errors) / count,
        "status_accuracy": status_hits / count if end_to_end else None,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "rows": rows,
    }


async def execute(dataset_path: Path, end_to_end: bool) -> dict:
    try:
        return await run(dataset_path, end_to_end)
    finally:
        if get_services.cache_info().currsize:
            await get_services().aclose()
            get_services.cache_clear()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("evals/datasets/smoke.json"))
    parser.add_argument("--end-to-end", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(execute(args.dataset, args.end_to_end))
    output = Path("evals/reports") / f"eval-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, ensure_ascii=False, indent=2))
    print(f"Report: {output}")


if __name__ == "__main__":
    main()
