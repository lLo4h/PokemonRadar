from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

import requests

from config import RETRY_ATTEMPTS, RETRY_DELAYS


T = TypeVar("T")


@dataclass(frozen=True)
class RetryOutcome(Generic[T]):
    value: T
    retries: int


def _is_retryable(error: BaseException) -> bool:
    """Nur vorübergehende Netzwerk- und Serverfehler erneut versuchen."""
    if isinstance(error, (requests.Timeout, requests.ConnectionError)):
        return True

    if isinstance(error, requests.HTTPError):
        response = error.response
        if response is None:
            return True

        status = response.status_code
        # HTTP 429 wird bereits im jeweiligen Scanner mit einer Domain-\n        # Sperrzeit behandelt. Ein sofortiger Retry würde nur einen Worker\n        # minutenlang blockieren und den Shop nochmals belasten.\n        if status == 429:\n            return False\n        return status in {408, 425} or 500 <= status <= 599\n
    return False


def _delay_for_retry(retry_number: int) -> float:
    """retry_number beginnt bei 1."""
    if not RETRY_DELAYS:
        return 0.0

    index = min(retry_number - 1, len(RETRY_DELAYS) - 1)
    return max(0.0, float(RETRY_DELAYS[index]))


def run_with_retry(
    operation: Callable[[], T],
    *,
    label: str,
) -> RetryOutcome[T]:
    """Führt einen Shopscan mit kontrolliertem Retry und Backoff aus."""
    attempts = max(1, int(RETRY_ATTEMPTS))
    retries_used = 0

    for attempt in range(1, attempts + 1):
        try:
            return RetryOutcome(operation(), retries_used)
        except Exception as error:
            is_last_attempt = attempt >= attempts
            retryable = _is_retryable(error)

            if is_last_attempt or not retryable:
                if retries_used:
                    print(
                        f"[{label}] Retry fehlgeschlagen nach {attempt} Versuch(en): "
                        f"{type(error).__name__}: {error}"
                    )
                raise

            retries_used += 1
            wait_seconds = _delay_for_retry(retries_used)
            print(
                f"[{label}] Vorübergehender Fehler: {type(error).__name__}: {error}"
            )
            print(
                f"[{label}] Retry {retries_used}/{attempts - 1} "
                f"in {wait_seconds:g} Sekunde(n) …"
            )
            if wait_seconds:
                time.sleep(wait_seconds)

    raise RuntimeError(f"{label}: Retry-Schleife unerwartet beendet.")
