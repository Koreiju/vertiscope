"""What the store must not keep: url redaction and unreadable store names.

Everything else in this package is about keeping what was read. This module
is the other half — the small set of things that arrive with a page and must
not survive it, and the one place the rules for them are written down so that
the write path, the read path and ``forget`` cannot disagree about what a url
*is*.

Two separate leaks live here.

Query strings
-------------
A url's query is not one kind of thing, so neither blanket keeping nor
blanket stripping is right. Three kinds share the same syntax:

``identity``
    ``?id=123``, ``?v=dQw4w9WgXcQ``, ``?page=2``, ``?query=university+library``.
    The document *is* its query. Strip it and two different pages collapse
    into one Page node, which is a correctness bug rather than a privacy win.
    Search terms are in this class deliberately: a results page is its search,
    and a reader who asked for a searchable record of what they read asked
    for that.

``tracking``
    ``?utm_source=...``, ``?gclid=...``, ``?fbclid=...``. Attached by whoever
    sent you, not by the document. It never changes what the page says — that
    is the entire reason advertisers can bolt it on — so dropping it loses no
    content, and it collapses the twelve spellings one article arrives under
    into the one page it is.

``credential``
    ``?access_token=...``, ``?sig=...``, and anything whose *value* is shaped
    like a secret whatever it is called. The strongest reason to drop these is
    not privacy in the abstract: a local database that holds a session token
    holds an account, and it is a database with no password on it.

So: known tracking names go, credentials go, everything else stays. The
value-shape test is what covers the parameter nobody enumerated — the rule
"never store a credential-shaped value" does not need to know the name.

Userinfo (``https://user:pass@host/``) is stripped unconditionally. There is
no reading of it under which it is content.

Store names
-----------
``ls build/chunks/`` used to be a browsing history: one human-readable file
per page, so the record could be read without opening it. The name is a
digest now. The url still lives *inside* the file, because the mirror is the
checkpoint the store rebuilds from and a checkpoint that has forgotten what
it is a checkpoint of is not one — but reading it costs opening it, which is
the difference between a listing and a search.
"""

from __future__ import annotations

import hashlib
import re
from typing import List, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__all__ = [
    "redact_url",
    "redact_query",
    "is_tracking_param",
    "is_credential",
    "looks_like_secret",
    "store_name",
    "STORE_NAME_RE",
]


# --- tracking ---------------------------------------------------------------

# Exact names. Every one of these is a click or campaign identifier: it says
# who sent you, never what you are looking at.
_TRACKING_NAMES = frozenset({
    "gclid", "gclsrc", "dclid", "gbraid", "wbraid", "gad_source",
    "fbclid", "msclkid", "twclid", "ttclid", "yclid", "igshid", "igsh",
    "mc_cid", "mc_eid", "mkt_tok", "vero_id", "vero_conv",
    "oly_anon_id", "oly_enc_id", "s_kwcid", "ef_id", "epik", "li_fat_id",
    "_ga", "_gl", "_hsenc", "_hsmi", "hsctatracking",
    "ref_src", "ref_url", "guccounter", "guce_referrer", "guce_referrer_sig",
    "at_medium", "at_campaign", "at_custom1", "at_custom2", "at_custom3",
    "at_custom4", "cmpid", "ncid", "icid", "ito", "wpisrc", "wpmm",
    "sr_share", "share_source", "trk", "trkcampaign", "spm", "scm",
    "_openstat", "rb_clickid", "twsrc", "cvid",
})

# Prefixed families. ``utm_`` is the obvious one; the rest are the same idea
# under other analytics vendors' names.
_TRACKING_PREFIXES = ("utm_", "pk_", "piwik_", "mtm_", "matomo_", "hsa_",
                      "itm_", "stm_", "ns_campaign", "cm_")


def is_tracking_param(name: str) -> bool:
    """Whether a query parameter is a campaign or click identifier."""
    lowered = (name or "").strip().lower()
    if lowered in _TRACKING_NAMES:
        return True
    return any(lowered.startswith(p) for p in _TRACKING_PREFIXES)


# --- credentials ------------------------------------------------------------

# Names that are a secret whatever the value looks like. Kept narrow on
# purpose: a name belongs here only when there is no reading of it under
# which it is content.
_SECRET_NAMES = frozenset({
    "password", "passwd", "pwd", "passphrase",
    "secret", "client_secret", "app_secret",
    "access_token", "refresh_token", "id_token", "auth_token", "authtoken",
    "bearer", "jwt", "api_key", "apikey", "api-key", "x-api-key",
    "private_key", "privatekey", "session_id", "sessionid", "session_key",
    "jsessionid", "phpsessid", "aspsessionid", "csrf_token", "csrftoken",
    "xsrf_token", "xsrftoken", "_csrf", "_xsrf", "authorization",
    "credential", "credentials", "auth_key", "secret_key", "sharedkey",
})

# Names that are *often* a secret and often not. ``?code=CA`` is a country
# and ``?state=NY`` is a state; both are also OAuth. These are dropped only
# when the value is shaped like a secret, so the ambiguity is settled by the
# thing that actually carries the risk.
_SUSPECT_NAMES = frozenset({
    "token", "auth", "key", "sig", "signature", "hmac", "mac", "nonce",
    "otp", "code", "state", "session", "sid", "sess", "ticket", "sso",
    "hash", "salt", "verifier", "challenge", "assertion", "saml",
})

