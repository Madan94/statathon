from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    String,
    Float,
    BigInteger,
    DateTime,
    Text,
    ForeignKey,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String, nullable=False)
    full_name = Column(String(256), nullable=True)
    officer_role = Column(String(256), nullable=True)
    email_verified_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=False, server_default="0")
    failed_login_count = Column(Integer, default=0, server_default="0")
    locked_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    datasets = relationship("Dataset", back_populates="owner")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"
    id = Column(String(36), primary_key=True)
    purpose = Column(String(32), nullable=False, index=True)
    email = Column(String(320), nullable=False, index=True)
    code_hash = Column(String(128), nullable=False)
    payload_json = Column(JSON, nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    attempts = Column(Integer, default=0, server_default="0")
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="refresh_tokens")


class Dataset(Base):
    __tablename__ = "datasets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String, nullable=False)
    # Local path after multipart upload; nullable when using object storage only.
    storage_path = Column(String, nullable=True)
    # S3-compatible key after presigned PUT flow.
    object_key = Column(String(1024), nullable=True, unique=True, index=True)
    storage_provider = Column(String(32), nullable=False, default="local", server_default="local")
    storage_url = Column(String(2048), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    checksum = Column(String(128), nullable=True)
    upload_status = Column(String(32), nullable=True, index=True)

    row_count = Column(Integer, default=0)
    column_count = Column(Integer, default=0)
    status = Column(String(32), default="pending")
    health_summary = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    owner = relationship("User", back_populates="datasets")
    columns = relationship("DatasetColumn", back_populates="dataset", cascade="all, delete-orphan")
    analyses = relationship("Analysis", back_populates="dataset", cascade="all, delete-orphan")


class DatasetColumn(Base):
    __tablename__ = "dataset_columns"
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    name = Column(String, nullable=False)
    inferred_type = Column(String(64), nullable=True)
    semantic_label = Column(String(256), nullable=True)
    priority = Column(Float, default=0.0)
    domain_tags = Column(JSON, nullable=True)
    dataset = relationship("Dataset", back_populates="columns")


class Analysis(Base):
    __tablename__ = "analyses"
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    status = Column(String(32), default="pending")
    config = Column(JSON, nullable=True)
    checkpoint = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    dataset = relationship("Dataset", back_populates="analyses")
    validation_results = relationship("ValidationResult", back_populates="analysis", cascade="all, delete-orphan")
    phase3_validation_candidates = relationship(
        "Phase3ValidationCandidate", back_populates="analysis", cascade="all, delete-orphan"
    )
    anomaly_intel = relationship(
        "Phase3AnomalyIntel", back_populates="analysis", uselist=False, cascade="all, delete-orphan"
    )

    anomaly_decisions = relationship(
        "Phase3AnomalyDecision", back_populates="analysis", cascade="all, delete-orphan"
    )


    imputation_intel = relationship(
        "Phase3ImputationIntel", back_populates="analysis", uselist=False, cascade="all, delete-orphan"
    )
    imputation_decisions = relationship(
        "Phase3ImputationDecision", back_populates="analysis", cascade="all, delete-orphan"
    )

    reports = relationship("Report", back_populates="analysis", cascade="all, delete-orphan")
    semantic_profiles = relationship("SemanticProfile", back_populates="analysis", cascade="all, delete-orphan")
    semantic_clusters_rel = relationship("SemanticCluster", back_populates="analysis", cascade="all, delete-orphan")
    schema_graph_edges_rel = relationship("SchemaGraphEdge", back_populates="analysis", cascade="all, delete-orphan")
    priority_dependencies_rel = relationship("PriorityDependency", back_populates="analysis", cascade="all, delete-orphan")
    dataset_contexts_rel = relationship("DatasetContextRecord", back_populates="analysis", cascade="all, delete-orphan")


class DatasetIntelligenceRecord(Base):
    """Dataset-level profiling rollup snapshot (relational complement to checkpoint JSON)."""

    __tablename__ = "dataset_intelligence_records"
    __table_args__ = (UniqueConstraint("analysis_id", name="uq_dataset_intel_analysis"),)

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    rollup_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ColumnIntelligenceProfile(Base):
    """Per-column profiling JSON for an analysis."""

    __tablename__ = "column_intelligence_profiles"
    __table_args__ = (
        UniqueConstraint("analysis_id", "column_name", name="uq_column_intel_analysis_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    column_name = Column(String(512), nullable=False)
    profile_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False)
    stage = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    analysis = relationship("Analysis", back_populates="validation_results")


class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False)
    report_type = Column(String(64), nullable=False)
    storage_path = Column(String, nullable=False)
    content_hash = Column(String(128), nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    analysis = relationship("Analysis", back_populates="reports")


class SemanticProfile(Base):
    __tablename__ = "semantic_profiles"
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    column_name = Column(String(512), nullable=False)
    semantic_domain = Column(String(256), nullable=True)
    confidence = Column(Float, nullable=True)
    cluster_id = Column(String(256), nullable=True)
    contextual_tags = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    analysis = relationship("Analysis", back_populates="semantic_profiles")


class SemanticCluster(Base):
    __tablename__ = "semantic_clusters"
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    cluster_name = Column(String(256), nullable=False)
    semantic_domain = Column(String(256), nullable=True)
    support_score = Column(Float, nullable=True)
    cluster_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    analysis = relationship("Analysis", back_populates="semantic_clusters_rel")


class SchemaGraphEdge(Base):
    __tablename__ = "schema_graph_edges"
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    source_column = Column(String(512), nullable=False)
    target_column = Column(String(512), nullable=False)
    edge_weight = Column(Float, nullable=False)
    relationship_type = Column(String(128), nullable=True)
    semantic_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    analysis = relationship("Analysis", back_populates="schema_graph_edges_rel")


class PriorityDependency(Base):
    __tablename__ = "priority_dependencies"
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    source_column = Column(String(512), nullable=False)
    dependent_column = Column(String(512), nullable=False)
    influence_score = Column(Float, nullable=False)
    dependency_reason = Column(Text, nullable=True)
    signal_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    analysis = relationship("Analysis", back_populates="priority_dependencies_rel")


class DatasetContextRecord(Base):
    __tablename__ = "dataset_contexts"
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    inferred_context = Column(String(128), nullable=False)
    domain_scores = Column(JSON, nullable=False)
    semantic_summary = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    analysis = relationship("Analysis", back_populates="dataset_contexts_rel")


# --- Phase 3: validation / anomalies / imputation (candidates-first; relational mirror) ---


class Phase3ValidationCandidate(Base):
    __tablename__ = "validation_candidates"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    kind = Column(String(64), nullable=False)
    column_name = Column(String(512), nullable=True)
    row_index = Column(Integer, nullable=True)
    severity = Column(String(32), nullable=True)
    candidate_action = Column(String(64), nullable=False)
    detail = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    analysis = relationship("Analysis", back_populates="phase3_validation_candidates")


class Phase3AnomalyIntel(Base):
    __tablename__ = "anomaly_results"
    __table_args__ = (UniqueConstraint("analysis_id", name="uq_phase3_anomaly_intel_analysis"),)

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    analysis = relationship("Analysis", back_populates="anomaly_intel")


class Phase3AnomalyDecision(Base):
    __tablename__ = "anomaly_decisions"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    analysis = relationship("Analysis", back_populates="anomaly_decisions")


class Phase3ImputationIntel(Base):
    __tablename__ = "imputation_results"
    __table_args__ = (UniqueConstraint("analysis_id", name="uq_phase3_imputation_intel_analysis"),)

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    analysis = relationship("Analysis", back_populates="imputation_intel")


class Phase3ImputationDecision(Base):
    __tablename__ = "imputation_decisions"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    analysis = relationship("Analysis", back_populates="imputation_decisions")


# -----------------------------------------------------------------------------
# Report Builder — full 6-phase architecture state
# -----------------------------------------------------------------------------


class ReportTemplate(Base):
    """Phase 0: Immutable blueprint extracted from a historical/government PDF.

    `source_hash` is SHA256 of the original PDF for auditability.
    `ast_json` is the hierarchical AST (SGLang-style) describing the report skeleton:
      [{"section":"executive_summary","kind":"narrative","required":true,...}, ...]
    """

    __tablename__ = "report_templates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    source_filename = Column(String(512), nullable=True)
    source_storage_path = Column(String(1024), nullable=True)
    source_hash = Column(String(128), nullable=True, index=True)
    ast_json = Column(JSON, nullable=False)
    extraction_method = Column(String(64), nullable=True)  # "pdfplumber+gemini_vision" / "manual"
    page_count = Column(Integer, nullable=True)
    filter_config = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReportJob(Base):
    """A single Report Builder run: analysis_id + template_id -> rendered blocks + PDF."""

    __tablename__ = "report_jobs"

    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("report_templates.id"), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    # 'pending' | 'running' | 'awaiting_verification' | 'verified' | 'exported' | 'failed'
    stage = Column(String(64), nullable=True)  # last phase reached (debug)
    error_message = Column(Text, nullable=True)
    blocks_json = Column(JSON, nullable=True)  # full block tree (Phase 5 AGUI snapshot)
    verifier_report = Column(JSON, nullable=True)  # Phase 4 firewall result
    kg_export_path = Column(String(1024), nullable=True)  # Phase 1 RDF/Turtle artifact
    final_pdf_path = Column(String(1024), nullable=True)  # Phase 6 PDF output
    content_hash = Column(String(128), nullable=True)
    filter_config = Column(JSON, nullable=True)
    delivery_log = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReportCorrection(Base):
    """Phase 2 LTM 'Reflection Ledger' — captures human corrections to learn from.

    Stored in Postgres now (Qdrant adapter wires later via the same schema).
    """

    __tablename__ = "report_corrections"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("report_jobs.id"), nullable=False, index=True)
    block_id = Column(String(128), nullable=False)
    correction_kind = Column(String(64), nullable=False)  # 'narrative_edit' | 'verify_fail' | 'regenerate'
    before_text = Column(Text, nullable=True)
    after_text = Column(Text, nullable=True)
    diagnostics = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReportTemplateExtractionJob(Base):
    """Async extraction lifecycle for production-grade template compilation."""

    __tablename__ = "report_template_extraction_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    stage = Column(String(64), nullable=True, index=True)
    progress_pct = Column(Integer, nullable=False, default=0)
    template_name = Column(String(256), nullable=False)
    source_filename = Column(String(512), nullable=True)
    source_storage_path = Column(String(1024), nullable=True)
    vault_object_key = Column(String(1024), nullable=True)
    source_hash = Column(String(128), nullable=True, index=True)
    extraction_method = Column(String(64), nullable=True)
    stage_diagnostics = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_template_id = Column(Integer, ForeignKey("report_templates.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
