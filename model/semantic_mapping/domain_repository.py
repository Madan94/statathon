"""
Hybrid domain repository: JSON-backed statistical domains + ephemeral runtime domains.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


class DomainRepository:
    def __init__(self, config_path: str | Path | None = None):
        base = Path(__file__).resolve().parent.parent / "config" / "domain_definitions.json"
        self.config_path = Path(config_path) if config_path else base
        self._base_domains: dict[str, Any] = {}
        self._runtime_domains: dict[str, Any] = {}
        self.load_domains()

    def load_domains(self) -> None:
        """Loads and flattens the Unified JSON for legacy downstream engines."""
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._base_domains = {}
        
        # Parse the new "dataset_types" structure
        if "dataset_types" in data:
            for arch_name, arch_data in data["dataset_types"].items():
                for sub_name, keywords in arch_data.get("subdomains", {}).items():
                    # Create a flat, deduplicated dictionary for downstream engines
                    if sub_name not in self._base_domains:
                        self._base_domains[sub_name] = {
                            "description": f"{sub_name.replace('_', ' ').title()} statistical domain.",
                            "keywords": keywords
                        }

        self._runtime_domains = {}

    def get_base_domain_names(self) -> list[str]:
        return list(self._base_domains.keys())

    def get_base_domain_descriptions(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for name, spec in self._base_domains.items():
            if isinstance(spec, dict):
                out[name] = str(spec.get("description", ""))
        return out

    def clear_runtime(self) -> None:
        self._runtime_domains = {}

    def merge_runtime(self, domains: dict[str, Any]) -> None:
        for name, spec in domains.items():
            if isinstance(spec, dict) and "description" in spec:
                self._runtime_domains[name] = {
                    "description": spec["description"],
                    "keywords": spec.get("keywords") or [],
                    "metadata": spec.get("metadata"),
                }

    def get_domains(self) -> dict[str, Any]:
        merged = deepcopy(self._base_domains)
        merged.update(self._runtime_domains)
        return merged

    def get_domain_names(self) -> list[str]:
        return list(self.get_domains().keys())

    def get_domain_description(self, domain_name: str) -> str:
        domain = self.get_domains().get(domain_name, {})
        if isinstance(domain, dict):
            return str(domain.get("description", ""))
        return str(domain)

    def get_domain_keywords(self, domain_name: str) -> list[str]:
        domain = self.get_domains().get(domain_name, {})
        if isinstance(domain, dict):
            return list(domain.get("keywords") or [])
        return []

    def get_domain_descriptions(self) -> dict[str, str]:
        return {name: self.get_domain_description(name) for name in self.get_domain_names()}

    def register_domain(self, domain_name: str, description: str, keywords: list[str] | None = None) -> None:
        self._runtime_domains[domain_name] = {
            "description": description,
            "keywords": keywords or [],
        }

    def save_base_to_disk(self) -> None:
        """
        WARNING: Disabled to protect hierarchical JSON structure.
        """
        raise NotImplementedError(
            "save_base_to_disk is disabled because it would overwrite the new hierarchical "
            "domain_definitions.json with a flat dictionary. Base domains should now be updated manually."
        )
