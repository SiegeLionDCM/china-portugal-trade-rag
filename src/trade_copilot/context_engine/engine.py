from __future__ import annotations

import re
from uuid import uuid4

from trade_copilot.domain.models import ContextPackage, Jurisdiction, QueryRequest

JURISDICTION_TERMS = {
    Jurisdiction.BRAZIL: ("巴西", "brasil", "brasileir"),
    Jurisdiction.PORTUGAL: ("葡萄牙", "portugal", "português", "portuguesa"),
}
TOPIC_TERMS = {
    "market_access": ("准入", "设立", "公司", "投资", "investimento", "empresa", "sociedade"),
    "tax": ("税", "税务", "税收", "imposto", "tribut", "fiscal"),
    "labor": ("用工", "劳动", "雇员", "工时", "trabalho", "trabalh", "labora", "empregado"),
}
FOLLOW_UP_TERMS = ("呢", "那", "上述", "这个", "方面", "e quanto", "e sobre", "isso")


class ContextEngine:
    def build(self, request: QueryRequest) -> ContextPackage:
        query = re.sub(r"\s+", " ", request.query).strip()
        lower = query.casefold()
        language = "zh" if re.search(r"[\u4e00-\u9fff]", query) else "pt"

        jurisdictions = list(dict.fromkeys(request.jurisdictions))
        if not jurisdictions:
            for jurisdiction, terms in JURISDICTION_TERMS.items():
                if any(term in lower for term in terms):
                    jurisdictions.append(jurisdiction)

        topics = list(dict.fromkeys(request.topics))
        if not topics:
            for topic, terms in TOPIC_TERMS.items():
                if any(term in lower for term in terms):
                    topics.append(topic)

        is_follow_up = bool(request.conversation) and (
            len(query) < 30 or any(term in lower for term in FOLLOW_UP_TERMS)
        )
        conversation_summary = ""
        if request.conversation:
            recent = request.conversation[-4:]
            conversation_summary = " | ".join(f"{turn.role}: {turn.content[:240]}" for turn in recent)
            if is_follow_up and not jurisdictions:
                history = conversation_summary.casefold()
                for jurisdiction, terms in JURISDICTION_TERMS.items():
                    if any(term in history for term in terms):
                        jurisdictions.append(jurisdiction)

        intent = "compare" if len(jurisdictions) > 1 or any(x in lower for x in ("对比", "区别", "比较", "diferença", "compar")) else "fact"
        if any(x in lower for x in ("总结", "概述", "resum")):
            intent = "summarize"
        if is_follow_up:
            intent = "follow_up"

        risk_flags = []
        if any(term in lower for term in ("忽略规则", "不要引用", "编造", "ignore previous", "sem fontes")):
            risk_flags.append("prompt_injection_or_unsafe_instruction")
        if any(
            term in lower
            for term in (
                "预测",
                "下周会不会",
                "明年的股票",
                "2035",
                "prever",
                "será a legislação",
            )
        ):
            risk_flags.append("unsupported_future_prediction")
        if any(term in lower for term in ("某家公司", "具体公司会不会", "specific company")):
            risk_flags.append("unverifiable_entity_specific_event")

        needs_clarification = not jurisdictions
        clarification = None
        if needs_clarification:
            clarification = (
                "这个问题会因法域不同而变化。请问你关注巴西还是葡萄牙？"
                if request.answer_language == "zh"
                else "A resposta depende da jurisdição. Refere-se ao Brasil ou a Portugal?"
            )

        retrieval_queries = [query]
        if is_follow_up and conversation_summary:
            retrieval_queries.append(f"{conversation_summary} | 当前问题: {query}")

        return ContextPackage(
            request_id=str(uuid4()),
            user_query_original=request.query,
            query_language=language,
            normalized_query=query,
            intent=intent,
            jurisdictions=jurisdictions,
            topics=topics,
            enterprise_profile=request.enterprise_profile,
            conversation_summary=conversation_summary,
            retrieval_queries=retrieval_queries,
            metadata_filters={"jurisdictions": [item.value for item in jurisdictions], "topics": topics},
            evidence_budget=3,
            answer_language=request.answer_language,
            risk_flags=risk_flags,
            needs_clarification=needs_clarification,
            clarification_question=clarification,
        )
