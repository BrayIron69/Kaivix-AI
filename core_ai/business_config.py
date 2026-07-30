"""
BusinessConfig: the single customization boundary of Kaivix Core.

Loads and validates the 8 per-business YAML files under
config/businesses/<business_id>/ into a composed, read-only BusinessConfig.

Scaffolding only — nothing in this module is wired into ConversationEngine,
PromptBuilder, or QualificationEngine yet. See docs/Business_Config.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, EmailStr, Field, ValidationError

CONFIG_ROOT = Path(__file__).resolve().parent.parent / "config" / "businesses"
DEFAULT_BUSINESS_ID = "kaivix"

# filename -> (BusinessConfig field name, model class)
_OPTIONAL_FILES: dict[str, tuple[str, type[BaseModel]]] = {}


class BusinessConfigError(Exception):
    """Raised when a business config file is missing (and required) or malformed."""


class ContactInfo(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None


class BusinessIdentity(BaseModel):
    business_id: str
    business_name: str
    industry: str
    description: str
    contact: ContactInfo = Field(default_factory=ContactInfo)
    timezone: str
    locale: str


class ResponseStyle(BaseModel):
    max_sentences: Optional[int] = None


class BusinessPersona(BaseModel):
    ai_name: str
    role: str
    tone: str
    formality: str
    signature_phrases: list[str] = Field(default_factory=list)
    booking_link: Optional[str] = None
    identity_statement: str
    objectives: list[str] = Field(default_factory=list)
    response_style: ResponseStyle = Field(default_factory=ResponseStyle)


class QualificationField(BaseModel):
    id: str
    prompt_hint: str
    required: bool = True


class QualificationSchema(BaseModel):
    fields: list[QualificationField] = Field(default_factory=list)


class KnowledgeConfig(BaseModel):
    """
    Where a business's knowledge lives -- but not what reads it.

    There is deliberately no `source_type` here. It used to exist alongside
    `providers.knowledge_provider` (providers.yaml), with both claiming to
    select the knowledge backend and nothing stating which won. Decision #022
    flagged that ambiguity as the reason knowledge was left out of the
    provider registry; Decision #025 resolves it in favour of
    `providers.knowledge_provider`, so that all four backend choices are
    declared in one file, under one naming convention.

    A stale `source_type:` key left in a knowledge.yaml is inert -- pydantic
    ignores unknown keys -- so removing it here cannot break an existing
    config.
    """

    namespace: str


class ToolsConfig(BaseModel):
    enabled_tools: list[str] = Field(default_factory=list)


class ChannelsConfig(BaseModel):
    enabled_channels: list[str] = Field(default_factory=lambda: ["web_chat"])


class GuardrailsConfig(BaseModel):
    disclaimers: list[str] = Field(default_factory=list)
    forbidden_topics: list[str] = Field(default_factory=list)
    escalation_triggers: list[str] = Field(default_factory=list)


class ProvidersConfig(BaseModel):
    llm_provider: str = "groq"
    crm_provider: str = "sqlite"
    calendar_provider: str = "none"
    knowledge_provider: str = "file"


class BusinessConfig(BaseModel):
    identity: BusinessIdentity
    persona: BusinessPersona
    qualification: QualificationSchema
    knowledge: KnowledgeConfig
    tools: ToolsConfig
    channels: ChannelsConfig
    guardrails: GuardrailsConfig
    providers: ProvidersConfig


_OPTIONAL_FILES.update(
    {
        "qualification.yaml": ("qualification", QualificationSchema),
        "knowledge.yaml": ("knowledge", KnowledgeConfig),
        "tools.yaml": ("tools", ToolsConfig),
        "channels.yaml": ("channels", ChannelsConfig),
        "guardrails.yaml": ("guardrails", GuardrailsConfig),
        "providers.yaml": ("providers", ProvidersConfig),
    }
)


def _read_yaml(path: Path) -> dict:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BusinessConfigError(f"{path}: could not read file ({exc})") from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise BusinessConfigError(f"{path}: malformed YAML ({exc})") from exc

    if data is None:
        data = {}

    if not isinstance(data, dict):
        raise BusinessConfigError(
            f"{path}: expected a YAML mapping at the top level, got {type(data).__name__}"
        )

    return data


def _validate(model_cls: type[BaseModel], data: dict, path: Path) -> BaseModel:
    try:
        return model_cls(**data)
    except ValidationError as exc:
        field_errors = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        )
        raise BusinessConfigError(f"{path}: {field_errors}") from exc


class BusinessConfigRepository:
    """
    Loads a business_id's 8 config files, validates each into its sub-model,
    and returns an assembled, cached BusinessConfig.

    Missing optional files/fields fall back to Kaivix's own values, read
    from Kaivix's own config directory (not duplicated as Python constants).
    identity.yaml and persona.yaml are required per business and never fall
    back to Kaivix's own values.
    """

    def __init__(
        self,
        config_root: Path = CONFIG_ROOT,
        default_business_id: str = DEFAULT_BUSINESS_ID,
    ):
        self._config_root = config_root
        self._default_business_id = default_business_id
        self._cache: dict[str, BusinessConfig] = {}
        self._default_sections: Optional[dict[str, BaseModel]] = None

    def load(self, business_id: str) -> BusinessConfig:
        if business_id in self._cache:
            return self._cache[business_id]

        business_dir = self._config_root / business_id
        identity = self._load_identity(business_dir, business_id)
        persona = self._load_persona(business_dir, business_id)

        defaults = self._get_default_sections()

        kwargs: dict[str, BaseModel] = {"identity": identity, "persona": persona}
        for filename, (field_name, model_cls) in _OPTIONAL_FILES.items():
            path = business_dir / filename
            if path.is_file():
                data = _read_yaml(path)
                kwargs[field_name] = _validate(model_cls, data, path)
            else:
                kwargs[field_name] = defaults[field_name].model_copy(deep=True)

        config = BusinessConfig(**kwargs)
        self._cache[business_id] = config
        return config

    def _load_identity(self, business_dir: Path, business_id: str) -> BusinessIdentity:
        path = business_dir / "identity.yaml"
        if not path.is_file():
            raise BusinessConfigError(
                f"{path}: identity.yaml is required and was not found for "
                f"business_id={business_id!r}"
            )
        data = _read_yaml(path)
        return _validate(BusinessIdentity, data, path)

    def _load_persona(self, business_dir: Path, business_id: str) -> BusinessPersona:
        path = business_dir / "persona.yaml"
        if not path.is_file():
            raise BusinessConfigError(
                f"{path}: persona.yaml is required and was not found for "
                f"business_id={business_id!r}"
            )
        data = _read_yaml(path)
        return _validate(BusinessPersona, data, path)

    def _get_default_sections(self) -> dict[str, BaseModel]:
        """
        The Kaivix defaults: each optional section as found in Kaivix's own
        config directory, falling back to that model's own bare defaults if
        Kaivix itself doesn't define a given file. Computed once and cached.
        """
        if self._default_sections is not None:
            return self._default_sections

        default_dir = self._config_root / self._default_business_id
        sections: dict[str, BaseModel] = {}
        for filename, (field_name, model_cls) in _OPTIONAL_FILES.items():
            path = default_dir / filename
            if path.is_file():
                data = _read_yaml(path)
                sections[field_name] = _validate(model_cls, data, path)
            else:
                try:
                    sections[field_name] = model_cls()
                except ValidationError as exc:
                    field_errors = "; ".join(
                        f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
                        for err in exc.errors()
                    )
                    raise BusinessConfigError(
                        f"{path}: Kaivix's own reference config does not "
                        f"define this file, and {model_cls.__name__} has no "
                        f"usable bare default ({field_errors}) — the "
                        f"default-sections fallback cannot supply a value "
                        f"for this section"
                    ) from exc

        self._default_sections = sections
        return sections
