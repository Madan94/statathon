"""FastAPI dependency providers."""

from object_storage.object_store import ObjectStore, StorageConfigError, build_default_store


def get_object_store() -> ObjectStore:
    return build_default_store()
