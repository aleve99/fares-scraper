"""Hubs and focus cities used to bootstrap the Vueling route graph when expanding active airports."""

DEFAULT_SEED_AIRPORTS: tuple[str, ...] = (
    "ACE",
    "AGP",
    "ALC",
    "AMS",
    "ARN",
    "ATH",
    "BCN",
    "BIO",
    "BOD",
    "BRU",
    "BUD",
    "CDG",
    "CGN",
    "CPH",
    "DUB",
    "EDI",
    "FCO",
    "FLR",
    "GVA",
    "IBZ",
    "LGW",
    "LIS",
    "LPA",
    "LYS",
    "MAD",
    "MAN",
    "MRS",
    "MUC",
    "MXP",
    "NAP",
    "NCE",
    "OPO",
    "ORY",
    "OVD",
    "PMI",
    "PRG",
    "SCQ",
    "STR",
    "SVQ",
    "TFN",
    "TFS",
    "TLS",
    "VLC",
    "VIE",
    "ZRH",
)

# Non-airport three-letter tokens sometimes present in ancillary JSON.
_IATA_BLOCKLIST: frozenset[str] = frozenset(
    {
        "EUR",
        "USD",
        "GBP",
        "CHF",
        "SEK",
        "NOK",
        "DKK",
        "API",
        "WEB",
        "GMT",
        "UTC",
        "VY",
        "BA",
        "OP",
        "URL",
        "XML",
        "PDF",
        "SMS",
    }
)


def is_plausible_iata(code: str) -> bool:
    c = (code or "").strip().upper()
    if len(c) != 3 or not c.isalpha():
        return False
    return c not in _IATA_BLOCKLIST
