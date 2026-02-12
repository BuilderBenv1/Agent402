"""
Sync ERC-8004 agents from Base mainnet into Agent402's Supabase.

Uses the Agent0 SDK's subgraph (The Graph) to query all registered agents
on Base, parses their metadata, and upserts into Agent402's database
with chain='base'.

Also supports Ethereum mainnet and Polygon via their respective subgraphs.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python scripts/sync_from_base_8004.py [chain] [start_from]

    chain:      base (default), ethereum, polygon
    start_from: agent_id to resume from (default: 0)

Subgraph URLs from Agent0 SDK (github.com/agent0lab/agent0-ts).
"""

import os
import sys
import json
import base64
import time
import logging
from datetime import datetime, timezone

import requests
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sync_8004")

# ─── Config ───────────────────────────────────────────────────────────

# Agent0 SDK subgraph URLs (from contracts.ts)
SUBGRAPH_URLS = {
    "base": "https://gateway.thegraph.com/api/536c6d8572876cabea4a4ad0fa49aa57/subgraphs/id/43s9hQRurMGjuYnC1r2ZwS6xSQktbFyXMPMqGKUFJojb",
    "ethereum": "https://gateway.thegraph.com/api/7fd2e7d89ce3ef24cd0d4590298f0b2c/subgraphs/id/FV6RR6y13rsnCxBAicKuQEwDp8ioEGiNaWaZUmvr1F8k",
    "polygon": "https://gateway.thegraph.com/api/782d61ed390e625b8867995389699b4c/subgraphs/id/9q16PZv1JudvtnCAf44cBoxg82yK9SSsFvrjCY9xnneF",
}

PAGE_SIZE = 1000  # subgraph max per query
DB_BATCH = 100  # agents per Supabase write


# ─── Helpers ──────────────────────────────────────────────────────────


def get_db() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        logger.error("SUPABASE_URL and SUPABASE_KEY required")
        sys.exit(1)
    return create_client(url, key)


def parse_metadata_uri(uri: str) -> dict:
    """Parse base64 data URI or fetch HTTP/IPFS metadata."""
    if not uri:
        return {}
    if uri.startswith("data:application/json;base64,"):
        b64 = uri.split(",", 1)[1]
        try:
            return json.loads(base64.b64decode(b64 + "=="))
        except Exception:
            return {}
    if uri.startswith("http"):
        try:
            r = requests.get(uri, timeout=5)
            if r.ok:
                return r.json()
        except Exception:
            pass
    if uri.startswith("ipfs://"):
        cid = uri.replace("ipfs://", "")
        for gw in ["https://gateway.pinata.cloud/ipfs/", "https://ipfs.io/ipfs/"]:
            try:
                r = requests.get(f"{gw}{cid}", timeout=5)
                if r.ok:
                    return r.json()
            except Exception:
                continue
    return {}


def infer_category(metadata: dict) -> str:
    """Infer agent category from metadata."""
    text = (
        (metadata.get("description", "") + " " + metadata.get("name", ""))
        .lower()
    )
    tags = [t.lower() for t in metadata.get("tags", [])]
    for svc in metadata.get("services", []):
        if svc.get("name") == "OASF":
            for d in svc.get("domains", []):
                tags.append(d.lower())
            for s in svc.get("skills", []):
                tags.append(s.lower())
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


def query_subgraph(subgraph_url: str, chain: str, start_from: int = 0) -> list[dict]:
    """Query all agents from subgraph, paginated."""
    all_agents = []
    last_id = str(start_from)

    while True:
        query = """
        {
          agents(
            first: %d,
            where: { agentId_gt: "%s" },
            orderBy: agentId,
            orderDirection: asc
          ) {
            agentId
            owner
            agentURI
            createdAt
            updatedAt
          }
        }
        """ % (PAGE_SIZE, last_id)

        for attempt in range(3):
            try:
                r = requests.post(subgraph_url, json={"query": query}, timeout=30)
                r.raise_for_status()
                data = r.json()
                break
            except Exception as e:
                if attempt < 2:
                    logger.warning(f"  Subgraph query retry ({attempt+2}): {e}")
                    time.sleep(2)
                else:
                    logger.error(f"  Subgraph query failed after 3 attempts: {e}")
                    return all_agents

        agents = data.get("data", {}).get("agents", [])
        if not agents:
            break

        all_agents.extend(agents)
        last_id = agents[-1]["agentId"]

        if len(agents) < PAGE_SIZE:
            break

        logger.info(f"  Fetched {len(all_agents)} agents from subgraph (last ID: {last_id})...")

    return all_agents


