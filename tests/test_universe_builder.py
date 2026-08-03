from unittest.mock import MagicMock

from src.universe_builder import UniverseBuilder, filter_universe


def _inst(sym, itype="EQ", exch="NSE", token=1):
    return {"tradingsymbol": sym, "instrument_token": token,
            "instrument_type": itype, "exchange": exch, "segment": "NSE"}


def test_keeps_only_equity():
    insts = [_inst("RELIANCE"), _inst("NIFTY26JULFUT", itype="FUT"),
             _inst("RELIANCE26JUL2500CE", itype="CE")]
    out = filter_universe(insts, {}, {})
    assert [r["symbol"] for r in out] == ["RELIANCE"]


def test_price_band_filter():
    insts = [_inst("CHEAP"), _inst("MID"), _inst("PRICEY")]
    ltp = {"CHEAP": 50, "MID": 1500, "PRICEY": 9000}
    out = filter_universe(insts, ltp, {"price_min": 100, "price_max": 5000})
    assert [r["symbol"] for r in out] == ["MID"]


def test_fno_whitelist_intersection():
    insts = [_inst("RELIANCE"), _inst("TINYSTOCK")]
    out = filter_universe(insts, {}, {"fno_underlyings": ["RELIANCE"]})
    assert [r["symbol"] for r in out] == ["RELIANCE"]


def test_fno_only_uses_derived_underlyings():
    # fno_only (default) keeps only names in the derived F&O set.
    insts = [_inst("RELIANCE"), _inst("ILLIQUID")]
    out = filter_universe(insts, {}, {"fno_only": True},
                          fno_underlyings={"RELIANCE"})
    assert [r["symbol"] for r in out] == ["RELIANCE"]


def test_fno_only_false_keeps_all_equity_in_band():
    # fno_only off -> every EQ in the price band survives (no liquidity gate).
    insts = [_inst("RELIANCE"), _inst("ILLIQUID")]
    out = filter_universe(insts, {"RELIANCE": 2800, "ILLIQUID": 300},
                          {"fno_only": False, "price_min": 100, "price_max": 5000},
                          fno_underlyings={"RELIANCE"})
    assert {r["symbol"] for r in out} == {"RELIANCE", "ILLIQUID"}


def test_build_derives_fno_from_nfo(tmp_path):
    cfg = {"trading": {"exchange": "NSE"}, "universe": {"fno_only": True}}
    kite = MagicMock()
    nse = [_inst("RELIANCE", token=738561), _inst("ILLIQUID", token=999)]
    nfo = [{"tradingsymbol": "RELIANCE26JULFUT", "instrument_type": "FUT",
            "name": "RELIANCE"}]
    kite.instruments.side_effect = lambda seg: nse if seg == "NSE" else nfo
    kite.ltp.return_value = {"NSE:RELIANCE": {"last_price": 2800.0},
                             "NSE:ILLIQUID": {"last_price": 300.0}}
    ub = UniverseBuilder(cfg, cache_dir=str(tmp_path))
    universe = ub.build(kite)
    assert {r["symbol"] for r in universe} == {"RELIANCE"}  # ILLIQUID has no F&O


def test_build_chunks_ltp_requests_at_200(monkeypatch):
    # kite.ltp() is a GET with one query param per symbol; >200 in one call risks a
    # 414 URI-too-large from the server. 450 symbols -> 3 chunks (200/200/50).
    monkeypatch.setattr("src.universe_builder.time.sleep", lambda s: None)
    cfg = {"trading": {"exchange": "NSE"}, "universe": {"fno_only": False}}
    kite = MagicMock()
    nse = [_inst(f"SYM{i}", token=i) for i in range(450)]
    kite.instruments.side_effect = lambda seg: nse if seg == "NSE" else []
    seen_chunk_sizes = []

    def _ltp(chunk):
        seen_chunk_sizes.append(len(chunk))
        return {s: {"last_price": 500.0} for s in chunk}
    kite.ltp.side_effect = _ltp
    ub = UniverseBuilder(cfg, cache_dir="ignored")
    ub._write = lambda universe: None          # skip disk I/O for this assertion
    ub.build(kite)
    assert seen_chunk_sizes == [200, 200, 50]
    assert all(n <= 200 for n in seen_chunk_sizes)


def test_build_throttles_between_chunks(monkeypatch):
    # ~10 chunks fired back-to-back with no delay trips Kite's per-second rate limit
    # (429) - a failure mode the smaller 200-chunk size introduced. Verify a pause
    # happens BETWEEN chunks (not before the first).
    sleeps = []
    monkeypatch.setattr("src.universe_builder.time.sleep", lambda s: sleeps.append(s))
    cfg = {"trading": {"exchange": "NSE"}, "universe": {"fno_only": False}}
    kite = MagicMock()
    nse = [_inst(f"SYM{i}", token=i) for i in range(450)]      # 3 chunks
    kite.instruments.side_effect = lambda seg: nse if seg == "NSE" else []
    kite.ltp.side_effect = lambda chunk: {s: {"last_price": 500.0} for s in chunk}
    ub = UniverseBuilder(cfg, cache_dir="ignored")
    ub._write = lambda universe: None
    ub.build(kite)
    assert len(sleeps) == 2                    # between chunk 1->2 and 2->3, not before chunk 1
    assert all(s > 0 for s in sleeps)


