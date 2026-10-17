"""Explicit, portable configuration. Relative paths use the TOML directory."""

from pathlib import Path
import tomllib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PdfSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed_roots: list[Path] = Field(min_length=1)
    output_root: Path
    pdftoppm: str | None = None
    timeout_seconds: float = Field(default=60, gt=0, le=600, allow_inf_nan=False)
    max_pdf_bytes: int = Field(default=104857600, gt=0, strict=True)
    max_pixels: int = Field(default=40000000, gt=0, strict=True)


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transport: Literal["stdio", "streamable-http"] = "stdio"
    preview_max_pixels: int = Field(default=4000000, gt=0, le=16000000, strict=True)
    preview_max_bytes: int = Field(default=6000000, gt=0, le=12000000, strict=True)
    pdf_concurrency: int = Field(default=2, ge=1, le=4, strict=True)
    expose_legacy_workflow: bool = False
    max_step_bytes: int = Field(default=33554432, gt=0, le=268435456, strict=True)


class HTTPSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = Field(default="127.0.0.1", min_length=1, max_length=253, pattern=r"^[A-Za-z0-9_.:\-]+$")
    port: int = Field(default=8000, ge=1, le=65535, strict=True)
    allowed_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1:*", "localhost:*", "[::1]:*"], min_length=1)
    allowed_origins: list[str] = Field(default_factory=list)
    token_env: str = Field(default="DRAWING2CAD_HTTP_TOKEN", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


class CadSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    timeout_seconds: float = Field(default=90, gt=0, le=600, allow_inf_nan=False)
    memory_mb: int = Field(default=3072, ge=256, le=8192, strict=True)
    concurrency: int = Field(default=1, ge=1, le=4, strict=True)
    allow_build_code: bool = False
    max_tool_calls: int = Field(default=45, ge=5, le=100, strict=True)


class DomainSettings(BaseModel):
    """Configure the shared service. Adapters supply the trusted identity."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    root: Path | None = None
    principal: str = Field(default="local", min_length=1, max_length=256)
    max_source_bytes: int = Field(default=20971520, ge=1, le=20971520, strict=True)
    max_chunk_bytes: int = Field(default=524288, ge=1, le=524288, strict=True)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pdf: PdfSettings
    server: ServerSettings = Field(default_factory=ServerSettings)
    http: HTTPSettings = Field(default_factory=HTTPSettings)
    cad: CadSettings = Field(default_factory=CadSettings)
    domain: DomainSettings = Field(default_factory=DomainSettings)

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        config_path = Path(path).expanduser().resolve(strict=True)
        with config_path.open("rb") as stream:
            settings = cls.model_validate(tomllib.load(stream))
        base = config_path.parent

        def resolve(value: Path) -> Path:
            value = value.expanduser()
            return (base / value).resolve() if not value.is_absolute() else value.resolve()

        settings.pdf.allowed_roots = [resolve(p) for p in settings.pdf.allowed_roots]
        settings.pdf.output_root = resolve(settings.pdf.output_root)
        if settings.domain.root is not None:
            settings.domain.root = resolve(settings.domain.root)
        value = settings.pdf.pdftoppm
        if value and ("/" in value or "\\" in value):
            settings.pdf.pdftoppm = str(resolve(Path(value)))
        return settings
