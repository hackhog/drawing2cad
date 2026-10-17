"""Explicit, portable configuration. Relative paths use the TOML directory."""

from pathlib import Path
import tomllib

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PdfSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed_roots: list[Path] = Field(min_length=1)
    output_root: Path
    pdftoppm: str | None = None
    timeout_seconds: float = Field(default=60, gt=0, le=600, allow_inf_nan=False)
    max_pdf_bytes: int = Field(default=104857600, gt=0, strict=True)
    max_pixels: int = Field(default=40000000, gt=0, strict=True)


class FreeCADSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: Path | None = None
    timeout_seconds: float = Field(default=120, gt=0, le=7200, allow_inf_nan=False)
    startup_timeout_seconds: float = Field(default=10, gt=0, le=120, allow_inf_nan=False)

    @model_validator(mode="after")
    def require_command(self):
        if self.enabled and not (self.command and self.command.strip()):
            raise ValueError("freecad.command is required when freecad.enabled=true")
        return self


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_max_pixels: int = Field(default=4000000, gt=0, le=16000000, strict=True)
    preview_max_bytes: int = Field(default=6000000, gt=0, le=12000000, strict=True)
    pdf_concurrency: int = Field(default=2, ge=1, le=4, strict=True)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pdf: PdfSettings
    freecad: FreeCADSettings = Field(default_factory=lambda: FreeCADSettings(enabled=False))
    server: ServerSettings = Field(default_factory=ServerSettings)

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
        if settings.freecad.cwd is not None:
            settings.freecad.cwd = resolve(settings.freecad.cwd)
        for section, field in ((settings.pdf, "pdftoppm"), (settings.freecad, "command")):
            value = getattr(section, field)
            if value and ("/" in value or "\\" in value):
                setattr(section, field, str(resolve(Path(value))))
        return settings
