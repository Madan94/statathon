"""ColPali VLM Client — HTTP client to the ColPali vision microservice.

The microservice accepts PDF files and returns structured page results
with semantic regions, entities, tables, and charts.

Docker deployment:
  docker run -p 8001:8001 --gpus all bharatstat/colpali-service:latest

Env:
  COLPALI_ENDPOINT=http://localhost:8001
  COLPALI_TIMEOUT=120
  COLPALI_MAX_RETRIES=3   (default: 3, for transient 5xx/timeout errors)
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from template_engine.vlm.client import VLMClient, VLMExtractionError
from template_engine.vlm.schemas import VLMPageResult

logger = logging.getLogger(__name__)

# HTTP status codes that warrant a retry
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ColPaliClient(VLMClient):
    """Real HTTP client to the ColPali vision-spatial microservice."""

    def __init__(self, endpoint: str = "http://localhost:8001",
                 timeout: int | None = None,
                 max_retries: int | None = None):
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout or int(os.getenv("COLPALI_TIMEOUT", "120"))
        self._max_retries = max_retries if max_retries is not None else int(
            os.getenv("COLPALI_MAX_RETRIES", "3")
        )

    @property
    def backend_name(self) -> str:
        return "colpali"

    def health_check(self) -> bool:
        try:
            import requests
            r = requests.get(f"{self._endpoint}/health", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def extract_pages(self, pdf_path: Path) -> list[VLMPageResult]:
        """Send PDF to ColPali service and parse structured response."""
        pdf_path = Path(pdf_path)  # Ensure Path object
        try:
            import requests
        except ImportError:
            raise VLMExtractionError(
                "requests library required for ColPali client. "
                "Install: pip install requests"
            )

        if not pdf_path.exists():
            raise VLMExtractionError(f"PDF not found: {pdf_path}")

        url = f"{self._endpoint}/extract"
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                with open(pdf_path, "rb") as f:
                    response = requests.post(
                        url,
                        files={"file": (pdf_path.name, f, "application/pdf")},
                        timeout=self._timeout,
                    )

                if response.status_code in _RETRYABLE_STATUS and attempt < self._max_retries:
                    wait = 2 ** attempt  # exponential backoff: 2, 4, 8 …
                    logger.warning(
                        "ColPali returned %d (attempt %d/%d), retrying in %ds",
                        response.status_code, attempt, self._max_retries, wait,
                    )
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                break

            except requests.ConnectionError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "ColPali connection error (attempt %d/%d), retrying in %ds: %s",
                        attempt, self._max_retries, wait, exc,
                    )
                    time.sleep(wait)
                    continue
                raise VLMExtractionError(
                    f"ColPali service unreachable at {self._endpoint} after {attempt} attempt(s). "
                    f"Ensure the Docker container is running."
                )
            except requests.Timeout as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    logger.warning(
                        "ColPali timed out (attempt %d/%d, timeout=%ds)",
                        attempt, self._max_retries, self._timeout,
                    )
                    continue
                raise VLMExtractionError(
                    f"ColPali extraction timed out after {self._timeout}s "
                    f"({self._max_retries} attempts) for {pdf_path.name}"
                )
            except requests.HTTPError as exc:
                raise VLMExtractionError(
                    f"ColPali returned HTTP {exc.response.status_code}: "
                    f"{exc.response.text[:500]}"
                )
        else:
            # All retries exhausted (loop completed without break)
            raise VLMExtractionError(
                f"ColPali extraction failed after {self._max_retries} attempts: {last_exc}"
            )

        data = response.json()
        pages_raw = data.get("pages") or []

        if not pages_raw:
            raise VLMExtractionError(
                f"ColPali returned empty pages for {pdf_path.name}",
                partial_results=[],
            )

        pages: list[VLMPageResult] = []
        parse_errors = 0
        for i, page_data in enumerate(pages_raw):
            try:
                page = VLMPageResult.from_dict(page_data)
                # Sanity-check: pageIndex must be valid
                if page.pageIndex < 0:
                    page.pageIndex = i
                pages.append(page)
            except Exception as exc:
                parse_errors += 1
                logger.warning("Failed to parse ColPali page %d: %s", i, exc)
                continue

        if not pages:
            raise VLMExtractionError(
                f"All {len(pages_raw)} pages failed to parse from ColPali response",
                partial_results=[],
            )

        if parse_errors:
            logger.warning(
                "ColPali: %d/%d pages parsed successfully (%d errors)",
                len(pages), len(pages_raw), parse_errors,
            )

        logger.info(
            "ColPali extracted %d pages from %s (avg confidence: %.2f)",
            len(pages), pdf_path.name,
            sum(p.confidence for p in pages) / len(pages),
        )
        return pages

