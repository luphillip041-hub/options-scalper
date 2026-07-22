"""Discord webhook notifications. No-op if DISCORD_WEBHOOK_URL is unset."""
import logging
import os

import requests

log = logging.getLogger("opscalper.notify")
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

COLORS = {
    "call": 0x2ECC71, "put": 0xE67E22,
    "win": 0x3498DB, "loss": 0xE74C3C,
    "halt": 0x9B59B6, "info": 0x95A5A6,
}


def send(title: str, description: str = "", kind: str = "info", fields: dict | None = None):
    if not WEBHOOK_URL:
        return
    embed = {"title": title, "description": description,
             "color": COLORS.get(kind, COLORS["info"])}
    if fields:
        embed["fields"] = [{"name": k, "value": str(v), "inline": True} for k, v in fields.items()]
    try:
        requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=5)
    except Exception as e:
        log.warning("discord webhook failed: %s", e)
