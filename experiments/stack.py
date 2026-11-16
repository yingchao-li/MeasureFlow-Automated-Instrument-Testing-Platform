#!/usr/bin/env python3
"""Private MeasureFlow test stack (simulator + C++ backend) on free ports.

Used by ``tests/conftest.py`` (pytest), ``experiments/run_experiments.py`` and, via ``--serve``,
by the Playwright end-to-end suite. Design rules:

* never uses the default ports (8080 / 5025..5027) so a developer stack can run concurrently;
* works on *snapshots*: the backend binary, ``frontend/dist`` and the simulator package are copied
  into a private temp directory first, so concurrent rebuilds cannot disturb a running experiment;
* the backend gets its own temporary ``--root`` (copy of ``configs/`` with the instrument ports
  rewritten, empty ``results/`` and ``reports/``);
* every child runs in its own process group; teardown is SIGTERM -> SIGKILL, also on ``atexit``,
  SIGINT/SIGTERM of the owner and on exceptions;
* stdout/stderr of both children are captured in ``<workdir>/logs``.

CLI (for Playwright)::

    python3 experiments/stack.py --serve --print-url [--backend-port P] [--control-port C]

starts a stack, prints one ``MFSTACK {...json...}`` line and serves a tiny control API on
``127.0.0.1:<control-port>`` (``/state``, ``/reset``, ``/backend/{stop,start,restart,kill}``,
``/simulator/{stop,start,restart,kill}``) until SIGTERM/SIGINT.
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import platform
import random
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import weakref
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable, Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from faultproxy import FaultProxy  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTRUMENT_IDS = ("siggen", "analyzer", "dut")
TERMINAL_STATES = ("PASS", "FAIL", "ERROR", "CANCELLED")


class StackError(RuntimeError):
    """Stack could not be started / a helper timed out."""


class ScpiClosed(ConnectionError):
    """Peer closed the connection (``partial`` holds bytes received before the close)."""

    def __init__(self, msg: str = "connection closed", partial: bytes = b"") -> None:
        super().__init__(msg)
        self.partial = partial


class ScpiTimeout(TimeoutError):
    """No complete line within the timeout (``partial`` holds bytes received so far)."""

    def __init__(self, msg: str = "timeout", partial: bytes = b"") -> None:
        super().__init__(msg)
        self.partial = partial


# --------------------------------------------------------------------------------------------
# raw SCPI client
# --------------------------------------------------------------------------------------------
class ScpiClient:
    """Minimal line-oriented SCPI/TCP client with a receive buffer (supports pipelining)."""

    def __init__(self, host: str, port: int, timeout: float = 5.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.timeout = timeout
        self.buf = b""

    def __enter__(self) -> "ScpiClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def send_raw(self, data: bytes) -> None:
        self.sock.sendall(data)

    def write(self, cmd: str) -> None:
        self.sock.sendall(cmd.encode("ascii") + b"\n")

    def read_line(self, timeout: Optional[float] = None, max_bytes: int = 64 * 1024 * 1024) -> str:
        """Read one ``\\n``-terminated line (terminator stripped)."""
        t = self.timeout if timeout is None else timeout
        deadline = time.monotonic() + t
        while True:
            nl = self.buf.find(b"\n")
            if nl >= 0:
                line, self.buf = self.buf[:nl], self.buf[nl + 1:]
                return line.decode("ascii", "replace")
            if len(self.buf) > max_bytes:
                raise ValueError(f"line longer than {max_bytes} bytes")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ScpiTimeout("timed out waiting for a line", self.buf)
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(1 << 20)
            except socket.timeout:
                raise ScpiTimeout("timed out waiting for a line", self.buf) from None
            except (ConnectionResetError, BrokenPipeError):
                raise ScpiClosed("connection reset", self.buf) from None
            if not chunk:
                raise ScpiClosed("connection closed by peer", self.buf)
            self.buf += chunk

    def read_chunks(self, until_newline: bool = True, timeout: float = 5.0) -> list[tuple[float, bytes]]:
        """Return ``[(monotonic_time, bytes), ...]`` for each ``recv`` (to observe fragmentation)."""
        out: list[tuple[float, bytes]] = []
        deadline = time.monotonic() + timeout
        if self.buf:
            out.append((time.monotonic(), self.buf))
            self.buf = b""
        while True:
            if until_newline and out and b"\n" in out[-1][1]:
                return out
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ScpiTimeout("timed out in read_chunks", b"".join(c for _, c in out))
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                raise ScpiTimeout("timed out in read_chunks", b"".join(c for _, c in out)) from None
            if not chunk:
                raise ScpiClosed("closed in read_chunks", b"".join(c for _, c in out))
            out.append((time.monotonic(), chunk))

    def query(self, cmd: str, timeout: Optional[float] = None) -> str:
        self.write(cmd)
        return self.read_line(timeout)

    def expect_no_data(self, wait: float = 0.15) -> bool:
        """True if nothing arrives within ``wait`` seconds and the peer is still connected."""
        self.sock.settimeout(wait)
        try:
            chunk = self.sock.recv(65536)
        except socket.timeout:
            return True
        except OSError:
            return False
        if chunk:
            self.buf += chunk
        return False

    def is_closed_by_peer(self, wait: float = 1.0) -> bool:
        """True if the peer closed the connection (EOF/reset) within ``wait`` seconds."""
        self.sock.settimeout(wait)
        try:
            chunk = self.sock.recv(65536)
        except socket.timeout:
            return False
        except (ConnectionResetError, BrokenPipeError):
            return True
        except OSError:
            return True
        if chunk:
            self.buf += chunk
            return False
        return True


# --------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------
def _bindable(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


_RNG = random.Random(os.getpid() ^ int(time.time() * 1000))
_RESERVED: set[int] = set()


def free_port_block(n: int = 1, lo: int = 20000, hi: int = 30000) -> int:
    """Find ``n`` consecutive bindable loopback ports below the ephemeral range; return the first."""
    for _ in range(500):
        base = _RNG.randrange(lo, hi - n)
        ports = range(base, base + n)
        if any(p in _RESERVED for p in ports):
            continue
        if all(_bindable(p) for p in ports):
            _RESERVED.update(ports)
            return base
    raise StackError("no free port block found")


def proc_stats(pid: int) -> dict[str, Any]:
    """RSS (kB), open fds and threads of a process from /proc (Linux) or psutil."""
    try:
        status = Path(f"/proc/{pid}/status").read_text()
        rss = threads = None
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1])
            elif line.startswith("Threads:"):
                threads = int(line.split()[1])
        fds = len(os.listdir(f"/proc/{pid}/fd"))
        return {"pid": pid, "rss_kb": rss, "fds": fds, "threads": threads}
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        pass
    try:
        import psutil  # type: ignore

        p = psutil.Process(pid)
        return {"pid": pid, "rss_kb": p.memory_info().rss // 1024,
                "fds": p.num_fds() if hasattr(p, "num_fds") else None, "threads": p.num_threads()}
    except Exception:  # noqa: BLE001
        return {"pid": pid, "rss_kb": None, "fds": None, "threads": None}


_LIVE: "weakref.WeakSet[Stack]" = weakref.WeakSet()


def _cleanup_all() -> None:
    for st in list(_LIVE):
        try:
            st.stop()
        except Exception:  # noqa: BLE001
            pass


atexit.register(_cleanup_all)


def _kill_group(proc: Optional[subprocess.Popen[bytes]], sig: int) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        try:
            proc.send_signal(sig)
        except Exception:  # noqa: BLE001
            pass


def terminate(proc: Optional[subprocess.Popen[bytes]], term_timeout: float = 5.0) -> Optional[int]:
    """SIGTERM the process group, SIGKILL after ``term_timeout``. Returns the exit code."""
    if proc is None:
        return None
    if proc.poll() is None:
        _kill_group(proc, signal.SIGTERM)
        try:
            proc.wait(term_timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc, signal.SIGKILL)
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                pass
    else:
        # make sure no orphaned group members survive
        _kill_group(proc, signal.SIGKILL)
    return proc.returncode


# --------------------------------------------------------------------------------------------
# Stack
# --------------------------------------------------------------------------------------------
class Stack:
    """A private simulator + backend (+ optional fault proxy) with helpers."""

    def __init__(
        self,
        root: Path | str = REPO_ROOT,
        backend: Path | str | None = None,
        seed: int = 12345,
        *,
        with_backend: bool = True,
        with_proxy: bool = False,
        overrides: Optional[dict[str, dict[str, Any]]] = None,
        config_extra: Optional[dict[str, Any]] = None,
        config_files: Optional[dict[str, Any]] = None,
        workdir: Path | str | None = None,
        snapshot: bool = True,
        keep: bool = False,
        name: str = "mf",
        sim_base_port: Optional[int] = None,
        backend_port: Optional[int] = None,
        backend_args: Iterable[str] = (),
        http_timeout: float = 30.0,
    ) -> None:
        self.root = Path(root).resolve()
        self.backend_src = Path(backend).resolve() if backend else self.root / "backend" / "build" / "measureflow_backend"
        self.seed = seed
        self.with_backend = with_backend
        self.with_proxy = with_proxy
        self.overrides = overrides or {}
        self.config_extra = config_extra or {}
        self.config_files = config_files or {}     # relative path under configs/ -> JSON-serialisable content
        self.snapshot = snapshot
        self.keep = keep
        self.name = name
        self.backend_args = list(backend_args)
        self.http_timeout = http_timeout
        self._own_workdir = workdir is None
        self.workdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix=f"{name}-stack-"))
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.log_dir = self.workdir / "logs"
        self.mf_root = self.workdir / "root"           # --root of the backend
        self.sim_cwd = self.workdir / "simulator"
        self.backend_bin = self.workdir / "bin" / "measureflow_backend"
        n_ports = 3
        self.sim_base_port = sim_base_port or free_port_block(n_ports)
        self.sim_ports = {iid: self.sim_base_port + i for i, iid in enumerate(INSTRUMENT_IDS)}
        self.backend_port = backend_port or free_port_block(1)
        self.base_url = f"http://127.0.0.1:{self.backend_port}"
        self.proxy: Optional[FaultProxy] = FaultProxy(self.sim_ports) if with_proxy else None
        self.backend_proc: Optional[subprocess.Popen[bytes]] = None
        self.sim_proc: Optional[subprocess.Popen[bytes]] = None
        self.http = requests.Session()
        self.http.trust_env = False           # never route loopback through a configured proxy
        self.http_calls = 0
        self._started = False
        self._lock = threading.RLock()
        self.python = os.environ.get("MF_PYTHON", sys.executable)
        _LIVE.add(self)

    # ------------------------------------------------------------------ properties
    @property
    def instrument_ports(self) -> dict[str, int]:
        """Ports the *backend* is configured with (proxy ports when a proxy is used)."""
        return dict(self.proxy.listen_ports) if self.proxy else dict(self.sim_ports)

    @property
    def backend_pid(self) -> Optional[int]:
        return self.backend_proc.pid if self.backend_proc and self.backend_proc.poll() is None else None

    @property
    def results_dir(self) -> Path:
        return self.mf_root / "results"

    @property
    def reports_dir(self) -> Path:
        return self.mf_root / "reports"

    def run_dir(self, run_id: str) -> Path:
        return self.results_dir / "runs" / run_id

    # ------------------------------------------------------------------ preparation
    def _prepare(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # configs with rewritten ports / overrides
        shutil.copytree(self.root / "configs", self.mf_root / "configs", dirs_exist_ok=True)
        inst_path = self.mf_root / "configs" / "instruments.json"
        cfg = json.loads(inst_path.read_text())
        ports = self.instrument_ports
        for inst in cfg["instruments"]:
            inst["port"] = ports[inst["id"]]
            inst.update(self.overrides.get(inst["id"], {}))
        cfg.update(self.config_extra)
        inst_path.write_text(json.dumps(cfg, indent=2))
        for rel, content in self.config_files.items():
            target = self.mf_root / "configs" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content if isinstance(content, str) else json.dumps(content, indent=2))
        for d in ("results", "reports"):
            (self.mf_root / d).mkdir(parents=True, exist_ok=True)
        # frontend snapshot
        dist = self.root / "frontend" / "dist"
        if dist.is_dir():
            shutil.copytree(dist, self.mf_root / "frontend" / "dist", dirs_exist_ok=True)
        # backend binary snapshot
        if self.with_backend:
            if not self.backend_src.is_file():
                raise StackError(f"backend binary not found: {self.backend_src}")
            self.backend_bin.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.backend_src, self.backend_bin)
            self.backend_bin.chmod(0o755)
        # simulator snapshot
        sim_src = self.root / "simulator"
        if self.snapshot:
            shutil.copytree(sim_src, self.sim_cwd, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc", ".pytest_cache"))
        else:
            self.sim_cwd = sim_src
        if not (self.sim_cwd / "mfsim" / "__main__.py").is_file():
            raise StackError(f"simulator not available: {self.sim_cwd / 'mfsim' / '__main__.py'} missing")

    # ------------------------------------------------------------------ process control
    def _spawn(self, argv: list[str], log: str, cwd: Path, env: Optional[dict[str, str]] = None) -> subprocess.Popen[bytes]:
        fh = open(self.log_dir / log, "ab", buffering=0)
        fh.write(f"\n--- start {time.strftime('%H:%M:%S')} {' '.join(argv)}\n".encode())
        e = dict(os.environ)
        e["PYTHONUNBUFFERED"] = "1"
        e.update(env or {})
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
            e.pop(k, None)
        return subprocess.Popen(argv, cwd=str(cwd), stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True, env=e)

    def log_text(self, which: str, tail: int = 60) -> str:
        p = self.log_dir / f"{which}.log"
        if not p.exists():
            return ""
        return "\n".join(p.read_text(errors="replace").splitlines()[-tail:])

    def start_simulator(self, seed: Optional[int] = None, timeout: float = 20.0) -> None:
        with self._lock:
            if seed is not None:
                self.seed = seed
            if self.sim_proc and self.sim_proc.poll() is None:
                raise StackError("simulator already running")
            log = self.log_dir / "simulator.log"
            offset = log.stat().st_size if log.exists() else 0
            self.sim_proc = self._spawn(
                [self.python, "-m", "mfsim", "--host", "127.0.0.1", "--base-port", str(self.sim_base_port),
                 "--seed", str(self.seed)], "simulator.log", self.sim_cwd)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.sim_proc.poll() is not None:
                    raise StackError(f"simulator exited early (code {self.sim_proc.returncode}):\n{self.log_text('simulator')}")
                with open(log, "rb") as fh:
                    fh.seek(offset)
                    if b"READY" in fh.read():
                        return
                time.sleep(0.05)
            raise StackError(f"simulator did not print READY within {timeout}s:\n{self.log_text('simulator')}")

    def stop_simulator(self) -> None:
        with self._lock:
            terminate(self.sim_proc)
            self.sim_proc = None

    def kill_simulator(self) -> None:
        """Hard kill (SIGKILL) -- simulates an instrument crash / power loss."""
        with self._lock:
            _kill_group(self.sim_proc, signal.SIGKILL)
            if self.sim_proc:
                try:
                    self.sim_proc.wait(5)
                except subprocess.TimeoutExpired:
                    pass
            self.sim_proc = None

    def restart_simulator(self, seed: Optional[int] = None) -> None:
        self.stop_simulator()
        self._wait_ports_free()
        self.start_simulator(seed)

    def _wait_ports_free(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if all(_bindable(p) for p in self.sim_ports.values()):
                return
            time.sleep(0.05)

    def start_backend(self, timeout: float = 20.0) -> None:
        with self._lock:
            if self.backend_proc and self.backend_proc.poll() is None:
                raise StackError("backend already running")
            self.backend_proc = self._spawn(
                [str(self.backend_bin), "--root", str(self.mf_root), "--host", "127.0.0.1",
                 "--port", str(self.backend_port), *self.backend_args], "backend.log", self.workdir)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.backend_proc.poll() is not None:
                    raise StackError(f"backend exited early (code {self.backend_proc.returncode}):\n{self.log_text('backend')}")
                try:
                    r = self.http.get(self.base_url + "/api/health", timeout=1.0)
                    if r.status_code == 200:
                        return
                except requests.RequestException:
                    pass
                time.sleep(0.05)
            raise StackError(f"backend /api/health not answering within {timeout}s:\n{self.log_text('backend')}")

    def stop_backend(self) -> Optional[int]:
        with self._lock:
            code = terminate(self.backend_proc)
            self.backend_proc = None
            return code

    def kill_backend(self) -> None:
        with self._lock:
            _kill_group(self.backend_proc, signal.SIGKILL)
            if self.backend_proc:
                try:
                    self.backend_proc.wait(5)
                except subprocess.TimeoutExpired:
                    pass
            self.backend_proc = None

    def restart_backend(self, hard: bool = False) -> None:
        (self.kill_backend if hard else self.stop_backend)()
        self.start_backend()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> "Stack":
        for attempt in range(3):
            try:
                self._prepare()
                if self.proxy:
                    self.proxy.start()
                self.start_simulator()
                if self.with_backend:
                    self.start_backend()
                self._started = True
                return self
            except StackError as exc:
                self._stop_children()
                if attempt == 2 or "Address already in use" not in (str(exc) + self.log_text("simulator") + self.log_text("backend")):
                    self.stop()
                    raise
                # port race with another process: pick new ports and retry
                self.sim_base_port = free_port_block(3)
                self.sim_ports = {iid: self.sim_base_port + i for i, iid in enumerate(INSTRUMENT_IDS)}
                self.backend_port = free_port_block(1)
                self.base_url = f"http://127.0.0.1:{self.backend_port}"
        raise StackError("unreachable")

    def _stop_children(self) -> None:
        self.stop_backend()
        self.stop_simulator()

    def stop(self) -> None:
        with self._lock:
            self._stop_children()
            if self.proxy:
                self.proxy.stop()
            try:
                self.http.close()
            except Exception:  # noqa: BLE001
                pass
            if self._own_workdir and not self.keep and self.workdir.exists():
                shutil.rmtree(self.workdir, ignore_errors=True)
            self._started = False

    def __enter__(self) -> "Stack":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def reset(self, seed: Optional[int] = None) -> None:
        """Stop both children, wipe results/reports, start again (fresh empty history)."""
        self._stop_children()
        for d in (self.results_dir, self.reports_dir):
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)
        if self.proxy:
            self.proxy.reset()
            self.proxy.clear_trace()
        self._wait_ports_free()
        self.start_simulator(seed)
        if self.with_backend:
            self.start_backend()

    # ------------------------------------------------------------------ HTTP
    def api(self, method: str, path: str, json: Any = None, *, params: Optional[dict[str, Any]] = None,
            headers: Optional[dict[str, str]] = None, data: Any = None, timeout: Optional[float] = None
            ) -> requests.Response:
        self.http_calls += 1
        return self.http.request(method.upper(), self.base_url + path, json=json, params=params, headers=headers,
                                 data=data, timeout=timeout or self.http_timeout)

    def get(self, path: str, **kw: Any) -> requests.Response:
        return self.api("GET", path, **kw)

    def post(self, path: str, json: Any = None, **kw: Any) -> requests.Response:
        return self.api("POST", path, json=json, **kw)

    def api_json(self, method: str, path: str, json: Any = None, expect: int | tuple[int, ...] = 200, **kw: Any) -> Any:
        r = self.api(method, path, json, **kw)
        ok = (expect,) if isinstance(expect, int) else expect
        if r.status_code not in ok:
            raise StackError(f"{method} {path} -> {r.status_code}, expected {ok}: {r.text[:500]}")
        return r.json()

    # convenience ---------------------------------------------------------------------------
    def connect_all(self) -> list[dict[str, Any]]:
        return self.api_json("POST", "/api/instruments/connect", {"id": "all"})["instruments"]

    def disconnect_all(self) -> list[dict[str, Any]]:
        return self.api_json("POST", "/api/instruments/disconnect", {"id": "all"})["instruments"]

    def instruments(self) -> dict[str, dict[str, Any]]:
        return {i["id"]: i for i in self.api_json("GET", "/api/instruments")["instruments"]}

    def command(self, instrument: str, command: str, expect: int | tuple[int, ...] = 200) -> Any:
        return self.api_json("POST", "/api/instruments/command", {"id": instrument, "command": command}, expect)

    def start_run(self, sequence_id: str, parameters: Optional[dict[str, Any]] = None,
                  dut: Optional[dict[str, Any]] = None, retries: Optional[int] = None,
                  label: Optional[str] = None, expect: int | tuple[int, ...] = 202) -> Any:
        body: dict[str, Any] = {"sequence_id": sequence_id}
        if parameters is not None:
            body["parameters"] = parameters
        if dut is not None:
            body["dut"] = dut
        if retries is not None:
            body["retries"] = retries
        if label is not None:
            body["label"] = label
        out = self.api_json("POST", "/api/tests/run", body, expect)
        return out["run"] if "run" in out else out

    def run_status(self, run_id: Optional[str] = None, log_tail: int = 0) -> Optional[dict[str, Any]]:
        params: dict[str, Any] = {"log_tail": log_tail}
        if run_id:
            params["run_id"] = run_id
        return self.api_json("GET", "/api/tests/status", params=params)["run"]

    def wait_run(self, run_id: str, timeout: float = 60.0, poll: float = 0.05, log_tail: int = 500,
                 on_poll: Any = None) -> dict[str, Any]:
        """Poll until the run reaches a terminal status; returns the run detail."""
        deadline = time.monotonic() + timeout
        last: Optional[dict[str, Any]] = None
        while time.monotonic() < deadline:
            last = self.run_status(run_id, log_tail=log_tail)
            if on_poll:
                on_poll(last)
            if last and last["status"] in TERMINAL_STATES and last.get("finished_at"):
                return last
            time.sleep(poll)
        raise StackError(f"run {run_id} not finished within {timeout}s (last status: {last and last['status']})")

    def run_sequence(self, sequence_id: str, parameters: Optional[dict[str, Any]] = None,
                     dut: Optional[dict[str, Any]] = None, retries: Optional[int] = None,
                     label: Optional[str] = None, timeout: float = 60.0) -> dict[str, Any]:
        run = self.start_run(sequence_id, parameters, dut, retries, label)
        return self.wait_run(run["run_id"], timeout)

    def ensure_idle(self, timeout: float = 30.0) -> None:
        """Cancel an active run (if any) and wait until the backend reports none.

        Uses ``/api/tests/status`` (authoritative) rather than ``/api/health`` (cached up to 2 s).
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = self.api_json("GET", "/api/tests/status", params={"log_tail": 0})["run"]
            if not run or run["status"] in TERMINAL_STATES:
                return
            self.api("POST", "/api/tests/cancel", {"run_id": run["run_id"]})
            time.sleep(0.1)
        raise StackError("run did not stop after cancel")

    def all_results(self, **filters: Any) -> list[dict[str, Any]]:
        """All persisted tasks matching ``filters`` (paged, newest first)."""
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            body = self.api_json("GET", "/api/tests/results", params={"limit": 1000, "offset": offset, **filters})
            out.extend(body["results"])
            offset += len(body["results"])
            if not body["results"] or offset >= body["total"]:
                return out

    def all_runs(self, **filters: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            body = self.api_json("GET", "/api/tests/runs", params={"limit": 50, "offset": offset, **filters})
            out.extend(body["runs"])
            offset += len(body["runs"])
            if not body["runs"] or offset >= body["total"]:
                return out

    def logs_since(self, since_seq: int = 0, limit: int = 1000, **filters: Any) -> dict[str, Any]:
        return self.api_json("GET", "/api/logs", params={"limit": limit, "since_seq": since_seq, **filters})

    # ------------------------------------------------------------------ SCPI (direct to simulator)
    def scpi_client(self, instrument: str, timeout: float = 5.0) -> ScpiClient:
        return ScpiClient("127.0.0.1", self.sim_ports[instrument], timeout)

    def scpi(self, instrument: str, cmd: str, timeout: float = 5.0) -> Optional[str]:
        """One command over a fresh TCP connection directly to the simulator.

        Queries (``?``) return the response line; setters return ``None`` after a synchronising
        ``MF:FAULT?`` (which, being a fault command, is never faulted and consumes no counters).
        """
        with self.scpi_client(instrument, timeout) as c:
            if cmd.rstrip().endswith("?"):
                return c.query(cmd)
            c.write(cmd)
            c.query("MF:FAULT?")
            return None

    def scpi_errors(self, instrument: str, limit: int = 50) -> list[str]:
        """Drain the instrument's error queue (over a private connection)."""
        out: list[str] = []
        with self.scpi_client(instrument) as c:
            for _ in range(limit):
                line = c.query("SYST:ERR?")
                if line.startswith("0,"):
                    break
                out.append(line)
        return out

    def reset_simulator_state(self) -> None:
        """``*RST`` + ``*CLS`` + ``MF:FAULT:CLEAR`` on every instrument (direct)."""
        for iid in INSTRUMENT_IDS:
            with self.scpi_client(iid) as c:
                c.write("MF:FAULT:CLEAR")
                c.write("*RST")
                c.write("*CLS")
                c.query("MF:FAULT?")

    def proc_stats(self) -> dict[str, Any]:
        pid = self.backend_pid
        return proc_stats(pid) if pid else {"pid": None, "rss_kb": None, "fds": None, "threads": None}

    def versions(self) -> dict[str, Any]:
        v: dict[str, Any] = {"python": platform.python_version(), "platform": platform.platform()}
        try:
            h = self.api_json("GET", "/api/health")
            v["backend"] = h.get("software", {}).get("backend") or h.get("version")
            v["simulator_reported_by_backend"] = h.get("software", {}).get("simulator")
            v["config_version"] = h.get("software", {}).get("config_version")
        except Exception as exc:  # noqa: BLE001
            v["backend_error"] = str(exc)
        try:
            v["simulator"] = self.scpi("siggen", "MF:SIM:VERS?")
        except Exception as exc:  # noqa: BLE001
            v["simulator_error"] = str(exc)
        return v

    def describe(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "backend_port": self.backend_port,
            "sim_ports": self.sim_ports,
            "instrument_ports_used_by_backend": self.instrument_ports,
            "seed": self.seed,
            "workdir": str(self.workdir),
        }


# --------------------------------------------------------------------------------------------
# --serve mode (Playwright)
# --------------------------------------------------------------------------------------------
def _serve(args: argparse.Namespace) -> int:
    backend = Path(args.backend) if args.backend else None
    stack = Stack(Path(args.root), backend, seed=args.seed, name="e2e", backend_port=args.backend_port,
                  sim_base_port=args.sim_base_port, keep=False)
    stack.start()
    control_port = args.control_port or free_port_block(1)

    def state() -> dict[str, Any]:
        return {**stack.describe(), "control_port": control_port,
                "backend_alive": stack.backend_pid is not None,
                "simulator_alive": bool(stack.sim_proc and stack.sim_proc.poll() is None),
                "results_dir": str(stack.results_dir)}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:  # silence
            pass

        def _send(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/state"):
                self._send(200, state())
            else:
                self._send(404, {"error": "unknown"})

        def do_POST(self) -> None:  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            try:
                path = self.path.split("?")[0]
                if path == "/reset":
                    stack.reset(args.seed)
                elif path == "/backend/stop":
                    stack.stop_backend()
                elif path == "/backend/start":
                    stack.start_backend()
                elif path == "/backend/restart":
                    stack.restart_backend()
                elif path == "/backend/kill":
                    stack.kill_backend()
                elif path == "/simulator/stop":
                    stack.stop_simulator()
                elif path == "/simulator/kill":
                    stack.kill_simulator()
                elif path in ("/simulator/start", "/simulator/restart"):
                    if path.endswith("restart"):
                        stack.stop_simulator()
                    stack._wait_ports_free()
                    stack.start_simulator()
                else:
                    self._send(404, {"error": "unknown"})
                    return
                self._send(200, state())
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"error": str(exc)})

    httpd = ThreadingHTTPServer(("127.0.0.1", control_port), Handler)
    httpd.daemon_threads = True
    stop = threading.Event()

    def on_signal(*_: Any) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    if args.print_url:
        print("MFSTACK " + json.dumps({"url": stack.base_url, "control": f"http://127.0.0.1:{control_port}",
                                       "sim_ports": stack.sim_ports}), flush=True)
    try:
        while not stop.wait(0.5):
            pass
    finally:
        httpd.shutdown()
        stack.stop()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serve", action="store_true", help="start a stack and serve a control API until SIGTERM")
    ap.add_argument("--print-url", action="store_true", help="print one MFSTACK json line when ready")
    ap.add_argument("--root", default=str(REPO_ROOT))
    ap.add_argument("--backend", default=None, help="backend binary (default backend/build/measureflow_backend)")
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--backend-port", type=int, default=None)
    ap.add_argument("--sim-base-port", type=int, default=None)
    ap.add_argument("--control-port", type=int, default=None)
    args = ap.parse_args(argv)
    if not args.serve:
        ap.error("only --serve is supported on the command line")
    return _serve(args)


if __name__ == "__main__":
    raise SystemExit(main())
