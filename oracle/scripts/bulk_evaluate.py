"""
Bulk evaluation cycle for Agent402.

Iterates all agents, parses metadata URIs, extracts names/protocol flags,
recomputes composite scores, and updates the agents table.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python scripts/bulk_evaluate.py
"""

import os
import sys
import math
import json
import base64
import logging
from datetime import datetime, timezone, date
from collections import Counter

from supabase import create_client, Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bulk_eval")

PAGE = 1000
BATCH = 500


def get_db() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        logger.error("SUPABASE_URL and SUPABASE_KEY required")
        sys.exit(1)
    return create_client(url, key)


def parse_metadata(agent_uri: str) -> dict:
    """Parse agent metadata from base64 data URI or return empty dict."""
    if not agent_uri:
        return {}
    if agent_uri.startswith("data:application/json;base64,"):
        b64 = agent_uri.split(",", 1)[1]
        try:
            return json.loads(base64.b64decode(b64 + "=="))
        except Exception:
            return {}
    return {}


def infer_category(metadata: dict, description: str = "") -> str:
    """Infer agent category from metadata and description."""
    text = (
        (metadata.get("description", "") + " " + (description or ""))
        .lower()
    )
    tags = [t.lower() for t in metadata.get("tags", [])]
    all_text = text + " " + " ".join(tags)

    if any(w in all_text for w in ["defi", "swap", "yield", "trading", "liquidity", "amm", "lending"]):
        return "defi"
    if any(w in all_text for w in ["game", "gaming", "npc", "nft game", "play"]):
        return "gaming"
    if any(w in all_text for w in ["rwa", "real world", "tokeniz", "property", "real-world"]):
        return "rwa"
    if any(w in all_text for w in ["payment", "settle", "remit", "invoice", "pay"]):
        return "payments"
    if any(w in all_text for w in ["data", "analyt", "index", "oracle", "pipeline", "scrape"]):
        return "data"
    return "general"


def calculate_composite_score(
    average_rating: float,
    feedback_count: int,
    rating_std_dev: float,
    validation_success_rate: float,
    account_age_days: int,
    uptime_pct: float = -1.0,
) -> float:
    """Same algorithm as services/trust.py."""
    prior_rating = 50.0
    k = 3
    smoothed = (average_rating * feedback_count + prior_rating * k) / (feedback_count + k)
    rating_score = smoothed

    if feedback_count == 0:
        volume_score = 0.0
    else:
        volume_score = min(100.0, (math.log10(feedback_count + 1) / math.log10(101)) * 100)

    if feedback_count < 2:
        consistency_score = 50.0
    else:
        consistency_score = max(0.0, 100.0 * (1 - rating_std_dev / 50.0))

    validation_score = validation_success_rate

    if account_age_days <= 0:
        age_score = 0.0
    else:
        age_score = min(100.0, (math.log10(account_age_days + 1) / math.log10(366)) * 100)

    uptime_score = 50.0 if uptime_pct < 0 else uptime_pct

    composite = (
        rating_score * 0.35
        + volume_score * 0.12
        + consistency_score * 0.13
        + validation_score * 0.18
        + age_score * 0.07
        + uptime_score * 0.15
    )
    return round(max(0.0, min(100.0, composite)), 2)


def determine_tier(score: float, feedback: int) -> str:
    if score >= 90 and feedback >= 50:
        return "diamond"
    if score >= 80 and feedback >= 30:
        return "platinum"
    if score >= 70 and feedback >= 20:
        return "gold"
    if score >= 60 and feedback >= 10:
        return "silver"
    if score >= 50 and feedback >= 5:
        return "bronze"
    return "unranked"


