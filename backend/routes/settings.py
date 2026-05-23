from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict
from datetime import datetime, timezone
from pathlib import Path
import httpx

from ..database import get_db
from ..models import Setting

SKILL_PATH = Path.home() / ".claude" / "skills" / "analyze-accounts.md"

router = APIRouter(prefix="/api/settings", tags=["settings"])

SENSITIVE_KEYS = {
    "youtube_api_key", "claude_api_key", "apify_api_key",
    "ai_provider_groq_key", "ai_provider_openrouter_key",
    "ai_provider_gemini_key", "linkedin_li_at",
}


class SettingItem(BaseModel):
    key: str
    value: str


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    rows = db.query(Setting).all()
    result = {}
    for row in rows:
        if row.key in SENSITIVE_KEYS and row.value:
            result[row.key] = "●●●●●●●●●●●●"
        else:
            result[row.key] = row.value
    return result


@router.post("")
def save_settings(data: Dict[str, str], db: Session = Depends(get_db)):
    for key, value in data.items():
        if value == "●●●●●●●●●●●●":
            continue
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = value
            row.updated_at = datetime.now(timezone.utc)
        else:
            db.add(Setting(key=key, value=value))
    db.commit()
    return {"ok": True}


@router.get("/value/{key}")
def get_raw_value(key: str, db: Session = Depends(get_db)):
    row = db.query(Setting).filter(Setting.key == key).first()
    return {"value": row.value if row else None}


@router.get("/test/apify")
async def test_apify(db: Session = Depends(get_db)):
    row = db.query(Setting).filter(Setting.key == "apify_api_key").first()
    if not row or not row.value:
        return {"ok": False, "error": "No Apify API key saved"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.apify.com/v2/users/me",
                headers={"Authorization": f"Bearer {row.value}"}
            )
        if r.status_code == 200:
            data = r.json().get("data", {})
            return {"ok": True, "username": data.get("username", "unknown")}
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── AI Provider endpoints ────────────────────────────────────────────────────

class TestAIProviderIn(BaseModel):
    provider: str
    api_key: Optional[str] = None
    model: Optional[str] = None


@router.post("/test-ai-provider")
async def test_ai_provider(data: TestAIProviderIn, db: Session = Depends(get_db)):
    from ..ai.providers import get_provider, TokenMissingError, TokenInvalidError, RateLimitError, ClaudeCLINotFoundError

    # If no api_key passed, try to load from DB
    api_key = data.api_key
    if not api_key and data.provider != "claude_cli":
        key_setting = f"ai_provider_{data.provider}_key"
        row = db.query(Setting).filter(Setting.key == key_setting).first()
        api_key = row.value if row else None

    try:
        provider = get_provider(data.provider, api_key)
        from ..ai.providers import PROVIDER_CONFIG
        model = data.model or PROVIDER_CONFIG.get(data.provider, {}).get("default_model", "")
        result = provider.complete([{"role": "user", "content": "Say 'ok' only."}], model)
        return {"ok": True, "response": result[:50]}
    except TokenMissingError:
        return {"ok": False, "error": "token_missing"}
    except TokenInvalidError:
        return {"ok": False, "error": "token_invalid"}
    except RateLimitError:
        return {"ok": False, "error": "rate_limit"}
    except ClaudeCLINotFoundError:
        return {"ok": False, "error": "cli_not_found"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.get("/ai-providers")
def get_ai_providers(db: Session = Depends(get_db)):
    """Return provider config + whether each token is saved."""
    from ..ai.providers import PROVIDER_CONFIG
    result = {}
    for name, cfg in PROVIDER_CONFIG.items():
        has_key = False
        if name != "claude_cli":
            key_setting = f"ai_provider_{name}_key"
            row = db.query(Setting).filter(Setting.key == key_setting).first()
            has_key = bool(row and row.value)
        result[name] = {**cfg, "has_key": has_key}
    return result


# ─── Skill file endpoints ─────────────────────────────────────────────────────

class SkillUpdate(BaseModel):
    content: str


@router.get("/skill/analyze-accounts")
def get_skill():
    exists = SKILL_PATH.exists()
    content = SKILL_PATH.read_text(encoding="utf-8") if exists else ""
    return {"content": content, "path": str(SKILL_PATH), "exists": exists}


@router.post("/skill/analyze-accounts")
def save_skill(data: SkillUpdate):
    SKILL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SKILL_PATH.write_text(data.content, encoding="utf-8")
    return {"ok": True, "path": str(SKILL_PATH)}
