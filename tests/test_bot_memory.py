"""Tests for modules/ai/bot_memory.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from modules.ai.bot_memory import BotMemory  # noqa: E402


@pytest.fixture
def mem(tmp_path):
    return BotMemory(store_path=tmp_path / "mem.json")


def test_add_and_get_all(mem):
    e = mem.add("BTC-EUR DCA werkt slecht in bear markets", user_id="bot",
                metadata={"category": "lesson", "market": "BTC-EUR"})
    assert e["id"]
    assert e["text"].startswith("BTC-EUR DCA")
    all_ = mem.get_all("bot")
    assert len(all_) == 1
    assert all_[0]["metadata"]["market"] == "BTC-EUR"


def test_dedup_on_near_identical(mem):
    mem.add("MIN_SCORE_TO_BUY blijft 7.0 — gebruiker wil dit niet verlagen",
            user_id="bot", metadata={"category": "config"})
    mem.add("MIN_SCORE_TO_BUY blijft 7.0 — gebruiker wil dit niet verlagen.",
            user_id="bot", metadata={"category": "config"})
    assert len(mem.get_all("bot")) == 1


def test_search_token_overlap(mem):
    mem.add("Trailing stops kappen winners af in trends", user_id="bot")
    mem.add("DCA bij 4% drop levert beste resultaat op SOL en ARB", user_id="bot")
    mem.add("Bandit allocator schakelt active arm uit bij negatieve Sharpe", user_id="bot")
    res = mem.search("trailing stops trend", user_id="bot", limit=3)
    assert len(res) >= 1
    assert "trailing" in res[0]["text"].lower()


def test_search_filters_category(mem):
    mem.add("BASE 60 EUR werkt beter dan 80 EUR op €1500 portfolio",
            user_id="bot", metadata={"category": "config"})
    mem.add("BTC laat lower-low zien op 4h chart", user_id="bot",
            metadata={"category": "market"})
    res_cfg = mem.search("BASE EUR portfolio", user_id="bot", category="config")
    res_mkt = mem.search("BASE EUR portfolio", user_id="bot", category="market")
    assert len(res_cfg) == 1
    assert len(res_mkt) == 0


def test_update_and_delete(mem):
    e = mem.add("draft text", user_id="bot")
    assert mem.update(e["id"], "final text", user_id="bot")
    assert mem.get(e["id"], user_id="bot")["text"] == "final text"
    assert mem.delete(e["id"], user_id="bot")
    assert mem.get(e["id"], user_id="bot") is None


def test_persistence(tmp_path):
    p = tmp_path / "persist.json"
    m1 = BotMemory(store_path=p)
    m1.add("persist this fact", user_id="bot")
    m2 = BotMemory(store_path=p)  # fresh instance, same file
    assert len(m2.get_all("bot")) == 1
    assert m2.get_all("bot")[0]["text"] == "persist this fact"


def test_stats(mem):
    mem.add("a", user_id="bot", metadata={"category": "lesson"})
    mem.add("b", user_id="bot", metadata={"category": "lesson"})
    mem.add("c", user_id="bot", metadata={"category": "trade"})
    s = mem.stats()
    assert s["total_memories"] == 3
    assert s["by_category"]["lesson"] == 2
    assert s["by_category"]["trade"] == 1
