"""The CIMD fallback for the OAuth provider (`_auth()` in stackshot/web/auth/oauth.py): a client that identifies itself by a URL client id
(claude.ai) is looked up by fetching that URL, and a failed fetch must not turn into a lost connector grant.
Kept apart from server.py so a test can import it without the server's import-time setup."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from fastmcp.server.auth.cimd import CIMDDocument, CIMDFetchError, CIMDValidationError

_RETRY_DELAYS = (1.5, 3.0)   # seconds between the three attempts


def _disk_path(store: Path, url: str) -> Path:
    return store / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".json")


def _harden_cimd(fetcher, store: Path, log: logging.Logger = logging.getLogger("stackshot.cimd")) -> None:
    """claude.ai serves its client metadata document with max-age=300, so token refreshes re-fetch it often; a failed
    fetch would make get_client() return None and reject a known client, so the last good copy is kept."""
    original = fetcher.fetch

    async def fetch(client_id_url: str):
        last: Exception | None = None
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                doc = await original(client_id_url)
            except (CIMDFetchError, CIMDValidationError) as e:
                last = e
                if attempt < len(_RETRY_DELAYS):
                    await asyncio.sleep(_RETRY_DELAYS[attempt])
                continue
            try:
                store.mkdir(parents=True, exist_ok=True)
                _disk_path(store, client_id_url).write_text(doc.model_dump_json(), encoding="utf-8")
            except Exception as e:  # noqa: BLE001  — the copy on disk is a fallback, never a reason to fail the fetch
                log.warning("CIMD document for %s not kept on disk: %s", client_id_url, e)
            return doc
        cached = fetcher._cache.get(client_id_url)
        if cached is not None:
            log.warning("CIMD fetch failed for %s (%s): serving the cached document", client_id_url, last)
            return cached.doc
        disk = _disk_path(store, client_id_url)
        if disk.exists():
            try:
                doc = CIMDDocument.model_validate_json(disk.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001  — an unreadable copy is no fallback: report the fetch error
                log.warning("CIMD document kept on disk for %s is unreadable: %s", client_id_url, e)
            else:
                log.warning("CIMD fetch failed for %s (%s): serving the document kept on disk", client_id_url, last)
                return doc
        assert last is not None
        raise last

    fetcher.fetch = fetch
