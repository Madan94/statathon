from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, ForeignKey, JSON,
)
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String)
    datasets = relationship("Dataset", back_populates="owner")


class Dataset(Base):
    __tablename__ = "datasets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
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
    reports = relationship("Report", back_populates="analysis", cascade="all, delete-orphan")
    semantic_profiles = relationship("SemanticProfile", back_populates="analysis", cascade="all, delete-orphan")
    semantic_clusters_rel = relationship("SemanticCluster", back_populates="analysis", cascade="all, delete-orphan")
    schema_graph_edges_rel = relationship("SchemaGraphEdge", back_populates="analysis", cascade="all, delete-orphan")
    priority_dependencies_rel = relationship("PriorityDependency", back_populates="analysis", cascade="all, delete-orphan")
    dataset_contexts_rel = relationship("DatasetContextRecord", back_populates="analysis", cascade="all, delete-orphan")


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
