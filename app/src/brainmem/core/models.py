"""领域模型（Pydantic v2，不可变）。字段严格对齐《记忆语义规范》第 2 节。"""
from pydantic import BaseModel, ConfigDict, Field

from brainmem.core.enums import (
    EdgeRelation,
    EdgeState,
    EventType,
    NodeKind,
    SourceKind,
    State,
)


class MemoryNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str = "default"
    label: str = Field(min_length=1, max_length=100)
    label_norm: str
    char_len: int = Field(ge=1, le=100)
    kind: NodeKind = NodeKind.ATOM
    weight_bp: int = Field(ge=0)
    stability: int = Field(default=0, ge=0, le=24)
    peak_bp: int = Field(ge=0)
    state: State
    fidelity: int = Field(default=100, ge=0, le=100)
    gist: str | None = None
    verbatim_ref: str | None = None
    fingerprint: str
    salience: int = Field(default=50, ge=0, le=100)
    born_at: float
    last_touch_at: float
    source_kind: SourceKind = SourceKind.HUMAN
    source_id: str | None = None
    deleted_at: float | None = None


class MemoryEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str = "default"
    src_id: str
    dst_id: str
    relation: EdgeRelation = EdgeRelation.ASSOCIATED
    weight_bp: int = Field(ge=0)
    coactivation: int = Field(default=0, ge=0)
    state: EdgeState = EdgeState.ACTIVE
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    provenance: str | None = None
    created_at: float
    last_touch_at: float


class WeightEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int = 0
    tenant_id: str = "default"
    entity_kind: str  # NODE / EDGE
    entity_id: str
    event_type: EventType
    delta_bp: int
    before_bp: int
    after_bp: int
    reason: str
    actor: str
    at_day: float
    at_real: int
    trace_id: str | None = None


class MemoryVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    node_id: str
    version_no: int
    gist: str | None = None
    verbatim_ref: str | None = None
    diff: str | None = None
    created_at: float
    created_by: str
    reason: str | None = None


class ConsolidationRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    run_type: str
    started_at: int
    finished_at: int | None = None
    sampled: int = 0
    changed: int = 0
    params: str | None = None
    report: str | None = None


class SchemaRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    template: str
    created_at: float
