import re

import pytest

from morpheus_vlt.protocols.vdai import VDAISimulator

# The reader's stats request. It ends in a line feed, which is what the simulator waits for.
STATS_REQUEST = b"\x05\x1b\x53\x31\x32\x33\x34\x35\x36\x37\x38\x6c\x47\x53\x20\x20\x43\x20\x20\x0a"

# Everything below is lifted from oblivion's lib/protocol/vdai.py. Don't tidy it up: the point is
# to parse exactly the way the reader does, warts included.
REX = {
    "b": rb"^(TOTAL PARTIDAS|PUNTOS| +\d+,\d+ =)",
    "a": rb"(EU|.*: +[0-9]+\.*[0-9]+$)",
    "m": rb"^( < EU| +\d+$)",
}

METERS_TABLE = ["coin_in", "bill_in", "tot_in", "coin_out", "bill_out", "tot_out", "plays", "play", "win"]

COUNTERS_TABLE_M = [
    "play", "win", "plays",
    "in_h_2e", "in_h_1e", "in_h_20c", "in_h_10c", "in_h_50e", "in_h_20e", "in_h_10e", "in_h_5e",
    "in_s_2e", "in_s_1e", "in_s_50c", "in_s_20c", "in_s_10c", "in_s_50e", "in_s_20e", "in_s_10e", "in_s_5e",
    "in_50e", "in_20e", "in_10e", "in_5e", "in_2e", "in_1e", "in_50c", "in_20c", "in_10c",
    "out_2e", "out_1e", "out_20c", "out_10c", "out_50e", "out_20e", "out_10e", "out_5e",
    "ts",
]

COUNTERS_TABLE_A = [
    "in_h_10c", "in_h_20c", "in_h_50c", "in_h_1e", "in_h_2e", "in_h_5e", "in_h_10e", "in_h_20e", "in_h_50e",
    "in_s_10c", "in_s_20c", "in_s_50c", "in_s_1e", "in_s_2e", "in_s_5e", "in_s_10e", "in_s_20e", "in_s_50e",
    "in_10c", "in_20c", "in_50c", "in_1e", "in_2e", "in_5e", "in_10e", "in_20e", "in_50e",
    "out_10c", "out_20c", "out_50c", "out_1e", "out_2e", "out_5e", "out_10e", "out_20e", "out_50e",
    "plays", "play", "win",
    "ts",
]

COUNTERS_TABLE_B = COUNTERS_TABLE_M[3:20] + [COUNTERS_TABLE_M[2]] + COUNTERS_TABLE_M[:2] + COUNTERS_TABLE_M[20:]


def _kept(page: bytes, flavor: str) -> list[bytes]:
    return list(filter(lambda x: re.match(REX[flavor], x), page.split(b"\n")))


def reader_parse_generic(page: bytes) -> tuple[dict, list]:
    meters = [
        float(x[0])
        for x in [
            list(map(lambda x: float(x.decode("utf-8")), re.findall(rb"(\d+\.\d+|[^\.]\d+$)", x)))  # noqa: C417
            for x in _kept(page, "m")
        ]
    ]
    if len(meters) >= 13:
        base_meters, plays_meter, extra_meters = [13, 14, 12], 12, [0, 1, 4, 5, 6, 10, 12, 13, 14]
    else:
        base_meters, plays_meter, extra_meters = [9, 10, 8], 8, [0, 1, 2, 3, 4, 6, 8, 9, 10]
    counters = [meters[i] for i in base_meters]
    meters = [int(meters[i] * 100) if i != plays_meter else int(meters[i]) for i in extra_meters]
    counters[0] = int(counters[0] * 100)
    counters[1] = int(counters[1] * 100)
    counters[2] = int(counters[2])
    counters = counters + [0] * 34
    return dict(zip(METERS_TABLE, meters)), counters


def reader_parse_anniversario(page: bytes) -> tuple[dict, dict]:
    counters = [
        int((float(x[0].decode("utf-8")) * 100) * int(x[1].decode("utf-8"))) if len(x) == 2
        else int(x[0].replace(b".", b""))
        for x in [re.findall(rb"([0-9]+\.[0-9]+|[0-9]+)", x) for x in _kept(page, "a")]
    ]
    meters = counters[6:12] + counters[43:46]
    counters = [0] * 9 + counters[14:19] + counters[20:24] + counters[24:33] + counters[33:42] + counters[43:46]
    return dict(zip(METERS_TABLE, meters)), dict(zip(COUNTERS_TABLE_A, counters))