def test_build_retries_a_rate_limited_chunk_and_recovers(tmp_path, monkeypatch):
    # a transient 429 on a chunk is retried once after a backoff; a recovery on retry
    # must NOT be treated as a loss - all of that chunk's symbols get priced.
    monkeypatch.setattr("src.universe_builder.time.sleep", lambda s: None)
    cfg = {"trading": {"exchange": "NSE"}, "universe": {"fno_only": False,
                                                         "price_min": 100, "price_max": 5000}}
    kite = MagicMock()
    nse = [_inst(f"SYM{i}", token=i) for i in range(50)]       # 1 chunk
    kite.instruments.side_effect = lambda seg: nse if seg == "NSE" else []
    calls = {"n": 0}

    def _ltp(chunk):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("429 Too Many Requests")           # transient
        return {f"NSE:{s.split(':')[1]}": {"last_price": 500.0} for s in chunk}
    kite.ltp.side_effect = _ltp
    ub = UniverseBuilder(cfg, cache_dir=str(tmp_path))
    universe = ub.build(kite)
    assert calls["n"] == 2                     # failed once, retried, recovered
    assert len(universe) == 50                  # every symbol priced via the retry


def test_build_one_bad_ltp_chunk_does_not_lose_the_rest(tmp_path, monkeypatch):
    # a chunk that fails BOTH attempts must not blank out the price band for OTHER
    # chunks - only that chunk's prices are skipped; its symbols still pass unfiltered.
    monkeypatch.setattr("src.universe_builder.time.sleep", lambda s: None)
    cfg = {"trading": {"exchange": "NSE"}, "universe": {"fno_only": False,
                                                         "price_min": 100, "price_max": 5000}}
    kite = MagicMock()
    nse = [_inst(f"SYM{i}", token=i) for i in range(250)]   # 2 chunks: 200 + 50
    kite.instruments.side_effect = lambda seg: nse if seg == "NSE" else []
    calls = {"n": 0}

    def _ltp(chunk):
        calls["n"] += 1
        if len(chunk) == 200:                  # the first chunk fails persistently
            raise Exception("429 Too Many Requests")
        return {f"NSE:{s.split(':')[1]}": {"last_price": 500.0} for s in chunk}
    kite.ltp.side_effect = _ltp
    ub = UniverseBuilder(cfg, cache_dir=str(tmp_path))
    universe = ub.build(kite)                  # must not raise
    assert calls["n"] == 3                     # chunk1: 2 attempts (both fail) + chunk2: 1 (ok)
    assert len(universe) == 250                # missing-ltp symbols (chunk1) still pass (unfiltered)


def test_explicit_exclusions():
    insts = [_inst("RELIANCE"), _inst("BANNED")]
    out = filter_universe(insts, {}, {"exclude": ["BANNED"]})
    assert [r["symbol"] for r in out] == ["RELIANCE"]


def test_missing_ltp_passes_price_band():
    insts = [_inst("RELIANCE")]
    out = filter_universe(insts, {}, {"price_min": 100, "price_max": 5000})
    assert len(out) == 1  # no LTP -> not filtered on price


def test_build_writes_and_loads_roundtrip(tmp_path):
    cfg = {"trading": {"exchange": "NSE"}, "universe": {"fno_underlyings": ["RELIANCE", "TCS"]}}
    kite = MagicMock()
    kite.instruments.return_value = [_inst("RELIANCE", token=738561),
                                     _inst("TCS", token=2953217),
                                     _inst("SMALLCAP", token=999)]
    kite.ltp.return_value = {
        "NSE:RELIANCE": {"last_price": 2800.0},
        "NSE:TCS": {"last_price": 3500.0},
        "NSE:SMALLCAP": {"last_price": 40.0},
    }
    ub = UniverseBuilder(cfg, cache_dir=str(tmp_path))
    universe = ub.build(kite)
    syms = {r["symbol"] for r in universe}
    assert syms == {"RELIANCE", "TCS"}          # SMALLCAP excluded by fno whitelist
    loaded = ub.load_today()
    assert {r["symbol"] for r in loaded} == {"RELIANCE", "TCS"}
    assert isinstance(loaded[0]["token"], int)


def test_load_today_none_when_absent(tmp_path):
    ub = UniverseBuilder({"trading": {"exchange": "NSE"}}, cache_dir=str(tmp_path))
    assert ub.load_today() is None
