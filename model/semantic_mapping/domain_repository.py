import json


class DomainRepository:

    def __init__(self, config_path="config/domain_definitions.json"):
        self.config_path = config_path
        self.domains = {}
        self.load_domains()

    def load_domains(self):
        with open(self.config_path, "r") as f:
            data = json.load(f)
        self.domains = data.get("domains", {})

    def get_domains(self):
        return self.domains

    def get_domain_names(self):
        return list(self.domains.keys())

    def get_domain_description(self, domain_name):
        domain = self.domains.get(domain_name, {})
        if isinstance(domain, dict):
            return domain.get("description", "")
        return str(domain)

    def get_domain_keywords(self, domain_name):
        domain = self.domains.get(domain_name, {})
        if isinstance(domain, dict):
            return domain.get("keywords", [])
        return []

    def get_domain_descriptions(self):
        descriptions = {}
        for name in self.domains:
            descriptions[name] = self.get_domain_description(name)
        return descriptions

    def register_domain(self, domain_name, description, keywords=None):
        self.domains[domain_name] = {
            "description": description,
            "keywords": keywords or []
        }

    def save(self):
        with open(self.config_path, "w") as f:
            json.dump({"domains": self.domains}, f, indent=2)