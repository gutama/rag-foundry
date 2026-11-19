"""IngestionPipeline processing files, storage, DB records, and indexing."""

import hashlib
import uuid
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from rag_foundry.db.models import Document
from rag_foundry.ingestion.indexer import IndexerService, IndexingResult
from rag_foundry.parsing.models import CanonicalDocument
from rag_foundry.parsing.router import ParserRouter, ParsingDiagnostics
from rag_foundry.storage.provider import ObjectStorageProvider


class IngestionJobStatus(str, Enum):
    """Status enumeration for document ingestion background jobs."""

    PENDING = "pending"
    PROCESSING = "processing"
    PARSED = "parsed"
    INDEXED = "indexed"
    FAILED = "failed"


class IngestionResult(BaseModel):
    """Result container for an ingestion pipeline processing run."""

    document_id: uuid.UUID = Field(description="Document record UUID")
    status: IngestionJobStatus = Field(description="Final ingestion status")
    storage_key: str = Field(description="Key in object storage")
    canonical_document: Optional[CanonicalDocument] = Field(
        default=None, description="Parsed canonical document"
    )
    diagnostics: Optional[ParsingDiagnostics] = Field(
        default=None, description="Parsing diagnostic metadata"
    )
    indexing_result: Optional[IndexingResult] = Field(
        default=None,
        description="Chunk indexing summary when ingest_and_index is used",
    )
    error_message: Optional[str] = Field(
        default=None, description="Error message if failed"
    )


class IngestionPipeline:
    """Pipeline coordinating storage, DB records, parsing, and indexing."""

    def __init__(
        self,
        storage_provider: ObjectStorageProvider,
        session: AsyncSession,
        parser_router: Optional[ParserRouter] = None,
        indexer: Optional[IndexerService] = None,
    ) -> None:
        """Initialize IngestionPipeline.

        Args:
            storage_provider: ObjectStorageProvider implementation.
            session: SQLAlchemy AsyncSession.
            parser_router: Optional ParserRouter instance.
            indexer: Optional IndexerService for chunking and DB indexing.
        """
        self.storage_provider = storage_provider
        self.session = session
        self.parser_router = parser_router or ParserRouter()
        self.indexer = indexer

    async def process_file(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        workspace_id: uuid.UUID,
        semantic_profile_id: uuid.UUID,
    ) -> IngestionResult:
        """Process raw file through storage, DB creation, and parsing.

        Args:
            file_bytes: Source file bytes.
            filename: Original filename.
            mime_type: MIME content type.
            workspace_id: Workspace UUID.
            semantic_profile_id: SemanticProfile UUID.

        Returns:
            IngestionResult container.
        """
        doc_id = uuid.uuid4()
        checksum = hashlib.sha256(file_bytes).hexdigest()
        storage_key = f"sources/ingestion/{doc_id}_{filename}"

        # 1. Put raw artifact into object storage
        meta = await self.storage_provider.put_object(
            key=storage_key, data=file_bytes, content_type=mime_type
        )

        try:
            # 2. Parse document via ParserRouter
            res = await self.parser_router.parse_document(
                file_bytes=file_bytes, filename=filename, mime_type=mime_type
            )
            canonical_doc, diagnostics = res

            # 3. Create Document ORM record
            doc_record = Document(
                id=doc_id,
                document_id=doc_id,
                workspace_id=workspace_id,
                title=filename,
                mime_type=mime_type,
                checksum=checksum,
                page_count=canonical_doc.page_count,
                parser_name=canonical_doc.parser_name,
                parser_version=canonical_doc.parser_version,
                semantic_profile_id=semantic_profile_id,
            )
            self.session.add(doc_record)
            await self.session.flush()
            await self.session.commit()

            return IngestionResult(
                document_id=doc_id,
                status=IngestionJobStatus.PARSED,
                storage_key=meta.key,
                canonical_document=canonical_doc,
                diagnostics=diagnostics,
            )
        except Exception as e:
            return IngestionResult(
                document_id=doc_id,
                status=IngestionJobStatus.FAILED,
                storage_key=meta.key,
                error_message=str(e),
            )

    async def ingest_and_index(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        workspace_id: uuid.UUID,
        semantic_profile_id: uuid.UUID,
        *,
        security_domain: str = "general",
        metadata: Optional[Dict[str, Any]] = None,
        indexer: Optional[IndexerService] = None,
    ) -> IngestionResult:
        """Process a raw file and index its structural chunks into the DB.

        Args:
            file_bytes: Source file bytes.
            filename: Original filename.
            mime_type: MIME content type.
            workspace_id: Owning workspace UUID.
            semantic_profile_id: SemanticProfile UUID.
            security_domain: Security domain tag applied to indexed chunks.
            metadata: Optional governed metadata dictionary attached to chunks.
            indexer: Optional per-call IndexerService override.

        Returns:
            IngestionResult with ``status=INDEXED`` and ``indexing_result`` on
            success, or ``status=FAILED`` on parse/index failure.

        Raises:
            ValueError: If no IndexerService is configured or supplied.
        """
        active_indexer = indexer or self.indexer
        if active_indexer is None:
            raise ValueError(
                "IndexerService must be configured on IngestionPipeline or "
                "passed to ingest_and_index."
            )

        parsed = await self.process_file(
            file_bytes=file_bytes,
            filename=filename,
            mime_type=mime_type,
            workspace_id=workspace_id,
            semantic_profile_id=semantic_profile_id,
        )
        if (
            parsed.status == IngestionJobStatus.FAILED
            or parsed.canonical_document is None
        ):
            return parsed

        try:
            idx_result = await active_indexer.index_document(
                canonical_doc=parsed.canonical_document,
                document_version_id=parsed.document_id,
                workspace_id=workspace_id,
                semantic_profile_id=semantic_profile_id,
                security_domain=security_domain,
                metadata=metadata,
            )
            return parsed.model_copy(
                update={
                    "status": IngestionJobStatus.INDEXED,
                    "indexing_result": idx_result,
                }
            )
        except Exception as exc:
            return parsed.model_copy(
                update={
                    "status": IngestionJobStatus.FAILED,
                    "error_message": str(exc),
                }
            )
