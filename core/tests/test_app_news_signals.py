"""Owner 2026-10-31: "Tambah sumber data beritanya … termasuk data dari sentimen sosial media, google trend, tradingview, dll" — Google Trends,
Google News per topic, Reddit, Fear & Greed, CoinGecko, the economic calendar and a TradingView-style technical rating, read by the brain."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_app_wave1 import FakeClient, FakeResp
from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")
NOW = datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc)

TRENDS = """<?xml version="1.0"?><rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
<item><title>harga emas antam</title><ht:approx_traffic>20.000+</ht:approx_traffic>
  <ht:news_item><ht:news_item_title>Harga emas Antam turun Rp15.000</ht:news_item_title></ht:news_item></item>
<item><title>persib</title><ht:approx_traffic>50.000+</ht:approx_traffic></item><item><title></title></item></channel></rss>"""
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Emas turun terus, serok atau tunggu?</title><updated>2026-11-01T20:00:00+00:00</updated><link href="https://reddit.com/r/finansial/1"/>
  <category term="finansial" label="r/finansial"/></entry>
<entry><title>Post lama</title><updated>2026-10-20T20:00:00+00:00</updated><link href="https://reddit.com/x"/></entry></feed>"""
FNG = {"data": [{"value": "22", "value_classification": "Extreme Fear"}] + [{"value": "40", "value_classification": "Fear"}] * 6
       + [{"value": "61", "value_classification": "Greed"}]}
CAL = [{"title": "Non-Farm Employment Change", "country": "USD", "date": "2026-11-06T08:30:00-05:00", "impact": "High", "forecast": "150K", "previous": "180K"},
       {"title": "Retail Sales", "country": "AUD", "date": "2026-11-03T19:30:00-05:00", "impact": "High"},
       {"title": "BI Rate", "country": "IDR", "date": "2026-11-03T02:00:00-05:00", "impact": "Medium"},
       {"title": "CPI y/y", "country": "CNY", "date": "2026-10-20T21:30:00-04:00", "impact": "High"}]


def test_the_sources_are_read_into_plain_facts():
    from app import brief, signals
    tr = signals.parse_trends(TRENDS)
    assert tr == [{"q": "harga emas antam", "traffic": "20.000+", "news": ["Harga emas Antam turun Rp15.000"]}, {"q": "persib", "traffic": "50.000+", "news": []}]
    posts = signals.parse_atom(ATOM, "Reddit Indonesia", NOW)
    assert [p["title"] for p in posts] == ["Emas turun terus, serok atau tunggu?"] and posts[0]["summary"] == "r/finansial"   # the last day only
    assert signals.parse_fng(FNG) == {"value": 22, "label": "sangat takut", "week_ago": 61, "label_week_ago": "serakah"}
    assert signals.parse_fng({}) is None
    cal = signals.parse_calendar(CAL, NOW)
    assert [c["title"] for c in cal] == ["Non-Farm Employment Change"]                          # high impact, the economies that move his money, ahead
    assert brief.mix([[{"title": "A"}, {"title": "B"}], [{"title": "a!"}, {"title": "C"}], [{"title": "D"}]]) == [{"title": "A"}, {"title": "D"}, {"title": "B"}, {"title": "C"}]
    g = {"trends": tr, "mood": {"crypto_fng": signals.parse_fng(FNG), "coins": ["Bitcoin (BTC)"]}, "agenda": cal}
    text = brief.signal_lines(g)
    assert "Fear & Greed kripto: 22 (sangat takut); seminggu lalu 61 (serakah)" in text and "1. harga emas antam (20.000+ pencarian)" in text
    assert "Jum 6/11 20.30 USD Non-Farm Employment Change; perkiraan 150K; sebelumnya 180K" in text   # in WIB