def main():
    logger.info("=" * 60)
    logger.info("Agent402 Bulk Evaluation Cycle")
    logger.info("=" * 60)

    db = get_db()

    # Pre-fetch all feedback data
    logger.info("Loading reputation events...")
    feedback_map: dict[int, list[int]] = {}
    offset = 0
    while True:
        batch = (
            db.table("reputation_events")
            .select("agent_id, rating")
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        if not batch.data:
            break
        for r in batch.data:
            aid = r["agent_id"]
            feedback_map.setdefault(aid, []).append(r["rating"])
        if len(batch.data) < PAGE:
            break
        offset += PAGE
    logger.info(f"Loaded feedback for {len(feedback_map)} agents")

    # Pre-fetch validation data
    logger.info("Loading validation records...")
    validation_map: dict[int, tuple[int, int]] = {}  # agent_id -> (completed, successful)
    offset = 0
    while True:
        batch = (
            db.table("validation_records")
            .select("agent_id, is_valid")
            .not_.is_("is_valid", "null")
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        if not batch.data:
            break
        for r in batch.data:
            aid = r["agent_id"]
            completed, successful = validation_map.get(aid, (0, 0))
            validation_map[aid] = (completed + 1, successful + (1 if r["is_valid"] else 0))
        if len(batch.data) < PAGE:
            break
        offset += PAGE
    logger.info(f"Loaded validations for {len(validation_map)} agents")

    # Process agents in pages
    now = datetime.now(timezone.utc)
    today = date.today().isoformat()
    total_processed = 0
    updates = []
    tier_counts: dict[str, int] = {}
    protocol_counts = Counter()
    category_counts = Counter()

    offset = 0
    while True:
        batch = (
            db.table("agents")
            .select("agent_id, owner_address, agent_uri, name, description, category, registered_at, total_feedback, average_rating, composite_score, tier")
            .order("agent_id")
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        if not batch.data:
            break

        for agent in batch.data:
            aid = agent["agent_id"]
            metadata = parse_metadata(agent.get("agent_uri", ""))

            # Extract name from metadata if not set
            name = agent.get("name") or metadata.get("name") or None

            # Infer category
            category = infer_category(metadata, agent.get("description", ""))

            # Protocol flags
            if metadata.get("x402Support") or metadata.get("x402support"):
                protocol_counts["x402"] += 1
            if metadata.get("8004Support"):
                protocol_counts["8004"] += 1
            if metadata.get("active"):
                protocol_counts["active"] += 1
            # All agents are on ERC-8004 registry
            protocol_counts["https"] += 1

            # Compute score
            ratings = feedback_map.get(aid, [])
            feedback_count = len(ratings)
            avg_rating = sum(ratings) / len(ratings) if ratings else 0
            std_dev = 0.0
            if len(ratings) >= 2:
                mean = sum(ratings) / len(ratings)
                variance = sum((r - mean) ** 2 for r in ratings) / len(ratings)
                std_dev = math.sqrt(variance)

            completed, successful = validation_map.get(aid, (0, 0))
            success_rate = (successful / completed * 100) if completed > 0 else 0

            reg_str = agent.get("registered_at", "")
            if reg_str:
                try:
                    reg_dt = datetime.fromisoformat(reg_str.replace("Z", "+00:00"))
                    if reg_dt.tzinfo is None:
                        reg_dt = reg_dt.replace(tzinfo=timezone.utc)
                    age_days = max(0, (now - reg_dt).days)
                except Exception:
                    age_days = 0
            else:
                age_days = 0

            composite = calculate_composite_score(
                average_rating=avg_rating,
                feedback_count=feedback_count,
                rating_std_dev=std_dev,
                validation_success_rate=success_rate,
                account_age_days=age_days,
            )
            tier = determine_tier(composite, feedback_count)

            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            category_counts[category] += 1

            update_data = {
                "name": name,
                "category": category,
                "composite_score": composite,
                "tier": tier,
                "total_feedback": feedback_count,
                "average_rating": round(avg_rating, 2),
                "validation_success_rate": round(success_rate, 2),
                "updated_at": now.isoformat(),
            }
            db.table("agents").update(update_data).eq("agent_id", aid).execute()
            total_processed += 1

            if total_processed % 500 == 0:
                logger.info(f"  Updated {total_processed} agents...")

        if len(batch.data) < PAGE:
            break
        offset += PAGE

    logger.info("=" * 60)
    logger.info(f"Bulk evaluation complete: {total_processed} agents scored")
    logger.info(f"Tier distribution: {dict(tier_counts)}")
    logger.info(f"Category distribution: {dict(category_counts)}")
    logger.info(f"Protocol flags: {dict(protocol_counts)}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
