"""VLM (Vision-Language Model) client sub-package.

Provides an abstraction layer over visual PDF parsing backends:
  - MockVLMClient: returns pre-annotated fixtures (dev without GPU)
  - ColPaliClient: real HTTP client to ColPali microservice
  - VLMClientFactory: env-driven selection
"""
from template_engine.vlm.client import VLMClient, VLMClientFactory
from template_engine.vlm.schemas import VLMPageResult, VLMRegion, VLMEntity

__all__ = [
    "VLMClient",
    "VLMClientFactory",
    "VLMPageResult",
    "VLMRegion",
    "VLMEntity",
]
