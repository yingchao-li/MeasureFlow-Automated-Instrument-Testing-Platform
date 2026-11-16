"""Shared pytest fixtures: private simulator/backend stacks on free ports.

* ``sim`` (module scope)    - simulator only, no backend needed.
* ``stack`` (module scope)  - simulator + backend with short client timeouts (fast failure tests).
* ``pstack`` (module scope) - like ``stack`` but with the fault-injecting proxy between backend and simulator.
* ``make_stack`` (function) - factory for stacks with custom overrides.

Soft state (active run, fault injections, instrument connections, proxy rules) is reset before every
test that uses a stack; history on disk is *not* wiped between tests of one module, so tests filter
by ``run_id`` / ``label`` instead of assuming an empty history.
Missing prerequisites (backend binary, simulator) cause an explicit ``pytest.skip``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "experiments", ROOT / "simulator", ROOT / "tests" / "api"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from stack import Stack, StackError  # noqa: E402  (after sys.path setup)

BACKEND_ENV = "MF_BACKEND"

# Client timeouts used by the shared stacks: short, so failure-path tests stay fast
# (the production defaults of configs/instruments.json are 1000/2000/1000 ms with 2 retries).
FAST_OVERRIDES: dict[str, dict[str, Any]] = {
    "siggen": {"timeout_ms": 500, "max_retries": 1},
    "analyzer": {"timeout_ms": 500, "max_retries": 1},
    "dut": {"timeout_ms": 500, "max_retries": 1},
}


def _backend_path() -> Path:
    return Path(os.environ.get(BACKEND_ENV) or ROOT / "backend" / "build" / "measureflow_backend")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def backend_bin() -> Path:
    p = _backend_path()
    if not p.is_file():
        pytest.skip(f"backend binary not built: {p} (run scripts/build.sh or set {BACKEND_ENV})")
    return p


@pytest.fixture(scope="session")
def sim_available() -> None:
    if not (ROOT / "simulator" / "mfsim" / "__main__.py").is_file():
        pytest.skip("simulator package missing: simulator/mfsim/__main__.py")


@pytest.fixture(scope="session")
def truth(sim_available: None) -> Any:
    """``mfsim.truth`` - the simulator's analytic expectation module."""
    try:
        import mfsim.truth as t  # type: ignore
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"mfsim.truth not importable: {exc}")
    return t


def _reset_soft_state(st: Stack) -> None:
    if st.with_backend:
        st.ensure_idle()
    if st.proxy:
        st.proxy.reset()
    if st.sim_proc is None or st.sim_proc.poll() is not None:
        st.start_simulator()
    st.reset_simulator_state()
    if st.with_backend:
        if st.backend_pid is None:
            st.start_backend()
        try:
            st.disconnect_all()
            # a connect override (host/port) is remembered by the backend for later plain connects - restore the endpoint
            for iid, port in st.instrument_ports.items():
                cur = st.instruments().get(iid, {})
                if cur and (cur.get("host") != "127.0.0.1" or cur.get("port") != port):
                    st.api("POST", "/api/instruments/connect", {"id": iid, "host": "127.0.0.1", "port": port})
            st.disconnect_all()
        except StackError:
            pass


@pytest.fixture(autouse=True)
def _isolation(request: pytest.FixtureRequest) -> Iterator[None]:
    """Reset soft state of whichever stack fixtures the test uses."""
    for name in ("sim", "stack", "pstack"):
        if name in request.fixturenames:
            _reset_soft_state(request.getfixturevalue(name))
    yield


@pytest.fixture(scope="module")
def sim(sim_available: None) -> Iterator[Stack]:
    st = Stack(ROOT, None, seed=12345, with_backend=False, name="qa-sim")
    st.start()
    try:
        yield st
    finally:
        st.stop()


@pytest.fixture(scope="module")
def stack(backend_bin: Path, sim_available: None) -> Iterator[Stack]:
    st = Stack(ROOT, backend_bin, seed=12345, overrides=FAST_OVERRIDES, name="qa-stack")
    st.start()
    try:
        yield st
    finally:
        st.stop()


@pytest.fixture(scope="module")
def pstack(backend_bin: Path, sim_available: None) -> Iterator[Stack]:
    st = Stack(ROOT, backend_bin, seed=12345, with_proxy=True, overrides=FAST_OVERRIDES, name="qa-pstack")
    st.start()
    try:
        yield st
    finally:
        st.stop()


@pytest.fixture
def make_stack(backend_bin: Path, sim_available: None) -> Iterator[Callable[..., Stack]]:
    created: list[Stack] = []

    def factory(**kw: Any) -> Stack:
        kw.setdefault("name", "qa-custom")
        st = Stack(ROOT, kw.pop("backend", backend_bin), **kw)
        created.append(st)
        st.start()
        return st

    try:
        yield factory
    finally:
        for st in created:
            st.stop()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Iterator[None]:
    """On failure attach the tails of backend/simulator logs of every stack the test used."""
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed:
        for name in ("sim", "stack", "pstack"):
            st = getattr(item, "funcargs", {}).get(name)
            if isinstance(st, Stack):
                for which in ("backend", "simulator"):
                    txt = st.log_text(which, 25)
                    if txt:
                        rep.sections.append((f"{name}: {which}.log (tail)", txt))