def reader_parse_bally(page: bytes) -> tuple[dict, dict]:
    counters = [
        int(float(x[1].decode("utf-8").replace(",", ".")) / float(x[0].decode("utf-8").replace(",", ".")))
        if len(x) == 2
        else int(x[0])
        for x in [re.findall(rb"(\d+[,.]\d+|[^,.]\d+)", x) for x in _kept(page, "b")]
    ]
    del counters[-8:-4]
    del counters[-8:-4]
    cnt = dict(zip(COUNTERS_TABLE_B, counters))
    meters = [
        cnt["in_10c"] * 10 + cnt["in_20c"] * 20 + cnt["in_50c"] * 50 + cnt["in_1e"] * 100 + cnt["in_2e"] * 200,
        cnt["in_5e"] * 500 + cnt["in_10e"] * 1000 + cnt["in_20e"] * 2000 + cnt["in_50e"] * 5000,
    ]
    meters += [meters[0] + meters[1]]
    meters += [cnt["out_10c"] * 10 + cnt["out_20c"] * 20 + cnt["out_1e"] * 100 + cnt["out_2e"] * 200]
    meters += [cnt["out_5e"] * 500 + cnt["out_10e"] * 1000 + cnt["out_20e"] * 2000 + cnt["out_50e"] * 5000]
    meters += [meters[3] + meters[4]]
    meters += [cnt["plays"], cnt["play"], cnt["win"]]
    return dict(zip(METERS_TABLE, meters)), cnt


def _sim(flavor: str, **meters: int) -> VDAISimulator:
    sim = VDAISimulator()
    sim.protocol_type = flavor
    for name, value in meters.items():
        sim.state.set_meter(name, value)
    return sim


def test_generic_page_round_trips_through_reader() -> None:
    sim = _sim("m", coin_in=12345, bill_in=50000, coin_out=6700, bill_out=2000, plays=77, play=100000, win=95000)

    meters, counters = reader_parse_generic(sim.handle(STATS_REQUEST))

    assert meters == {
        "coin_in": 12345, "bill_in": 50000, "tot_in": 62345,
        "coin_out": 6700, "bill_out": 2000, "tot_out": 8700,
        "plays": 77, "play": 100000, "win": 95000,
    }
    assert counters[:3] == [100000, 95000, 77]
    assert len(counters) + 1 == len(COUNTERS_TABLE_M)  # the reader appends the timestamp


def test_generic_page_with_single_digit_values_still_parses() -> None:
    sim = _sim("m", coin_in=5, plays=3)

    meters, _ = reader_parse_generic(sim.handle(STATS_REQUEST))

    assert meters["coin_in"] == 5
    assert meters["plays"] == 3


def test_anniversario_page_round_trips_through_reader() -> None:
    denominations = {name: idx for idx, name in enumerate(COUNTERS_TABLE_A[9:36], start=1)}
    sim = _sim(
        "a", coin_in=12345, bill_in=50000, coin_out=6789, bill_out=0, plays=3, play=1999, win=29, **denominations
    )

    meters, counters = reader_parse_anniversario(sim.handle(STATS_REQUEST))

    assert meters == {
        "coin_in": 12345, "bill_in": 50000, "tot_in": 62345,
        "coin_out": 6789, "bill_out": 0, "tot_out": 6789,
        "plays": 3, "play": 1999, "win": 29,
    }
    for name, value in denominations.items():
        assert counters[name] == value, name
    assert all(counters[name] == 0 for name in COUNTERS_TABLE_A[:9])  # the reader zeroes in_h_*


def test_bally_page_round_trips_through_reader() -> None:
    denominations = [name for name in COUNTERS_TABLE_B[:37] if name not in ("plays", "play", "win")]
    counts = {name: idx for idx, name in enumerate(denominations, start=1)}
    sim = _sim("b", plays=4321, play=98765, win=87654, **counts)

    meters, cnt = reader_parse_bally(sim.handle(STATS_REQUEST))

    for name, value in counts.items():
        assert cnt[name] == value, name
    assert (cnt["plays"], cnt["play"], cnt["win"]) == (4321, 98765, 87654)
    assert meters["coin_in"] == (
        counts["in_10c"] * 10 + counts["in_20c"] * 20 + counts["in_50c"] * 50
        + counts["in_1e"] * 100 + counts["in_2e"] * 200
    )
    assert meters["plays"] == 4321


def test_bally_page_with_zero_counts_does_not_trip_the_division() -> None:
    meters, cnt = reader_parse_bally(_sim("b").handle(STATS_REQUEST))

    assert set(meters.values()) == {0}
    assert set(cnt.values()) == {0}


@pytest.mark.parametrize("flavor", ["m", "a", "b"])
def test_idle_line_gets_silence(flavor: str) -> None:
    assert _sim(flavor).handle(b"") == b""


def test_partial_request_waits_for_the_line_feed() -> None:
    sim = _sim("m")

    assert sim.handle(STATS_REQUEST[:7]) == b""
    page = sim.handle(STATS_REQUEST[7:])

    assert page.startswith(b"STATISTICS\n")
    assert page.count(b"STATISTICS") == 1


def test_two_requests_in_one_read_get_two_pages() -> None:
    page = _sim("m").handle(STATS_REQUEST * 2)

    assert page.count(b"STATISTICS") == 2


def test_noise_without_a_line_feed_gets_dropped() -> None:
    sim = _sim("m")

    assert sim.handle(b"x" * 300) == b""
    assert sim.handle(b"\n").count(b"STATISTICS") == 1
    assert sim._rx == bytearray()
