from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Protocol, TypeVar

from config import DASHBOARD_REFRESH_SECONDS
from logging_utils import console_write, set_dashboard_mode
from retry import RetryOutcome


T = TypeVar("T")


class ScanJob(Protocol):
    def __getitem__(self, key: str) -> object: ...


@dataclass
class JobState:
    name: str
    scanner: Callable[[], T]
    interval_seconds: int
    next_due: float
    future: Future[T] | None = None
    started_at: float | None = None
    scans_started: int = 0
    scans_ok: int = 0
    errors: int = 0
    retries_total: int = 0
    last_retries: int = 0
    last_duration: float | None = None
    last_products: int | None = None
    last_notifications: int = 0
    last_error: str = ""
    last_finished_at: datetime | None = None


def _timestamp() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def _advance_missed_slots(state: JobState, now: float) -> None:
    while state.next_due <= now:
        state.next_due += state.interval_seconds


def _format_uptime(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _status_text(state: JobState, now: float) -> str:
    if state.future is not None:
        running_for = now - (state.started_at or now)
        return f"LÄUFT {running_for:4.1f}s"

    due_in = max(0, int(round(state.next_due - now)))
    if state.last_error:
        return f"FEHLER · erneut in {due_in:2d}s"
    if state.scans_ok:
        return f"OK · in {due_in:2d}s"
    return f"START · in {due_in:2d}s"


def _render_dashboard(
    states: list[JobState],
    *,
    started_at: float,
    max_workers: int,
    total_products: int,
    total_notifications: int,
    total_errors: int,
    total_retries: int,
) -> None:
    now = time.monotonic()
    active = sum(state.future is not None for state in states)
    lines = [
        "=" * 78,
        "                         POKÉMON RADAR · LIVE",
        "=" * 78,
        f"Uptime: {_format_uptime(now - started_at)}   "
        f"Aktive Scans: {active}/{max_workers}   "
        f"Produkte geprüft: {total_products:,}".replace(",", "'"),
        f"Discord-Änderungen: {total_notifications}   "
        f"Retries: {total_retries}   Fehler: {total_errors}   "
        f"Log: logs/{datetime.now().strftime('%Y-%m-%d')}.log",
        "-" * 78,
        f"{'Shop':<24} {'Intervall':>9}  {'Status':<22} {'Letzter Scan':<16}",
        "-" * 78,
    ]

    for state in sorted(states, key=lambda item: (item.interval_seconds, item.name.lower())):
        last_scan = "noch keiner"
        if state.last_finished_at is not None:
            duration = f"{state.last_duration:.1f}s" if state.last_duration is not None else ""
            products = f"{state.last_products} Prod." if state.last_products is not None else ""
            retry_info = f"R{state.last_retries}" if state.last_retries else ""
            last_scan = f"{duration} {products} {retry_info}".strip()
        lines.append(
            f"{state.name:<24} {state.interval_seconds:>6}s   "
            f"{_status_text(state, now):<22} {last_scan:<16}"
        )

    recent_errors = [state for state in states if state.last_error]
    lines.append("-" * 78)
    if recent_errors:
        latest = recent_errors[-1]
        lines.append(f"Letzter Fehler: {latest.name}: {latest.last_error[:55]}")
    else:
        lines.append("Status: Alle Shops ohne aktuellen Fehler.")
    lines.append("Beenden mit Strg + C")
    lines.append("=" * 78)

    console_write("\n".join(lines) + "\n", clear=True)


def run_shop_scheduler(
    jobs: Iterable[ScanJob],
    process_result: Callable[[str, T], object],
    *,
    max_workers: int = 5,
    poll_seconds: float = 0.25,
    dashboard: bool = False,
) -> None:
    """Startet jeden Shop nach seinem eigenen Intervall.

    Im Dashboard-Modus bleiben vollständige Details in der täglichen Logdatei,
    während das Terminal nur eine laufend aktualisierte Übersicht zeigt.
    """
    raw_jobs = list(jobs)
    if not raw_jobs:
        print("[SCHEDULER] Keine Shops konfiguriert.")
        return

    workers = max(1, min(int(max_workers), len(raw_jobs)))
    scheduler_started = time.monotonic()
    states: list[JobState] = []

    for job in raw_jobs:
        name = str(job["name"])
        scanner = job["scanner"]
        interval = max(5, int(job.get("interval_seconds", 60)))  # type: ignore[attr-defined]
        if not callable(scanner):
            raise TypeError(f"Scanner für '{name}' ist nicht aufrufbar.")
        states.append(
            JobState(
                name=name,
                scanner=scanner,  # type: ignore[arg-type]
                interval_seconds=interval,
                next_due=scheduler_started,
            )
        )

    total_products = 0
    total_notifications = 0
    total_errors = 0
    total_retries = 0
    last_dashboard_refresh = 0.0

    print("=" * 64)
    print(f"[{_timestamp()}] [SCHEDULER] Pokémon Radar gestartet.")
    print(f"[{_timestamp()}] [SCHEDULER] Parallele Shop-Scans: maximal {workers}")
    print(f"[{_timestamp()}] [SCHEDULER] Dashboard: {'aktiv' if dashboard else 'aus'}")
    print(f"[{_timestamp()}] [SCHEDULER] Beenden mit Strg + C.")

    if dashboard:
        set_dashboard_mode(True)
        _render_dashboard(
            states,
            started_at=scheduler_started,
            max_workers=workers,
            total_products=0,
            total_notifications=0,
            total_errors=0,
            total_retries=0,
        )
    else:
        print("-" * 64)
        for state in sorted(states, key=lambda item: (item.interval_seconds, item.name.lower())):
            print(f"{state.name:<24} alle {state.interval_seconds:>2} Sekunden")
        print("=" * 64)

    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="shop-scheduler") as executor:
            while True:
                now = time.monotonic()

                for state in states:
                    future = state.future
                    if future is None or not future.done():
                        continue

                    duration = now - (state.started_at or now)
                    state.future = None
                    state.started_at = None
                    state.last_duration = duration
                    state.last_finished_at = datetime.now()

                    print(f"\n[{_timestamp()}] [{state.name}] Download abgeschlossen ({duration:.1f} s).")
                    try:
                        outcome = future.result()
                        if isinstance(outcome, RetryOutcome):
                            products = outcome.value
                            state.last_retries = outcome.retries
                        else:
                            products = outcome
                            state.last_retries = 0

                        state.retries_total += state.last_retries
                        total_retries += state.last_retries
                        if state.last_retries:
                            print(
                                f"[{state.name}] Scan nach {state.last_retries} Retry(s) erfolgreich."
                            )

                        result = process_result(state.name, products)
                        state.scans_ok += 1
                        state.last_error = ""

                        if isinstance(result, dict):
                            state.last_products = int(result.get("products", len(products)))
                            state.last_notifications = int(result.get("notifications", 0))
                        else:
                            state.last_products = len(products)
                            state.last_notifications = 0

                        total_products += state.last_products or 0
                        total_notifications += state.last_notifications
                    except Exception as error:
                        state.errors += 1
                        state.last_retries = 0
                        total_errors += 1
                        state.last_error = f"{type(error).__name__}: {error}"
                        print(f"[{state.name}] FEHLER: {state.last_error}")

                now = time.monotonic()
                for state in states:
                    if state.future is not None and state.next_due <= now:
                        _advance_missed_slots(state, now)

                active_count = sum(state.future is not None for state in states)
                free_slots = max(0, workers - active_count)
                if free_slots:
                    due_states = sorted(
                        (
                            state
                            for state in states
                            if state.future is None and state.next_due <= now
                        ),
                        key=lambda item: (item.next_due, item.interval_seconds, item.name.lower()),
                    )

                    for state in due_states[:free_slots]:
                        state.scans_started += 1
                        state.started_at = time.monotonic()
                        state.future = executor.submit(state.scanner)
                        state.next_due += state.interval_seconds
                        print(
                            f"[{_timestamp()}] [{state.name}] Scan #{state.scans_started} gestartet "
                            f"(Intervall {state.interval_seconds} s)."
                        )

                if dashboard and now - last_dashboard_refresh >= max(0.2, float(DASHBOARD_REFRESH_SECONDS)):
                    _render_dashboard(
                        states,
                        started_at=scheduler_started,
                        max_workers=workers,
                        total_products=total_products,
                        total_notifications=total_notifications,
                        total_errors=total_errors,
                        total_retries=total_retries,
                    )
                    last_dashboard_refresh = now

                time.sleep(max(0.05, float(poll_seconds)))

    except KeyboardInterrupt:
        if dashboard:
            set_dashboard_mode(False)
            console_write("\033[2J\033[H")
        print(f"\n[{_timestamp()}] [SCHEDULER] Beenden angefordert …")
        print(f"[{_timestamp()}] [SCHEDULER] Laufende Downloads werden sauber beendet.")
        print(f"[{_timestamp()}] [SCHEDULER] Pokémon Radar wurde beendet.")
