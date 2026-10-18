"""Shared clinical-admin model selection and LM Studio authentication.

Cloudflare Access's service-token pair is operator-owned and stored only in
Render. The cloudflared connector token stays on Windows. The clinical
administrator's LM Studio bearer token is encrypted at rest with a stable
Fernet key held solely by the backend. Provider and model selection are
shared; account identity and local-model authorization remain per request.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.config import get_settings
from app.database import Base
from app.services import llm_config
from app.services.local_model_catalog import Catalog, fetch_catalog


class LocalModelUnavailable(RuntimeError):
    """The shared model configuration is incomplete or unavailable."""


OPENAI_BASE_URL = "https://api.openai.com/v1"


class UserLLMPreference(Base):
    __tablename__ = "llm_user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    chat_model: Mapped[str] = mapped_column(String(192), nullable=False)
    analysis_model: Mapped[str] = mapped_column(String(192), nullable=False)
    copilot_model: Mapped[str] = mapped_column(String(192), nullable=False, default="")
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=4096)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    lm_api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    # Legacy personal Access columns retained for rollback only; never read.
    cf_client_id_encrypted: Mapped[str | None] = mapped_column(Text)
    cf_client_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class PersonalResolvedConfig(llm_config.ResolvedConfig):
    """Hide bearer and Access credentials from dataclass repr / API responses."""

    api_key: str = field(default="", repr=False)
    access_client_id: str = field(default="", repr=False)
    access_client_secret: str = field(default="", repr=False)
    access_hostname: str = ""


def _cipher() -> Fernet:
    key = os.environ.get("LLM_USER_CREDENTIALS_KEY", "").strip()
    if not key:
        raise RuntimeError("El cifrado de credenciales no está configurado en el servidor.")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise RuntimeError("La clave de cifrado del servidor no es válida.") from exc


def _replace_lm_key(value: str | None, old_ciphertext: str | None) -> str | None:
    """None preserves, empty string revokes, nonempty value creates/rotates."""
    if value is None:
        return old_ciphertext
    if not value.strip():
        return None
    if len(value) > 8192 or "\r" in value or "\n" in value:
        raise ValueError("Formato de API key de LM Studio no válido.")
    return _cipher().encrypt(value.strip().encode("utf-8")).decode("ascii")


def _decrypt_lm_key(ciphertext: str | None) -> str:
    if not ciphertext:
        raise RuntimeError("El administrador debe configurar la API key compartida de LM Studio.")
    try:
        return _cipher().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise RuntimeError("No se pueden descifrar las credenciales de esta cuenta. Solicita su rotación.") from exc


def approved_host() -> str:
    host = get_settings().model_local_cf_access_host.strip().lower().rstrip(".")
    if not host:
        raise ValueError("El administrador debe configurar el host de Cloudflare Access en Render.")
    return host


def approved_endpoint(raw: str) -> str:
    """Only an operator-pinned HTTPS /v1 endpoint may receive either secret."""
    url = llm_config.normalise_base_url(raw)
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != approved_host()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.query or parsed.fragment
        or parsed.path.rstrip("/") != "/v1"
    ):
        raise ValueError("El endpoint HTTPS /v1 de Render no coincide con el host autorizado.")
    return url


def shared_gateway():
    """Fail closed unless operator-owned Cloudflare Access is complete."""
    settings = get_settings()
    if not settings.model_local_cf_access_required:
        raise RuntimeError("El administrador debe exigir Cloudflare Access en Render.")
    if not all((
        settings.model_local_cf_access_host.strip(),
        settings.model_local_cf_access_client_id.strip(),
        settings.model_local_cf_access_client_secret.strip(),
    )):
        raise RuntimeError("El administrador debe completar Cloudflare Access en Render.")
    return settings, approved_endpoint(settings.model_local_base_url)


def shared_ready() -> bool:
    try:
        shared_gateway()
        return True
    except (ValueError, RuntimeError):
        return False


def _catalog_for(api_key: str) -> Catalog:
    """Catalog of the operator tunnel; never uses a legacy Render bearer key."""
    try:
        settings, endpoint = shared_gateway()
    except (ValueError, RuntimeError):
        return Catalog((), False)
    if not api_key.strip():
        return Catalog((), False)
    return fetch_catalog(
        endpoint=endpoint,
        api_key=api_key,
        access_client_id=settings.model_local_cf_access_client_id,
        access_client_secret=settings.model_local_cf_access_client_secret,
        access_hostname=settings.model_local_cf_access_host,
    )


def _usable_key(ciphertext: str | None) -> str:
    try:
        return _decrypt_lm_key(ciphertext)
    except RuntimeError:
        return ""


def _catalog_payload(catalog: Catalog) -> list[dict]:
    return [{"id": model.id, "loaded": model.loaded} for model in catalog.models]


def _is_openai_destination(row: UserLLMPreference | None) -> bool:
    return bool(
        row
        and row.provider == llm_config.PROVIDER_LOCAL
        and (row.base_url or "").rstrip("/") == OPENAI_BASE_URL
    )


def _admin_owner_id(db: Session) -> uuid.UUID | None:
    """Latest shared selection row owned by an active clinical admin."""
    from app.models import User

    query = getattr(db, "query", None)
    if not callable(query):
        return None
    row = (
        db.query(UserLLMPreference)
        .join(User, User.id == UserLLMPreference.user_id)
        .filter(User.role == "admin_clinical", User.is_active == True)  # noqa: E712
        .order_by(UserLLMPreference.updated_at.desc().nullslast())
        .first()
    )
    return row.user_id if row is not None else None


def _provider_for(row: UserLLMPreference | None) -> str:
    if row is None:
        return ""
    if not (row.chat_model or "").strip() or not (row.analysis_model or "").strip() or not (row.copilot_model or "").strip():
        return ""
    if _is_openai_destination(row):
        return "openai"
    return row.provider


def _model_id(value: str, name: str) -> str:
    model_id = (value or "").strip()
    if not model_id or len(model_id) > 192 or any(ord(char) < 32 for char in model_id):
        raise ValueError(f"Indica un identificador válido para el modelo de {name}.")
    return model_id


def _selected_models(row: UserLLMPreference | None) -> tuple[str, str, str]:
    if row is None:
        raise LocalModelUnavailable("El administrador clínico todavía no ha guardado proveedor y modelos.")
    return (
        _model_id(row.chat_model, "chat"),
        _model_id(row.analysis_model, "análisis"),
        _model_id(row.copilot_model, "copiloto"),
    )


def _assert_catalog_selection(models: tuple[str, str, str], catalog: Catalog) -> None:
    if not catalog.reachable:
        return
    available = {item.id for item in catalog.models}
    if not available:
        raise ValueError("LM Studio no anuncia modelos. Carga al menos uno y actualiza el catálogo.")
    if any(model_id not in available for model_id in models):
        raise ValueError("Uno o más modelos ya no aparecen en LM Studio. Actualiza el catálogo y selecciónalos de nuevo.")


def status(db: Session, user_id: uuid.UUID) -> dict:
    from app.services.personal_resolution import personal_mode_enabled

    owner_id = _admin_owner_id(db)
    row = db.get(UserLLMPreference, owner_id) if owner_id else None
    settings = get_settings()
    selected = _provider_for(row)
    configured = selected in (llm_config.PROVIDER_LOCAL, llm_config.PROVIDER_ANTHROPIC, "openai")
    local = selected == llm_config.PROVIDER_LOCAL
    catalog = _catalog_for(_usable_key(row.lm_api_key_encrypted if row else None)) if local else Catalog((), False)
    models = (row.chat_model, row.analysis_model, row.copilot_model) if row else ("", "", "")
    key_configured = bool(row and row.lm_api_key_encrypted)
    if local:
        provider_credentials = shared_ready() and key_configured
    elif selected == llm_config.PROVIDER_ANTHROPIC:
        provider_credentials = bool(settings.anthropic_api_key)
    elif selected == "openai":
        provider_credentials = bool(settings.openai_api_key)
    else:
        provider_credentials = False
    allowed = selected != llm_config.PROVIDER_ANTHROPIC or settings.model_allow_commercial
    return {
        "configured": configured,
        "provider": selected if configured else "",
        "chat_model": models[0],
        "analysis_model": models[1],
        "copilot_model": models[2],
        "local_models": _catalog_payload(catalog),
        "local_models_reachable": catalog.reachable,
        "ready": bool(row and allowed and provider_credentials and all(value.strip() for value in models)),
        "max_tokens": row.max_tokens if row else min(settings.model_local_max_tokens, 32768),
        "timeout_seconds": row.timeout_seconds if row else settings.model_local_timeout_seconds,
        "local_available": shared_ready(),
        "lm_api_key_configured": key_configured,
        "anthropic_allowed": bool(settings.model_allow_commercial),
        "anthropic_api_key_configured": bool(settings.anthropic_api_key),
        "openai_allowed": True,
        "openai_api_key_configured": bool(settings.openai_api_key),
        "shared_inference_active": personal_mode_enabled(),
    }


def save(db: Session, user_id: uuid.UUID, payload) -> dict:
    settings = get_settings()
    if payload.provider == llm_config.PROVIDER_ANTHROPIC and not settings.model_allow_commercial:
        raise ValueError("Anthropic no está habilitado en este despliegue. Actívalo en la configuración del servidor.")
    if payload.provider not in (llm_config.PROVIDER_LOCAL, llm_config.PROVIDER_ANTHROPIC, "openai"):
        raise ValueError("Proveedor no admitido.")

    chat_model = _model_id(payload.chat_model, "chat")
    analysis_model = _model_id(payload.analysis_model, "análisis")
    copilot_model = _model_id(payload.copilot_model, "copiloto")
    owner_id = _admin_owner_id(db)
    target_id = owner_id or user_id
    row = db.get(UserLLMPreference, target_id)
    old_ciphertext = row.lm_api_key_encrypted if row else None
    lm_ciphertext = _replace_lm_key(payload.lm_api_key, old_ciphertext)

    endpoint = None
    if payload.provider == llm_config.PROVIDER_LOCAL:
        if shared_ready():
            _, endpoint = shared_gateway()
        key_for_catalog = ((payload.lm_api_key or "").strip() if payload.lm_api_key is not None
                           else _usable_key(old_ciphertext))
        _assert_catalog_selection(
            (chat_model, analysis_model, copilot_model),
            _catalog_for(key_for_catalog),
        )
    elif payload.provider == "openai":
        endpoint = OPENAI_BASE_URL

    if payload.lm_api_key and payload.lm_api_key.strip():
        _cipher()
    if row is None:
        row = UserLLMPreference(user_id=target_id, provider=payload.provider,
                                chat_model=chat_model, analysis_model=analysis_model)
    # The production check constraint stores OpenAI-compatible destinations as
    # openai_compatible; the fixed api.openai.com URL distinguishes OpenAI.
    row.provider = llm_config.PROVIDER_LOCAL if payload.provider == "openai" else payload.provider
    row.base_url = endpoint
    row.chat_model = chat_model
    row.analysis_model = analysis_model
    row.copilot_model = copilot_model
    row.max_tokens = payload.max_tokens
    row.timeout_seconds = payload.timeout_seconds
    row.lm_api_key_encrypted = lm_ciphertext
    # Obsolete per-account Access credentials are never used for inference.
    row.cf_client_id_encrypted = None
    row.cf_client_secret_encrypted = None
    row.updated_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    return status(db, user_id)


def clear_shared_selection(db: Session) -> None:
    """Write a disabled tombstone so an older admin row cannot reactivate."""
    owner_id = _admin_owner_id(db)
    row = db.get(UserLLMPreference, owner_id) if owner_id else None
    if row is None:
        return
    # Keep the database provider check constraint valid; blank explicit IDs
    # make _provider_for treat this latest row as an inactive tombstone.
    row.provider = llm_config.PROVIDER_LOCAL
    row.base_url = None
    row.chat_model = ""
    row.analysis_model = ""
    row.copilot_model = ""
    row.lm_api_key_encrypted = None
    row.cf_client_id_encrypted = None
    row.cf_client_secret_encrypted = None
    row.updated_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()


def list_local_models(db: Session, user_id: uuid.UUID, api_key: str | None = None) -> dict:
    owner_id = _admin_owner_id(db)
    row = db.get(UserLLMPreference, owner_id) if owner_id else None
    candidate = (api_key or "").strip() or _usable_key(row.lm_api_key_encrypted if row else None)
    catalog = _catalog_for(candidate)
    return {
        "models": _catalog_payload(catalog),
        "reachable": catalog.reachable,
        "detail": (
            "Catálogo de LM Studio actualizado."
            if catalog.reachable
            else "No se pudo consultar LM Studio: revisa el acceso de Cloudflare en el servidor y la API key de LM Studio."
        ),
    }


def resolve_candidate(db: Session, user_id: uuid.UUID, payload) -> PersonalResolvedConfig:
    """Build an unsaved candidate for the admin's synthetic connection test."""
    settings = get_settings()
    chat_model = _model_id(payload.chat_model, "chat")
    analysis_model = _model_id(payload.analysis_model, "análisis")
    copilot_model = _model_id(payload.copilot_model, "copiloto")
    if payload.provider == llm_config.PROVIDER_ANTHROPIC:
        if not settings.model_allow_commercial:
            raise RuntimeError("Anthropic no está habilitado en este despliegue.")
        if not settings.anthropic_api_key.strip():
            raise RuntimeError("Falta la clave API de Anthropic en los secretos del servidor.")
        return PersonalResolvedConfig(
            provider=payload.provider, chat_model=chat_model, analysis_model=analysis_model,
            copilot_model=copilot_model, copilot_model_explicit=copilot_model,
            api_key=settings.anthropic_api_key, max_tokens=payload.max_tokens,
            timeout_seconds=payload.timeout_seconds, label="Configuración compartida", source="runtime",
        )
    if payload.provider == "openai":
        if not settings.openai_api_key.strip():
            raise RuntimeError("Falta OPENAI_API_KEY en los secretos del servidor.")
        return PersonalResolvedConfig(
            provider="openai", chat_model=chat_model, analysis_model=analysis_model,
            copilot_model=copilot_model, copilot_model_explicit=copilot_model,
            api_key=settings.openai_api_key, max_tokens=payload.max_tokens,
            timeout_seconds=payload.timeout_seconds, label="Configuración compartida", source="runtime",
        )
    if payload.provider != llm_config.PROVIDER_LOCAL:
        raise RuntimeError("Proveedor no admitido.")
    gateway_settings, endpoint = shared_gateway()
    owner_id = _admin_owner_id(db)
    row = db.get(UserLLMPreference, owner_id) if owner_id else None
    api_key = (payload.lm_api_key or "").strip() or _usable_key(row.lm_api_key_encrypted if row else None)
    if not api_key:
        raise RuntimeError("Introduce la API key de LM Studio para probar el proveedor local.")
    _assert_catalog_selection((chat_model, analysis_model, copilot_model), _catalog_for(api_key))
    return PersonalResolvedConfig(
        provider=llm_config.PROVIDER_LOCAL, base_url=endpoint,
        chat_model=chat_model, analysis_model=analysis_model, copilot_model=copilot_model,
        copilot_model_explicit=copilot_model, api_key=api_key, max_tokens=payload.max_tokens,
        timeout_seconds=payload.timeout_seconds, label="Configuración compartida", source="runtime",
        access_client_id=gateway_settings.model_local_cf_access_client_id,
        access_client_secret=gateway_settings.model_local_cf_access_client_secret,
        access_hostname=approved_host(),
    )


