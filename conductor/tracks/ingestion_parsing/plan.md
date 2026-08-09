# Implementation Plan: Source Ingestion, Parser Router, and Canonical Document Processing

## Phase 1: Object Storage Interface & Connectors
- [x] Task: Implement Object Storage Provider and Ingestion Connectors (1f51958)
  - [x] Write failing unit tests for `ObjectStorageProvider` (Local & MinIO/S3 backends)
  - [x] Write failing unit tests for File Upload API (`/api/v1/sources/upload`) and `FilesystemConnector`
  - [x] Implement `ObjectStorageProvider` interface and local/S3 adapters
  - [x] Implement File Upload endpoint and `FilesystemConnector`
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase 2: Parser Architecture & Multi-Format Adapters (PDF & Office Docs)
- [x] Task: Implement Parser Adapter Architecture, Native PDF, and Office Document Parsers (b9d6ba7)
  - [x] Write failing unit tests for `ParserProvider` interface and canonical `CanonicalDocument` / `DocumentElement` output
  - [x] Write failing unit tests for `NativePDFParserAdapter` (PDF) and `DoclingParserAdapter` (PDF, DOCX, XLSX, PPTX)
  - [x] Implement `NativePDFParserAdapter` (fast text, page numbers, bounding box extraction)
  - [x] Implement `DoclingParserAdapter` for PDF & Office formats (DOCX tables/headings, XLSX sheets/grids, PPTX slides)
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase 3: OCR Fallback Router & Parsing Diagnostics (ADR-0008)
- [x] Task: Implement Intelligent Parser Router and OCR Fallback (6d8e61c)
  - [x] Write failing unit tests for `ParserRouter` text quality scoring (density < 50 chars/page)
  - [x] Write failing unit tests for `PaddleOCRProviderAdapter` and automatic fallback routing
  - [x] Implement `ParserRouter` score evaluator and `PaddleOCRProviderAdapter`
  - [x] Implement `ParsingDiagnostics` recorder on document versions
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase 4: Asynchronous Ingestion Worker & Pipeline Integration (ADR-0001)
- [x] Task: Implement Async Ingestion Pipeline and Job Tracking (7ce938a)
  - [x] Write failing integration tests for end-to-end `IngestionPipeline` and DB job status state machine (`pending`, `processing`, `parsed`, `failed`)
  - [x] Implement `IngestionPipeline` service and async job worker task
  - [x] Verify test suite passes with ≥80% coverage across ingestion & parsing packages
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md)
