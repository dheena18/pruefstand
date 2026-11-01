"""Identifier types shared across modules (interfaces §2). All IDs are plain strings at runtime."""

from typing import NewType

CaseId = NewType("CaseId", str)
TenantId = NewType("TenantId", str)
DocId = NewType("DocId", str)
ChunkId = NewType("ChunkId", str)
RunId = NewType("RunId", str)
