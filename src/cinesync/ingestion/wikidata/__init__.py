"""Wikidata / Wikipedia enrichment package.

The WDQS and Wikipedia APIs both want a descriptive User-Agent with a contact.
The UA *template* lives in code (per the config convention: URLs/UAs stay in the
scripts), but the contact email is imported from the EMAIL env var so it isn't
hardcoded -- set EMAIL in .env (loaded via `uv run --env-file .env`). Missing
EMAIL just drops the contact clause; the product token still identifies us.
"""

import os

_CONTACT = os.environ.get("EMAIL", "").strip()
USER_AGENT = (
    f"CineSync/0.1 (personal recommendation project; {_CONTACT})"
    if _CONTACT
    else "CineSync/0.1 (personal recommendation project)"
)
