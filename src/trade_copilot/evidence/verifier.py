from __future__ import annotations

from datetime import UTC, datetime

from trade_copilot.config import Settings
from trade_copilot.domain.models import (
    AnswerStatus,
    CandidateEvidence,
    ContextPackage,
    EvidenceDecision,
    EvidenceLevel,
    SourceTier,
)


class EvidenceVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def verify(self, context: ContextPackage, evidence: list[CandidateEvidence]) -> EvidenceDecision:
        reasons: list[str] = []
        blocking_flags = {
            "prompt_injection_or_unsafe_instruction",
            "unsupported_future_prediction",
            "unverifiable_entity_specific_event",
        }
        detected = blocking_flags.intersection(context.risk_flags)
        if detected:
            return EvidenceDecision(
                status=AnswerStatus.ABSTAINED,
                level=EvidenceLevel.INSUFFICIENT,
                reasons=[f"请求包含不可由当前知识库可靠验证的风险类型：{', '.join(sorted(detected))}"],
            )
        eligible = [
            item
            for item in evidence
            if item.rerank_score is not None and item.rerank_score >= self.settings.min_rerank_score
        ]
        if not eligible:
            return EvidenceDecision(
                status=AnswerStatus.ABSTAINED,
                level=EvidenceLevel.INSUFFICIENT,
                reasons=["没有达到校准阈值的相关证据"],
            )

        today = datetime.now(UTC).date()
        expired = [item for item in eligible if item.chunk.expires_date and item.chunk.expires_date < today]
        if expired:
            reasons.append("部分材料已标记失效，未将其作为确定结论依据")
            eligible = [item for item in eligible if item not in expired]
        if not eligible:
            return EvidenceDecision(
                status=AnswerStatus.ABSTAINED,
                level=EvidenceLevel.INSUFFICIENT,
                reasons=reasons + ["可用证据均已失效"],
            )

        found_jurisdictions = {item.chunk.jurisdiction for item in eligible}
        missing = set(context.jurisdictions) - found_jurisdictions
        if missing:
            reasons.append("部分目标法域没有可靠证据")
            return EvidenceDecision(
                status=AnswerStatus.PARTIAL,
                level=EvidenceLevel.LIMITED,
                reasons=reasons,
                evidence=eligible[: context.evidence_budget],
            )

        authoritative = any(
            item.chunk.source_tier in {SourceTier.OFFICIAL_LAW, SourceTier.GOVERNMENT, SourceTier.OFFICIAL_GUIDE}
            for item in eligible
        )
        if not authoritative:
            reasons.append("未检索到官方或政府来源")
            return EvidenceDecision(
                status=AnswerStatus.PARTIAL,
                level=EvidenceLevel.LIMITED,
                reasons=reasons,
                evidence=eligible[: context.evidence_budget],
            )

        return EvidenceDecision(
            status=AnswerStatus.ANSWERED,
            level=EvidenceLevel.SUFFICIENT,
            reasons=["法域匹配且存在达到阈值的官方/政府证据"],
            evidence=eligible[: context.evidence_budget],
        )
