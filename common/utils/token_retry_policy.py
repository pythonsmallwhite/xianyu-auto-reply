"""Retry policy shared by the websocket connect and cookie-refresh loops."""

CAPTCHA_RETRY_DEFER_STATUSES = frozenset({
    "failed_captcha",
    "failed_captcha_exception",
    "failed_captcha_max_retries",
})

COOKIE_REFRESH_DEFER_STATUSES = CAPTCHA_RETRY_DEFER_STATUSES | frozenset({
    "skipped_local_slider_disabled",
    "skipped_local_slider_config_unavailable",
    "skipped_risk_control_processing",
    "skipped_risk_control_check_failed",
    "skipped_startup_cache_lookup_failed",
})


def token_failure_retry_delay(status: str, cookie_refresh_interval: int) -> int:
    """Avoid repeating captcha work every few seconds after a known recoverable failure."""
    if status == "skipped_cooldown":
        return 300
    if status in COOKIE_REFRESH_DEFER_STATUSES:
        return max(1, int(cookie_refresh_interval))
    return 5
