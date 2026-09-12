from __future__ import annotations

import hashlib
import json

from trade_copilot.config import Settings
from trade_copilot.domain.models import Chunk, DocumentManifest, IngestResult
from trade_copilot.providers import SiliconFlowClient
from trade_copilot.storage import Repository

from .chunker import split_pages
from .loader import load_document


class IngestionPipeline:
    def __init__(self, settings: Settings, repository: Repository, provider: SiliconFlowClient) -> None:
        self.settings = settings
        self.repository = repository
        self.provider = provider

    def load_manifests(self) -> list[DocumentManifest]:
        manifests = []
        for path in sorted(self.settings.manifest_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            items = payload if isinstance(payload, list) else [payload]
            manifests.extend(DocumentManifest.model_validate(item) for item in items)
        return manifests

    async def run(self) -> IngestResult:
        result = IngestResult()
        for manifest in self.load_manifests():
            result.documents_seen += 1
            try:
                path = (self.settings.raw_data_dir / manifest.file).resolve()
                root = self.settings.raw_data_dir.resolve()
                if root not in path.parents:
                    raise ValueError("Manifest file escapes RAW_DATA_DIR")
                content = path.read_bytes()
                document_hash = hashlib.sha256(content).hexdigest()
                if self.repository.has_document_hash(manifest.document_id, document_hash):
                    result.documents_skipped += 1
                    continue
                pages = load_document(path)
                chunks = []
                for index, (page, section, text) in enumerate(split_pages(pages)):
                    chunk_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    stable_id = hashlib.sha256(
                        f"{manifest.document_id}:{document_hash}:{index}".encode()
                    ).hexdigest()[:32]
                    chunks.append(
                        Chunk(
                            chunk_id=stable_id,
                            document_id=manifest.document_id,
                            text=text,
                            page=page,
                            section=section,
                            jurisdiction=manifest.jurisdiction,
                            language=manifest.language,
                            topics=manifest.topics,
                            title=manifest.title,
                            publisher=manifest.publisher,
                            source_url=str(manifest.source_url),
                            source_tier=manifest.source_tier,
                            published_date=manifest.published_date,
                            effective_date=manifest.effective_date,
                            expires_date=manifest.expires_date,
                            content_hash=chunk_hash,
                        )
                    )
                if not chunks:
                    raise ValueError("Document produced no text chunks (OCR may be required)")
                vectors = await self.provider.embed([chunk.text for chunk in chunks])
                self.repository.replace_document(manifest.document_id, chunks, vectors)
                result.documents_indexed += 1
                result.chunks_indexed += len(chunks)
            except Exception as exc:  # noqa: BLE001 - isolate per-document ingestion failures
                result.errors.append(f"{manifest.document_id}: {type(exc).__name__}: {exc}")
        return result
