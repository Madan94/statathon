import os

from pydantic import BaseModel, Field, field_validator


SAFE_DOC_EXT = frozenset({".csv", ".xlsx", ".xls"})
DEFAULT_ALLOWED_CT = frozenset(
    {
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "binary/octet-stream",
    }
)


def _allowed_content_types() -> frozenset[str]:
    raw = os.getenv("DATASET_UPLOAD_ALLOWED_CONTENT_TYPES", "").strip()
    if not raw:
        return DEFAULT_ALLOWED_CT
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


class UploadUrlRequest(BaseModel):
    filename: str = Field(..., max_length=512)
    content_type: str = Field(..., max_length=255)

    @field_validator("filename")
    @classmethod
    def strip_and_basename(cls, v: str) -> str:
        name = os.path.basename(v.strip())
        if not name:
            raise ValueError("invalid filename")
        ext = os.path.splitext(name)[1].lower()
        if ext not in SAFE_DOC_EXT:
            raise ValueError(f"disallowed extension; allowed: {', '.join(sorted(SAFE_DOC_EXT))}")
        return name

    @field_validator("content_type")
    @classmethod
    def normalized_allowed_content_type(cls, v: str) -> str:
        ct = v.strip().lower().split(";")[0].strip()
        if ct not in _allowed_content_types():
            raise ValueError("content_type not allowed for uploads")
        return ct


class RegisterDatasetRequest(BaseModel):
    object_key: str = Field(..., max_length=1024)
    filename: str = Field(..., max_length=512)
    file_size: int = Field(..., gt=0, le=2**40)
    checksum: str | None = Field(None, max_length=512)

    @field_validator("filename")
    @classmethod
    def register_basename_safe(cls, v: str) -> str:
        name = os.path.basename(v.strip())
        if not name:
            raise ValueError("invalid filename")
        ext = os.path.splitext(name)[1].lower()
        if ext not in SAFE_DOC_EXT:
            raise ValueError(f"disallowed extension; allowed: {', '.join(sorted(SAFE_DOC_EXT))}")
        return name
