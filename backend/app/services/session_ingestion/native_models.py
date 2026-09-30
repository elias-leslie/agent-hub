"""Version-one native observation contract; positions belong to collectors, not RPCs."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class NativeSourceRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["native-observation.v1"] = "native-observation.v1"
    provider: Literal["codex"] = "codex"
    namespace: str = Field(min_length=1, max_length=512)
    source_kind: Literal["app_server", "rollout"]
    producer_id: str = Field(min_length=1, max_length=256)
    epoch: str = Field(min_length=1, max_length=256)
    collector_id: str = Field(min_length=1, max_length=256)
    provider_version: str = Field(min_length=1, max_length=256)
    schema_fingerprint: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=512)
    transcript_path: str | None = Field(default=None, max_length=4096)


class NativeSourceReceipt(BaseModel):
    schema_version: Literal["native-observation.v1"] = "native-observation.v1"
    source_id: str
    committed_position: int
    authenticity: Literal["local_verified", "collector_attested"]


class NativeAlias(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["api_session_id", "transcript_runtime_session_id", "provider_call_id"]
    value: str = Field(min_length=1, max_length=512)


class NativeObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: int = Field(ge=1)
    thread_id: str = Field(min_length=1, max_length=512)
    turn_id: str | None = Field(default=None, max_length=512)
    item_id: str | None = Field(default=None, max_length=512)
    identity_quality: Literal["durable", "provisional", "source_local", "unknown"] = "unknown"
    origin: Literal["live", "stored_snapshot", "active_resume_snapshot", "rollout_record"]
    history_owner_thread_id: str | None = Field(default=None, max_length=512)
    aliases: list[NativeAlias] = Field(default_factory=list)
    kind: str = Field(min_length=1, max_length=256)
    payload: dict[str, Any] = Field(default_factory=dict)
    source_reference: dict[str, Any] = Field(default_factory=dict)
    requested_model: str | None = None
    requested_reasoning_effort: str | None = None
    configured_model: str | None = None


class NativeObservationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["native-observation.v1"] = "native-observation.v1"
    observations: list[NativeObservation] = Field(default_factory=list)
    acknowledged_position: int | None = Field(default=None, ge=0)


class NativeObservationDisposition(BaseModel):
    position: int
    disposition: str
    entity_id: str | None = None
    issue_code: str | None = None


class NativeObservationResult(NativeSourceReceipt):
    dispositions: list[NativeObservationDisposition] = Field(default_factory=list)
