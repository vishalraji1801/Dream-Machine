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