def test_the_technical_rating_follows_the_tradingview_method():
    from app import signals
    up = [100 + i * 0.5 + (i % 3) * 0.2 for i in range(260)]
    down = list(reversed(up))
    t_up, t_down = signals.technicals(up), signals.technicals(down)
    assert t_up["ma"] == 1.0 and t_up["above_ma50"] and t_up["above_ma200"] and t_up["change_1m"] > 0
    assert t_down["ma"] == -1.0 and t_down["label"] in ("jual", "jual kuat") and t_down["rsi"] < 50
    assert t_up["rating"] > t_down["rating"] and signals.technicals([1, 2, None, 3]) is None   # too short: no rating
    words = signals.tech_words(t_down)
    assert words.startswith("rating teknikal jual") and "di bawah MA50" in words and signals.tech_words(None) == ""
    flat = signals.technicals([100.0] * 60)
    assert flat["label"] == "netral"


@needs_db
async def test_the_brain_reads_every_source_and_says_the_sentiment(pool, monkeypatch):
    from app import brief, gateway, hub, weather
    await pool.execute("TRUNCATE briefs, flow_runs, invest_snapshots RESTART IDENTITY CASCADE")
    monkeypatch.setattr(brief, "MAX_AGE_H", 10 ** 6)
    from app import signals
    monkeypatch.setattr(signals.asyncio, "sleep", _no_sleep)
    rss = """<rss><channel><item><title>{t}</title><link>https://n/{i}</link><pubDate>Mon, 02 Nov 2026 00:00:00 GMT</pubDate></item></channel></rss>"""
    closes = [100 + i * 0.4 for i in range(250)]
    monkeypatch.setattr(brief, "_client", lambda: FakeClient({
        "finance.yahoo.com": FakeResp({"chart": {"result": [{"indicators": {"quote": [{"close": closes}]}}]}}),
        "trends.google.com": FakeResp(None, TRENDS), "news.google.com": FakeResp(None, rss.format(t="Emas Antam turun", i=9)),
        "reddit.com": FakeResp(None, ATOM.replace("2026-11-01T20", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H"))),
        "alternative.me": FakeResp(FNG), "coingecko.com": FakeResp({"coins": [{"item": {"name": "Bitcoin", "symbol": "BTC"}}]}),
        "faireconomy.media": FakeResp([{**CAL[0], "date": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}]),
        "": FakeResp(None, rss.format(t="BI tahan bunga", i=1))}))

    async def no_weather():
        return ""
    monkeypatch.setattr(weather, "today_text", no_weather)
    seen = []

    async def fake(category, body, **kw):
        seen.append(body["messages"][1]["content"])
        return {"choices": [{"message": {"content": json.dumps({"judul": "Pasar takut", "situasi": "Emas turun.", "suasana": "waspada",
            "sentimen": {"label": "takut", "ringkas": "Publik cemas soal emas.", "sinyal": [{"sumber": "Google Trends", "isi": "pencarian harga emas 20.000+"}]},
            "tema": [{"judul": "Emas", "alasan": [{"isi": "dibahas di Reddit", "nomor": "SOSIAL 1"}]}]})}}]}
    monkeypatch.setattr(gateway, "complete", fake)
    hub.tap(lambda ev: _none())
    d = await brief.compose("owner")
    prompt = seen[0]
    for block in ("GOOGLE TRENDS INDONESIA", "SENTIMEN:", "Fear & Greed kripto: 22", "AGENDA EKONOMI", "[TOPIK]", "[SOSIAL]", "[PASAR]",
                  "rating teknikal beli", "Google News · harga emas", "Reddit Indonesia"):
        assert block in prompt, block
    assert d["sentimen"]["label"] == "takut" and d["sentimen"]["sinyal"][0]["sumber"] == "Google Trends"
    assert d["tema"][0]["alasan"][0]["link"] == "https://reddit.com/r/finansial/1"                  # a reason can point at what people said
    assert d["trends"][0]["q"] == "harga emas antam" and d["mood"]["crypto_fng"]["value"] == 22 and d["agenda"] and d["markets"][0]["tech"]["label"]
    srcs = (await brief.today())["sources"]
    assert {"Google Trends", "Fear & Greed", "CoinGecko", "Forex Factory", "Reddit Indonesia", "Google News"} <= set(srcs)


async def _no_sleep(*a, **k):
    return None


async def _none():
    return None
