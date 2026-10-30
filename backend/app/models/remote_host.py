"""Remote hosts that run agents and the per-tool credential map they launch with.

A host authenticates with its own bearer token, stored only as a SHA-256 hash.
The tool map is data: one row per credential a Tether tool uses, saying how it
reaches the tool (env var or auth file under the tool's real config dir) and
whether the login rotates. Rotating logins are signed in on the host and never
served; non-rotating values live encrypted in ``credentials`` (provider
``_host_tool_<tool>``, type ``<name>``).
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RemoteHost(Base):
    __tablename__ = "remote_hosts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Tool slugs whose served credentials this host may fetch.
    granted_tools: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RemoteToolCredential(Base):
    __tablename__ = "remote_tool_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_slug: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # Executable the host shim stands in for (Tether's argv[0] for the tool).
    command: Mapped[str] = mapped_column(String(50), nullable=False)
    # The tool's real config dir on the host, "~/"-relative; auth_file is under it.
    config_dir: Mapped[str] = mapped_column(String(200), nullable=False)
    env_var: Mapped[str | None] = mapped_column(String(100), nullable=True)
    auth_file: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rotates: Mapped[bool] = mapped_column(Boolean, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tool_slug", "name", name="uq_remote_tool_credentials_tool_name"),
        CheckConstraint(
            "(env_var IS NULL) <> (auth_file IS NULL)", name="ck_remote_tool_credentials_one_delivery",
        ),
    )
