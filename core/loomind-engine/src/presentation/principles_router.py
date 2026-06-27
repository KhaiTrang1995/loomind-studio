"""
Principles Router — POST /api/principles/share and POST /api/principles/import

Export and import T0 principles across projects with optional HMAC-SHA256 signing.
Requirements: 9.1–9.6
"""

from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import APIRouter, HTTPException, Query, Request

from src.domain.evolution.tiers import TIER_COLLECTION, KnowledgeTier
from src.domain.models import EdgeType, Experience, SharedPrincipleBundle

router = APIRouter(prefix="/api/principles", tags=["principles"])


@router.post("/share")
async def share_principle(req: Request, body: dict) -> dict:
    """Export a T0 principle as a SharedPrincipleBundle."""
    principle_id = body.get("principle_id", "")
    if not principle_id:
        raise HTTPException(status_code=400, detail="principle_id required")

    qdrant = req.app.state.service.qdrant
    t0_col = TIER_COLLECTION[KnowledgeTier.T0_PRINCIPLE]

    # Find the principle in T0
    payload = qdrant.get_experience(t0_col, principle_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Principle not found or not a T0-tier entry")

    # Check it's actually T0
    if payload.get("tier") != KnowledgeTier.T0_PRINCIPLE.value:
        raise HTTPException(status_code=404, detail="Entry is not a T0 principle")

    # Get member summaries (up to 50)
    member_ids = payload.get("member_ids", [])
    member_summaries = []
    for mid in member_ids[:50]:
        for tier in (KnowledgeTier.T1_BEHAVIORAL, KnowledgeTier.T2_QA_CACHE):
            m_payload = qdrant.get_experience(TIER_COLLECTION[tier], mid)
            if m_payload:
                member_summaries.append({"id": mid, "title": m_payload.get("title", "")})
                break

    # Sign if key available
    from src.config import settings
    signature = None
    if settings.principle_signing_key:
        bundle_data = json.dumps({"principle": payload, "members": member_summaries}, sort_keys=True)
        signature = hmac.new(
            settings.principle_signing_key.encode(),
            bundle_data.encode(),
            hashlib.sha256,
        ).hexdigest()

    bundle = SharedPrincipleBundle(
        principle=payload,
        member_summaries=member_summaries,
        signature=signature,
    )
    return {"bundle": bundle.model_dump()}


@router.post("/import", status_code=201)
async def import_principle(req: Request, body: dict, trusted: bool = Query(default=False)) -> dict:
    """Import a principle bundle with optional signature verification."""
    bundle_data = body.get("bundle")
    if not bundle_data:
        raise HTTPException(status_code=400, detail="bundle required")

    try:
        bundle = SharedPrincipleBundle(**bundle_data)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid bundle format")

    from src.config import settings

    # Signature verification
    if bundle.signature:
        if not settings.principle_signing_key:
            raise HTTPException(status_code=403, detail="Server cannot verify signatures (no signing key configured)")
        verify_data = json.dumps({"principle": bundle.principle, "members": bundle.member_summaries}, sort_keys=True)
        expected_sig = hmac.new(
            settings.principle_signing_key.encode(),
            verify_data.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(bundle.signature, expected_sig):
            raise HTTPException(status_code=403, detail="Signature verification failed")
    else:
        # Unsigned bundle
        if not trusted:
            raise HTTPException(status_code=403, detail="Unsigned bundles require ?trusted=true flag")

    # Store as T0
    qdrant = req.app.state.service.qdrant
    embedder = req.app.state.service.embedder
    t0_col = TIER_COLLECTION[KnowledgeTier.T0_PRINCIPLE]

    try:
        exp = Experience(**bundle.principle)
        exp = exp.model_copy(update={"tier": KnowledgeTier.T0_PRINCIPLE})
        text = f"{exp.title} {exp.description}"
        vector = embedder.embed(text)
        qdrant.upsert_experience(t0_col, exp, vector)
        return {"id": exp.id, "imported": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to import: {e}")