def resolve(db: Session, user_id: uuid.UUID) -> PersonalResolvedConfig:
    row = db.get(UserLLMPreference, user_id)
    if row is None:
        raise LocalModelUnavailable("El administrador clínico todavía no ha guardado proveedor y modelos.")
    settings = get_settings()
    selected = _provider_for(row)
    if selected not in (llm_config.PROVIDER_LOCAL, llm_config.PROVIDER_ANTHROPIC, "openai"):
        raise LocalModelUnavailable("El administrador clínico todavía no ha configurado proveedor y modelos.")
    chat_model, analysis_model, copilot_model = _selected_models(row)
    if selected == llm_config.PROVIDER_ANTHROPIC:
        if not settings.model_allow_commercial:
            raise RuntimeError("Anthropic no está habilitado en este despliegue.")
        if not settings.anthropic_api_key.strip():
            raise RuntimeError("Falta la clave API de Anthropic en los secretos del servidor.")
        return PersonalResolvedConfig(
            provider=selected, chat_model=chat_model, analysis_model=analysis_model,
            copilot_model=copilot_model, copilot_model_explicit=copilot_model,
            api_key=settings.anthropic_api_key, max_tokens=row.max_tokens,
            timeout_seconds=row.timeout_seconds, label="Configuración compartida del admin clínico",
            source="runtime",
        )
    if selected == "openai":
        if not settings.openai_api_key.strip():
            raise RuntimeError("Falta OPENAI_API_KEY en los secretos del servidor.")
        return PersonalResolvedConfig(
            provider="openai", chat_model=chat_model, analysis_model=analysis_model,
            copilot_model=copilot_model, copilot_model_explicit=copilot_model,
            api_key=settings.openai_api_key, max_tokens=row.max_tokens,
            timeout_seconds=row.timeout_seconds, label="Configuración compartida del admin clínico",
            source="runtime",
        )
    if selected != llm_config.PROVIDER_LOCAL:
        raise RuntimeError("Proveedor de inferencia no admitido.")
    gateway_settings, endpoint = shared_gateway()
    api_key = _decrypt_lm_key(row.lm_api_key_encrypted)
    _assert_catalog_selection((chat_model, analysis_model, copilot_model), _catalog_for(api_key))
    return PersonalResolvedConfig(
        provider=selected, base_url=endpoint, chat_model=chat_model,
        analysis_model=analysis_model, copilot_model=copilot_model,
        copilot_model_explicit=copilot_model, api_key=api_key,
        max_tokens=row.max_tokens, timeout_seconds=row.timeout_seconds,
        label="Configuración compartida del admin clínico", source="runtime",
        access_client_id=gateway_settings.model_local_cf_access_client_id,
        access_client_secret=gateway_settings.model_local_cf_access_client_secret,
        access_hostname=approved_host(),
    )


def resolve_active(db: Session, user_id: uuid.UUID) -> PersonalResolvedConfig:
    """Resolve one clinical-admin configuration for every authenticated user."""
    owner_id = _admin_owner_id(db)
    if owner_id is None:
        raise LocalModelUnavailable("El administrador clínico todavía no ha configurado proveedor y modelos.")
    resolved = resolve(db, owner_id)
    if resolved.provider == llm_config.PROVIDER_LOCAL:
        from app.services import local_llm_access

        local_llm_access.assert_can_use_local_llm(local_llm_access.request_user(db))
    return resolved
