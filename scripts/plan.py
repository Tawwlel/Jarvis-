"""What the CUSTOMER sees about their plan. Customers never see credits, tokens, keys or amounts: only whether
their plan is active, running low or needs paying. The owner (Apricot Digital) can switch this off on their own
laptop with "owner_mode": true in config.local.json."""
from tools import CTX

BILL = ("Your Jarvis plan for this month is used up. Please pay your bill to Apricot Digital to continue; "
        "I'll be back to full speed as soon as it's renewed. I can still find your files meanwhile.")
LOW = "Your Jarvis plan is almost used up for this month. Please contact Apricot Digital to renew it in time."
NOT_READY = ("Jarvis isn't activated on this computer yet. Please contact Apricot Digital to finish your setup "
             "(your plan or payment may be pending). I can still find your files meanwhile.")


def customer_mode(cfg: dict | None = None) -> bool:
    cfg = cfg if cfg is not None else CTX.get("cfg") or {}
    if not cfg:
        try:
            import config
            cfg = config.load_config()
        except Exception:
            cfg = {}
    return not cfg.get("owner_mode", False)


def status() -> tuple[str, str]:
    """(short label for the screen, sentence for the customer)."""
    try:
        import licence
        if licence.blocked():
            return "PAUSED", licence.message()
    except Exception:
        pass
    try:
        import usage
        p = usage.percent()
    except Exception:
        p = 0
    if p >= 100:
        return "RENEW", BILL
    if p >= 80:
        return "RUNNING LOW", LOW
    return "ACTIVE", "Your Jarvis plan is active."
