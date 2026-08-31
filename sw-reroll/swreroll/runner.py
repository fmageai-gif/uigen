"""Orchestration: run the reroll loop across one or more emulator instances."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .adb import AdbDevice, AdbError
from .config import ConfigError, Flow, RunConfig
from .flow import AbortAccount, Context, StepTimeout, run_phase
from .ocr import Ocr, OcrError
from .vision import TemplateError, TemplateStore

log = logging.getLogger(__name__)

STOP_FILE = "STOP"


@dataclass
class AccountResult:
    serial: str
    index: int
    account_id: str
    keep: bool
    hits: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    vars: dict = field(default_factory=dict)
    seconds: float = 0.0
    error: str = ""
    finished_at: str = ""


@dataclass
class Stats:
    accounts: int = 0
    keeps: int = 0
    errors: int = 0
    started: float = field(default_factory=time.monotonic)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def summary(self) -> str:
        rate = self.accounts / (self.elapsed / 3600) if self.elapsed > 0 else 0.0
        per = self.elapsed / self.accounts if self.accounts else 0.0
        return (
            f"{self.accounts} accounts, {self.keeps} keeps, {self.errors} errors | "
            f"{per / 60:.1f} min/account, {rate:.1f} accounts/hour | "
            f"elapsed {self.elapsed / 3600:.2f}h"
        )


class Runner:
    """Drives N devices in parallel, one worker thread each."""

    def __init__(self, cfg: RunConfig, flow: Flow) -> None:
        self.cfg = cfg
        self.flow = flow
        if cfg.wanted:
            flow.defaults["wanted"] = list(cfg.wanted)
        self.store = TemplateStore(cfg.templates_dir)
        self.ocr = Ocr(
            binary=cfg.tesseract, lang=cfg.lang, tessdata_dir=cfg.tessdata_dir
        )
        self.stats = Stats()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.results: list[AccountResult] = []

        self.out_dir = Path(cfg.out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self.out_dir / "results.jsonl"

    # ---- control ---------------------------------------------------------

    def stop(self) -> None:
        self._stop.set()

    def _should_stop(self) -> bool:
        if self._stop.is_set():
            return True
        # Touching a file named STOP in the run directory is the least
        # surprising kill switch when this is running unattended overnight.
        if (self.out_dir / STOP_FILE).exists():
            log.info("STOP file present, winding down")
            self._stop.set()
            return True
        with self._lock:
            if self.cfg.max_accounts and self.stats.accounts >= self.cfg.max_accounts:
                return True
        return False

    def _record(self, result: AccountResult) -> None:
        with self._lock:
            self.results.append(result)
            self.stats.accounts += 1
            self.stats.keeps += int(result.keep)
            self.stats.errors += int(bool(result.error))
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(result)) + "\n")
            log.info(
                "[%s] account %d %s | %s",
                result.serial,
                self.stats.accounts,
                "KEEP" if result.keep else ("ERROR" if result.error else "reroll"),
                self.stats.summary(),
            )

    # ---- worker ----------------------------------------------------------

    def _run_account(self, device: AdbDevice, index: int) -> AccountResult:
        account_id = f"{device.serial.replace(':', '_')}-{index:05d}"
        ctx = Context(
            device=device,
            store=self.store,
            flow=self.flow,
            threshold=self.cfg.match_threshold,
            step_timeout=self.cfg.step_timeout,
            out_dir=self.out_dir,
            save_shots=self.cfg.save_shots,
            account_id=account_id,
            ocr=self.ocr,
        )
        started = time.monotonic()
        error = ""
        # `reset` and `wipe` are always protected; a flow can name others that
        # are simply a waste of time once the account is already worth keeping.
        skip_on_keep = {"reset", "wipe"} | set(
            str(n) for n in (self.flow.defaults.get("skip_on_keep") or ())
        )
        try:
            for phase_name in self.flow.order:
                if self._stop.is_set():
                    break
                phase = self.flow.phase(phase_name)
                # Once a keeper is confirmed, never run the phase that wipes
                # it -- nor any phase the flow marks as pointless after a hit.
                if ctx.keep and phase_name in skip_on_keep:
                    log.info(
                        "[%s] keeper found -- skipping %s", device.serial, phase_name
                    )
                    continue
                run_phase(ctx, phase)
        except AbortAccount as exc:
            error = f"aborted: {exc}"
            log.warning("[%s] %s", device.serial, error)
        except StepTimeout as exc:
            error = f"timeout: {exc}"
            log.warning("[%s] %s", device.serial, error)
        except AdbError as exc:
            error = f"adb: {exc}"
            log.error("[%s] %s", device.serial, error)
        except (ConfigError, TemplateError, OcrError) as exc:
            # An operator error -- a typo'd template name, a missing crop, no
            # tesseract. Record it rather than killing the worker thread; the
            # consecutive-failure guard below will stop the device shortly.
            error = f"config: {exc}"
            log.error("[%s] %s", device.serial, error)

        return AccountResult(
            serial=device.serial,
            index=index,
            account_id=account_id,
            keep=ctx.keep,
            hits=list(ctx.hits),
            notes=list(ctx.notes),
            vars=dict(ctx.vars),
            seconds=round(time.monotonic() - started, 1),
            error=error,
            finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    def _worker(self, serial: str) -> None:
        device = AdbDevice(
            serial=serial, adb_path=self.cfg.adb_path, dry_run=self.cfg.dry_run
        )
        if not self.cfg.dry_run and not device.is_installed(self.flow.package):
            log.error(
                "[%s] %s is not installed. Check the package id with: "
                "adb -s %s shell pm list packages | grep -i smon",
                serial, self.flow.package, serial,
            )
            return

        keeps_here = 0
        index = 0
        consecutive_errors = 0

        while not self._should_stop():
            index += 1
            result = self._run_account(device, index)
            self._record(result)

            if result.error:
                consecutive_errors += 1
                # Something structural is wrong -- a changed menu, a dead
                # emulator. Grinding out hundreds of identical failures helps
                # nobody, so back off and let the operator look at the shots.
                if consecutive_errors >= 5:
                    log.error(
                        "[%s] 5 consecutive failures, stopping this device. "
                        "Check %s/shots for the TIMEOUT screenshots.",
                        serial, self.out_dir,
                    )
                    return
            else:
                consecutive_errors = 0

            if result.keep:
                keeps_here += 1
                log.warning(
                    "[%s] KEEPER on account %d: %s -- app data left intact.",
                    serial, index, ", ".join(result.hits) or "match",
                )
                if self.cfg.max_keeps and keeps_here >= self.cfg.max_keeps:
                    log.warning(
                        "[%s] reached max_keeps=%d. Go bind this account to a "
                        "Hive login before you touch anything else.",
                        serial, self.cfg.max_keeps,
                    )
                    return

    # ---- entry point -----------------------------------------------------

    def run(self) -> Stats:
        serials = self.cfg.serials
        if not serials:
            raise RuntimeError("no devices to run against")

        log.info("starting on %d device(s): %s", len(serials), ", ".join(serials))
        threads = [
            threading.Thread(target=self._worker, args=(s,), name=f"dev-{s}", daemon=True)
            for s in serials
        ]
        for t in threads:
            t.start()
        try:
            while any(t.is_alive() for t in threads):
                time.sleep(0.5)
        except KeyboardInterrupt:
            log.warning("interrupted -- letting workers finish the current account")
            self.stop()
            for t in threads:
                t.join(timeout=60)

        log.info("done: %s", self.stats.summary())
        return self.stats
