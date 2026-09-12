from __future__ import annotations

import re
from collections import defaultdict

from rank_bm25 import BM25Okapi

from trade_copilot.config import Settings
from trade_copilot.domain.models import CandidateEvidence, ContextPackage
from trade_copilot.providers import SiliconFlowClient
from trade_copilot.storage import Repository


def tokenize(text: str) -> list[str]:
    # Character bigrams make the tiny local lexical index useful for Chinese while preserving
    # normal word tokens for Portuguese names, acronyms and legal terms.
    lowered = text.casefold()
    words = re.findall(r"[a-zà-ÿ0-9_-]+", lowered)
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
    words.extend(chinese[i : i + 2] for i in range(max(0, len(chinese) - 1)))
    return words or [lowered]


class HybridRetriever:
    def __init__(self, settings: Settings, repository: Repository, provider: SiliconFlowClient) -> None:
        self.settings = settings
        self.repository = repository
        self.provider = provider

    async def retrieve(self, context: ContextPackage) -> list[CandidateEvidence]:
        all_candidates: dict[str, CandidateEvidence] = {}
        ranks: dict[str, float] = defaultdict(float)

        scopes = [[item] for item in context.jurisdictions] or [[]]
        for query in context.retrieval_queries:
            vector = (await self.provider.embed([query]))[0]
            for scope in scopes:
                dense = self.repository.dense_search(
                    vector,
                    scope,
                    self.settings.dense_top_k,
                    topics=context.topics,
                )
                for item in dense:
                    item.matched_query = query
                    all_candidates.setdefault(item.chunk.chunk_id, item)
                    ranks[item.chunk.chunk_id] += 1 / (60 + (item.dense_rank or 1000))

                chunks = self.repository.all_chunks(scope, topics=context.topics)
                if chunks:
                    bm25 = BM25Okapi([tokenize(chunk.text) for chunk in chunks])
                    scores = bm25.get_scores(tokenize(query))
                    ordered = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
                    for lexical_rank, index in enumerate(ordered, start=1):
                        if scores[index] <= 0 or lexical_rank > self.settings.lexical_top_k:
                            break
                        chunk = chunks[index]
                        candidate = all_candidates.setdefault(
                            chunk.chunk_id,
                            CandidateEvidence(chunk=chunk, matched_query=query),
                        )
                        candidate.lexical_rank = min(
                            candidate.lexical_rank or lexical_rank, lexical_rank
                        )
                        ranks[chunk.chunk_id] += 1 / (60 + lexical_rank)

        fused = sorted(all_candidates.values(), key=lambda item: ranks[item.chunk.chunk_id], reverse=True)
        for item in fused:
            item.fused_score = ranks[item.chunk.chunk_id]
        pool = fused[: max(self.settings.dense_top_k, self.settings.lexical_top_k)]
        reranked = await self.provider.rerank(
            context.normalized_query,
            [item.chunk.text for item in pool],
            self.settings.rerank_top_k,
        )
        ordered_output = []
        for index, score in reranked:
            item = pool[index]
            item.rerank_score = score
            ordered_output.append(item)
        if len(context.jurisdictions) < 2:
            return ordered_output

        # A global top-k can be monopolized by one jurisdiction. Reserve the best passage
        # for every requested jurisdiction, then fill the remaining evidence budget by score.
        output = []
        selected_ids = set()
        for jurisdiction in context.jurisdictions:
            best = next(
                (item for item in ordered_output if item.chunk.jurisdiction == jurisdiction),
                None,
            )
            if best:
                output.append(best)
                selected_ids.add(best.chunk.chunk_id)
        output.extend(
            item
            for item in ordered_output
            if item.chunk.chunk_id not in selected_ids
        )
        return output