_UUID = re.compile(
    r"^\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?$"
)
_JWT = re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*$")
# No separators at all. `/` and `.` are what a *path* and a *hostname* are
# made of, and both turn up in query values that are plainly not secrets --
# `?redirect=/a/b`, `?iu=/15786418/APNews/site/home`, `?apiKey=apnews.com`.
# Measured against the frozen corpus, admitting them mis-classified an ad
# unit path as a credential.
_OPAQUE = re.compile(r"^[A-Za-z0-9_\-=~]{16,}$")
# The same test for a parameter whose *name* already says "secret". A base64
# secret decodes with `/` and `+` in it, so those have to be admitted
# somewhere; here is where the name has already paid for the risk.
_OPAQUE_LOOSE = re.compile(r"^[A-Za-z0-9_\-=+/.~]{16,}$")
_HEX = re.compile(r"^[0-9a-fA-F]+$")


def looks_like_secret(value: str, *, allow_separators: bool = False) -> bool:
    """Whether a value is shaped like a credential rather than like content.

    Shape, not entropy. A real entropy estimate over a thirty-character
    string is noise, and the thing being separated is not "random" from
    "ordered" but *opaque* from *legible*: a secret has no word boundaries,
    no spaces, no punctuation a human put there, and enough length and
    character mixing that it could not be a slug.

    Two exemptions matter more than the rule itself.

    A **uuid** is the standard spelling of an identity, and identities are
    what the query is allowed to carry. Dropping ``?id=<uuid>`` would lose
    the document.

    A **decimal number** of any length is a database id, a timestamp or a
    page number, and never a secret on its own.
    """
    val = (value or "").strip()
    if len(val) < 16:
        # Too short to be worth taking, and short values are overwhelmingly
        # slugs, ids and words. A sixteen-character floor is what keeps
        # ``?q=cats`` and ``?v=dQw4w9WgXcQ`` out of the credential class.
        return False
    if _JWT.match(val):
        return True
    if _UUID.match(val):
        return False
    pattern = _OPAQUE_LOOSE if allow_separators else _OPAQUE
    if not pattern.match(val):
        # Anything with a space, an ampersand, a comma, a plus-as-space or a
        # non-ascii letter is text somebody meant to be read -- and, unless
        # the name has already raised the suspicion, anything with a slash or
        # a dot is a path or a host.
        return False
    if val.isdigit():
        return False
    if _HEX.match(val):
        # A hex run is a digest when it is digest-length. Sixteen hex
        # characters is a short id; thirty-two is md5, forty is sha1.
        return len(val) >= 32
    has_digit = any(c.isdigit() for c in val)
    has_alpha = any(c.isalpha() for c in val)
    if not (has_digit and has_alpha):
        # ``averylongwordwithnodigits`` is a slug, not a token.
        return False
    mixed_case = any(c.islower() for c in val) and any(c.isupper() for c in val)
    return mixed_case or len(val) >= 32


def is_credential(name: str, value: str) -> bool:
    """Whether a ``name=value`` pair is a secret this store must not hold."""
    lowered = (name or "").strip().lower()
    if lowered in _SECRET_NAMES:
        return True
    if lowered in _SUSPECT_NAMES and looks_like_secret(value,
                                                       allow_separators=True):
        return True
    # The name-independent clause. This is the one that covers the parameter
    # nobody enumerated, and it is the reason the two lists above are allowed
    # to be short.
    return looks_like_secret(value)


# --- the redaction ----------------------------------------------------------


def redact_query(query: str) -> str:
    """Drop tracking and credential parameters, keeping order and the rest.

    Order is kept because a query is not a set: some servers care, and a
    reordering would make one page two under any key built from the url.
    Repeated names stay repeated for the same reason.

    A query with nothing to drop is returned *unchanged* rather than
    re-encoded. ``parse_qsl`` is lossy on a query that is not pairs at all —
    ``?print`` comes back as ``[('print', '')]`` and would re-encode to
    ``print=`` — so a query that survives redaction intact must survive it
    byte for byte.
    """
    if not query:
        return ""
    pairs: List[Tuple[str, str]] = parse_qsl(query, keep_blank_values=True)
    if not pairs:
        return query
    kept = [(n, v) for n, v in pairs
            if not is_tracking_param(n) and not is_credential(n, v)]
    if len(kept) == len(pairs):
        return query
    if not kept:
        return ""
    return urlencode(kept)


def redact_url(url: str) -> str:
    """A url with its trackers, its credentials and its userinfo removed.

    Everything else is left exactly as it was, including the fragment and the
    case of the path: this is a redaction, not a canonicalisation, and the
    two are kept apart so that :func:`vertiscope.graphstore.canonical_url` can do
    the second on top of the first without either becoming responsible for
    the other.

    A url that does not parse comes back unchanged. There is nothing useful
    to do with it here, and a caller handed an empty string back would
    silently store nothing.
    """
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    netloc = parts.netloc
    if "@" in netloc:
        # ``https://user:pass@host/`` — the credential is in the authority,
        # and no scheme this store reads treats it as content.
        netloc = netloc.rpartition("@")[2]
    query = redact_query(parts.query)
    if netloc == parts.netloc and query == parts.query:
        return url
    return urlunsplit((parts.scheme, netloc, parts.path, query,
                       parts.fragment))


# --- store names ------------------------------------------------------------

STORE_NAME_RE = re.compile(r"^[0-9a-f]{40}$")


def store_name(url: str) -> str:
    """The on-disk name for a page's mirror: a digest, not the url.

    ``ls`` over the chunk directory used to print a browsing history, which
    made the filesystem a second, unguarded copy of the index — readable by
    anything that can list a directory, and by every backup that ever touched
    it.

    sha1 over the *redacted* url, so the name a page is stored under does not
    depend on the trackers it happened to arrive with, and so ``forget`` can
    recompute the name from a url a reader types with its trackers still
    attached.
    """
    return hashlib.sha1(
        redact_url(url).encode("utf-8", "surrogatepass")
    ).hexdigest()
