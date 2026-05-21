"""FastAPI dependency providers."""

from storage.object_store import ObjectStore, build_default_store, StorageConfigError


def get_object_store() -> ObjectStore:
    return build_default_store()