def transform_agent(raw: dict, chain: str) -> dict:
    """Transform subgraph agent data into Agent402 record."""
    agent_id = int(raw["agentId"])
    uri = raw.get("agentURI", "")
    metadata = parse_metadata_uri(uri)

    name = metadata.get("name")
    description = metadata.get("description", "")
    category = infer_category(metadata)
    image_url = metadata.get("image")

    endpoints = []
    for svc in metadata.get("services", []):
        if svc.get("name") in ("web", "api", "a2a"):
            endpoints.append(svc.get("endpoint", ""))

    # Convert unix timestamp to ISO
    created_ts = int(raw.get("createdAt", 0))
    if created_ts > 0:
        registered_at = datetime.fromtimestamp(created_ts, tz=timezone.utc).isoformat()
    else:
        registered_at = datetime.now(timezone.utc).isoformat()

    updated_ts = int(raw.get("updatedAt", 0))
    if updated_ts > 0:
        updated_at = datetime.fromtimestamp(updated_ts, tz=timezone.utc).isoformat()
    else:
        updated_at = registered_at

    return {
        "agent_id": agent_id,
        "chain": chain,
        "owner_address": raw.get("owner", "").lower(),
        "agent_uri": uri or f"erc8004:{chain}:{agent_id}",
        "name": name,
        "description": description[:500] if description else None,
        "category": category,
        "image_url": image_url,
        "endpoints": endpoints,
        "registered_at": registered_at,
        "updated_at": updated_at,
        "total_feedback": 0,
        "average_rating": 0,
        "composite_score": 0,
        "validation_success_rate": 0,
        "tier": "unranked",
    }


def write_batch(db: Client, records: list[dict]) -> tuple[int, int]:
    """Write a batch of records to Supabase. Returns (success, errors)."""
    success = 0
    errors = 0
    for rec in records:
        for attempt in range(3):
            try:
                db.table("agents").upsert(
                    rec, on_conflict="agent_id,chain"
                ).execute()
                success += 1
                break
            except Exception as e:
                if attempt == 2:
                    try:
                        db.table("agents").insert(rec).execute()
                        success += 1
                    except Exception:
                        errors += 1
                else:
                    time.sleep(0.5)
    return success, errors


# ─── Main ─────────────────────────────────────────────────────────────


def main():
    chain = sys.argv[1] if len(sys.argv) > 1 else "base"
    start_from = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    if chain not in SUBGRAPH_URLS:
        logger.error(f"Unsupported chain: {chain}. Use: {', '.join(SUBGRAPH_URLS.keys())}")
        sys.exit(1)

    subgraph_url = SUBGRAPH_URLS[chain]

    logger.info("=" * 60)
    logger.info(f"Agent402 — ERC-8004 Indexer ({chain})")
    logger.info(f"Subgraph: Agent0 SDK (The Graph)")
    logger.info(f"Start from agent_id: {start_from}")
    logger.info("=" * 60)

    # Query subgraph
    logger.info("Querying subgraph for all agents...")
    raw_agents = query_subgraph(subgraph_url, chain, start_from)
    logger.info(f"Found {len(raw_agents)} agents in subgraph")

    if not raw_agents:
        logger.info("No agents to sync")
        return

    # Transform
    logger.info("Parsing metadata...")
    records = []
    category_counts: dict[str, int] = {}
    parse_errors = 0

    for i, raw in enumerate(raw_agents):
        try:
            rec = transform_agent(raw, chain)
            cat = rec["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1
            records.append(rec)
        except Exception as e:
            parse_errors += 1
            if parse_errors <= 5:
                logger.warning(f"  Parse error for agent {raw.get('agentId')}: {e}")

        if (i + 1) % 1000 == 0:
            logger.info(f"  Parsed {i + 1}/{len(raw_agents)} agents...")

    logger.info(f"Parsed {len(records)} agents ({parse_errors} errors)")

    # Write to Supabase
    db = get_db()

    existing = (
        db.table("agents")
        .select("agent_id", count="exact")
        .eq("chain", chain)
        .limit(0)
        .execute()
    )
    logger.info(f"Existing {chain} agents in DB: {existing.count or 0}")

    total_synced = 0
    total_errors = 0

    logger.info(f"Writing {len(records)} agents to Supabase...")
    for i in range(0, len(records), DB_BATCH):
        batch = records[i : i + DB_BATCH]
        s, e = write_batch(db, batch)
        total_synced += s
        total_errors += e

        if (i + DB_BATCH) % 500 == 0 or i + DB_BATCH >= len(records):
            logger.info(
                f"  Progress: {total_synced}/{len(records)} synced, "
                f"{total_errors} errors"
            )

        # Refresh connection on errors
        if total_errors > 50:
            logger.warning("  Refreshing DB connection...")
            db = get_db()
            total_errors = 0

    logger.info("=" * 60)
    logger.info(f"ERC-8004 indexing complete ({chain}):")
    logger.info(f"  Total in subgraph: {len(raw_agents)}")
    logger.info(f"  Synced:   {total_synced}")
    logger.info(f"  Errors:   {total_errors}")
    logger.info(f"  Categories: {category_counts}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
