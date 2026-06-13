"""VLM Client — abstract interface and factory for vision-language model backends.

The factory reads environment to select the active backend:
  - VLM_BACKEND=mock     → MockVLMClient (pre-annotated fixtures, no GPU)
  - VLM_BACKEND=colpali  → ColPaliClient (HTTP to COLPALI_ENDPOINT)
  - VLM_BACKEND=fallback → PdfPlumberVLMAdapter (existing pdfplumber as fallback)

When switching from local Docker to cloud, only the env vars change.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from template_engine.vlm.schemas import VLMPageResult

logger = logging.getLogger(__name__)


class VLMClient(ABC):
    """Abstract base for all VLM backends."""

    @abstractmethod
    def extract_pages(self, pdf_path: Path) -> list[VLMPageResult]:
        """Extract structured page results from a PDF file.

        Args:
            pdf_path: Path to the PDF file on disk.

        Returns:
            List of VLMPageResult, one per page.

        Raises:
            VLMExtractionError: If extraction fails completely.
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the backend is available and healthy."""
        ...

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Human-readable backend identifier."""
        ...


class VLMExtractionError(Exception):
    """Raised when VLM extraction fails."""

    def __init__(self, message: str, page_index: int | None = None,
                 partial_results: list[VLMPageResult] | None = None):
        super().__init__(message)
        self.page_index = page_index
        self.partial_results = partial_results or []


class VLMClientFactory:
    """Factory for VLM clients — selects backend based on environment.

    Usage:
        client = VLMClientFactory.create()
        pages = client.extract_pages(pdf_path)
    """

    @staticmethod
    def create(backend: str | None = None) -> VLMClient:
        """Create VLM client based on backend name or VLM_BACKEND env var.

        Cascade: explicit arg → env var → auto-detect (colpali if endpoint set, else mock)
        """
        backend = backend or os.getenv("VLM_BACKEND", "").lower()

        if not backend:
            # Auto-detect: if ColPali endpoint is configured, use it
            if os.getenv("COLPALI_ENDPOINT"):
                backend = "colpali"
            else:
                backend = "mock"

        if backend == "mock":
            from template_engine.vlm.mock_client import MockVLMClient
            return MockVLMClient()

        if backend == "colpali":
            from template_engine.vlm.colpali_client import ColPaliClient
            endpoint = os.getenv("COLPALI_ENDPOINT", "http://localhost:8100")
            return ColPaliClient(endpoint=endpoint)

        if backend == "fallback":
            from template_engine.vlm.pdfplumber_adapter import PdfPlumberVLMAdapter
            return PdfPlumberVLMAdapter()

        raise ValueError(f"Unknown VLM backend: {backend!r}. "
                         f"Valid: mock, colpali, fallback")

    @staticmethod
    def available_backends() -> list[str]:
        """List backends that are currently available."""
        available = ["mock"]  # always available

        if os.getenv("COLPALI_ENDPOINT"):
            available.append("colpali")

        try:
            import pdfplumber  # noqa: F401
            available.append("fallback")
        except ImportError:
            pass

        return available
