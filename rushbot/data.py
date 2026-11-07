"""Public statlocker datasets, cached on disk and indexed for puzzle solving.

Every value the Rush generator compares comes from one of these endpoints; the
resolver maps puzzle families onto these fields.
"""
from __future__ import annotations

import json
import os
import re
import threading

from .api import Client

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
_LOCK = threading.Lock()

_ENDPOINTS = {
    "heroes_full": "/api/info/heroes-full",
    "items_full": "/api/info/items-full",
    "abilities_catalog": "/api/abilities/catalog",
    "item_usage_catalog": "/api/item-usage/catalog",
    "hero_stats": "/api/info/get-hero-stats/0/0/1",
    "hero_lane_stats": "/api/info/get-hero-lane-stats",
    "misc_entities": "/api/map/misc-entities",
    "difficulty": "/api/heroes/difficulty-ratings",
    "ability_order": "/api/info/hero-ability-order-stats?minRank=0",
}

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def parse_num(v):
    """'25 %' -> 25.0, '4' -> 4.0, None -> None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = _NUM.search(v)
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return None
    return None


def _cache_path(name):
    return os.path.join(CACHE, name + ".json")


def _fetch(name, client):
    d = client.request(_ENDPOINTS[name])
    with _LOCK:
        os.makedirs(CACHE, exist_ok=True)
        with open(_cache_path(name), "w", encoding="utf8") as f:
            json.dump(d, f)
    return d


class Data:
    """Lazy view over the cached datasets."""

    def __init__(self, client: Client | None = None, refresh: bool = False):
        self.client = client or Client()
        self.refresh = refresh
        self._mem = {}
        self._hero_usage = {}
        self._hero_games = {}
        self._pooled_total_games = None

    # ------------------------------------------------------------------ raw
    def raw(self, name):
        if name in self._mem:
            return self._mem[name]
        path = _cache_path(name)
        data = None
        if not self.refresh:
            try:
                with open(path, encoding="utf8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = None
        if data is None:
            data = _fetch(name, self.client)
        self._mem[name] = data
        return data

    # ------------------------------------------------------------- entities
    @property
    def hero(self) -> dict:
        if "hero" not in self._mem:
            self._mem["hero"] = {h["id"]: h for h in self.raw("heroes_full")}
        return self._mem["hero"]

    @property
    def item(self) -> dict:
        if "item" not in self._mem:
            self._mem["item"] = {i["id"]: i for i in self.raw("items_full")}
        return self._mem["item"]

    @property
    def ability(self) -> dict:
        if "ability" not in self._mem:
            self._mem["ability"] = {a["abilityId"]: a
                                    for a in self.raw("abilities_catalog")["abilities"]}
        return self._mem["ability"]

    @property
    def usage(self) -> dict:
        if "usage" not in self._mem:
            self._mem["usage"] = {i["itemId"]: i
                                  for i in self.raw("item_usage_catalog")["items"]}
        return self._mem["usage"]

    @property
    def hero_stats(self) -> dict:
        if "hero_stats" not in self._mem:
            self._mem["hero_stats"] = {h["hero_id"]: h for h in self.raw("hero_stats")}
        return self._mem["hero_stats"]

    @property
    def lane(self) -> dict:
        if "lane" not in self._mem:
            self._mem["lane"] = {h["hero_id"]: h for h in self.raw("hero_lane_stats")}
        return self._mem["lane"]

    @property
    def misc(self) -> dict:
        if "misc" not in self._mem:
            self._mem["misc"] = {e.get("id"): e for e in self.raw("misc_entities")}
        return self._mem["misc"]

    @property
    def ability_order(self) -> dict:
        if "ability_order" not in self._mem:
            raw = self.raw("ability_order") or {}
            self._mem["ability_order"] = {int(k): v for k, v in raw.items()}
        return self._mem["ability_order"]

    @property
    def hero_slug(self) -> dict:
        """hero id -> class slug used in ability image paths (hero_spectre -> spectre)."""
        if "hero_slug" not in self._mem:
            m = {}
            for hid, h in self.hero.items():
                card = ((h.get("images") or {}).get("icon_hero_card_webp")
                        or (h.get("images") or {}).get("icon_hero_card") or "")
                base = card.rsplit("/", 1)[-1].split(".")[0]
                slug = base[:-5] if base.endswith("_card") else base
                if not slug:
                    cn = h.get("class_name") or ""
                    slug = cn.split("_", 1)[1] if cn.startswith("hero_") else cn
                m[hid] = slug
            self._mem["hero_slug"] = m
        return self._mem["hero_slug"]

    @property
    def icon_to_ability(self) -> dict:
        """Ability icon basename -> abilityId (icons live in items_full asset urls)."""
        if "icon_ability" not in self._mem:
            m = {}
            for it in self.raw("items_full"):
                for key in ("image", "image_webp", "shop_image", "shop_image_webp"):
                    u = it.get(key)
                    if u:
                        m.setdefault(u.rsplit("/", 1)[-1].split(".")[0].lower(), it["id"])
            self._mem["icon_ability"] = m
        return self._mem["icon_ability"]

    def ability_slot_for_image(self, image_url: str):
        """(abilityKey, heroId) for an ability icon, or None."""
        base = (image_url or "").rsplit("/", 1)[-1].split(".")[0].lower()
        aid = self.icon_to_ability.get(base)
        a = self.ability.get(aid) if aid else None
        if not a:
            return None
        return a.get("abilityKey"), a.get("heroId")

    def ability_key_for_image(self, image_url: str):
        """Resolve an ability icon to its kit slot via class-name suffix match."""
        if "ability_keys" not in self._mem:
            m = {}
            for a in self.ability.values():
                cn = (a.get("className") or "").lower()
                if not cn:
                    continue
                m.setdefault(cn, []).append(a)
            self._mem["ability_keys"] = m
        base = (image_url or "").rsplit("/", 1)[-1].split(".")[0].lower()
        if not base:
            return None
        for cn, rows in self._mem["ability_keys"].items():
            if cn.endswith(base):
                return rows[0].get("abilityKey")
        return None

    def hero_id_by_name(self, name: str):
        want = (name or "").strip().lower()
        for hid, h in self.hero.items():
            if (h.get("name") or "").strip().lower() == want:
                return hid
        return None

    @property
    def difficulty(self) -> dict:
        if "difficulty" not in self._mem:
            raw = self.raw("difficulty")
            self._mem["difficulty"] = {int(k): float(v) for k, v in raw.items()}
        return self._mem["difficulty"]

    # --------------------------------------------------------------- derived
    def hero_usage(self, hero_id: int) -> dict:
        """Per-hero item usage: {itemId: {games, winRate, figures}} (cached on disk)."""
        if hero_id in self._hero_usage:
            return self._hero_usage[hero_id]
        path = os.path.join(CACHE, f"usage_hero_{hero_id}.json")
        data = None
        if not self.refresh:
            try:
                with open(path, encoding="utf8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = None
        if data is None:
            data = self.client.request(f"/api/item-usage/catalog?heroId={hero_id}")
            os.makedirs(CACHE, exist_ok=True)
            with open(path, "w", encoding="utf8") as f:
                json.dump(data, f)
        idx = {i["itemId"]: i for i in data.get("items", [])}
        self._hero_usage[hero_id] = idx
        self._hero_games[hero_id] = {
            x.get("heroId"): x.get("games") for x in data.get("heroes") or []
        }.get(hero_id)
        return idx

    def hero_total(self, hero_id: int):
        """Total games for a hero in the item-usage sample (buy-rate denominator)."""
        self.hero_usage(hero_id)  # ensure loaded/cached
        return self._hero_games.get(hero_id)

    def hero_usage_top(self, hero_id: int) -> dict:
        """Per-hero item usage restricted to the top ranks (minTier=9)."""
        if "top" not in self._mem:
            self._mem["top"] = {}
        cache = self._mem["top"]
        if hero_id in cache:
            return cache[hero_id]
        path = os.path.join(CACHE, f"usage_hero_top_{hero_id}.json")
        data = None
        if not self.refresh:
            try:
                with open(path, encoding="utf8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = None
        if data is None:
            data = self.client.request(
                f"/api/item-usage/catalog?heroId={hero_id}&minTier=9&maxTier=11")
            os.makedirs(CACHE, exist_ok=True)
            with open(path, "w", encoding="utf8") as f:
                json.dump(data, f)
        idx = {i["itemId"]: i for i in data.get("items", [])}
        hero_games = {x["heroId"]: x["games"] for x in data.get("heroes") or []}.get(hero_id)
        cache[hero_id] = (idx, hero_games)
        return cache[hero_id]

    def rank_cdf(self) -> dict:
        """badge id -> % of ranked players at or below that badge."""
        if "rank_cdf" in self._mem:
            return self._mem["rank_cdf"]
        path = os.path.join(CACHE, "rank_cdf.json")
        data = None
        if not self.refresh:
            try:
                with open(path, encoding="utf8") as f:
                    data = {int(k): v for k, v in json.load(f).items()}
            except (OSError, ValueError):
                data = None
        if data is None:
            raw = self.client.request("/api/info/rank-migration") or {}
            counts = {}
            for cell in raw.get("cells") or []:
                counts[int(cell.get("newRank", 0))] = counts.get(int(cell.get("newRank", 0)), 0) + int(cell.get("accounts", 0))
            total = sum(counts.values()) or 1
            data, acc = {}, 0
            for badge in sorted(counts):
                acc += counts[badge]
                data[badge] = 100.0 * acc / total
            os.makedirs(CACHE, exist_ok=True)
            with open(path, "w", encoding="utf8") as f:
                json.dump({str(k): v for k, v in data.items()}, f)
        self._mem["rank_cdf"] = data
        return data

    def hero_wpa(self, hero_id: int) -> dict:
        """Per-hero WPA table: {itemName: {mean_wpa, mean_purchase_time_min, cost}}."""
        if "wpa" not in self._mem:
            self._mem["wpa"] = {}
        cache = self._mem["wpa"]
        if hero_id in cache:
            return cache[hero_id]
        hero = self.hero.get(hero_id) or {}
        name = (hero.get("name") or "").replace(" ", "_").replace("&", "and")
        path = os.path.join(CACHE, f"wpa_hero_{hero_id}.json")
        data = None
        if not self.refresh:
            try:
                with open(path, encoding="utf8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = None
        if data is None:
            data = self.client.request(f"/api/info/wpa-homepage-data?hero={name}")
            os.makedirs(CACHE, exist_ok=True)
            with open(path, "w", encoding="utf8") as f:
                json.dump(data, f)
        idx = {}
        for row in data.get("items") or []:
            idx[row.get("item")] = row
        cache[hero_id] = idx
        return idx

    def item_spread(self, item_id: int) -> dict:
        """Per-item distribution table: {figureKey: dist{dict}}."""
        if "spread" not in self._mem:
            self._mem["spread"] = {}
        cache = self._mem["spread"]
        if item_id in cache:
            return cache[item_id]
        path = os.path.join(CACHE, f"spread_item_{item_id}.json")
        data = None
        if not self.refresh:
            try:
                with open(path, encoding="utf8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = None
        if data is None:
            data = self.client.request(f"/api/item-usage/{item_id}")
            os.makedirs(CACHE, exist_ok=True)
            with open(path, "w", encoding="utf8") as f:
                json.dump(data, f)
        idx = {f["key"]: (f.get("dist") or {}) for f in (data.get("figures") or [])}
        cache[item_id] = idx
        return idx

    def total_hero_games(self) -> float:
        """Team-games denominator for pick rate (12 heroes per match)."""
        if self._pooled_total_games is None:
            total = sum(h["matches"] for h in self.hero_stats.values())
            self._pooled_total_games = total / 12.0
        return self._pooled_total_games

    def item_prop(self, item_id: int, label: str | None = None,
                  key: str | None = None):
        it = self.item.get(int(item_id))
        if not it:
            return None
        props = it.get("properties") or {}
        if key and key in props:
            v = parse_num(props[key].get("value"))
            if v is not None:
                return v
        if label:
            want = label.strip().lower()
            found = []
            for k, p in props.items():
                if (p.get("label") or "").strip().lower() != want:
                    continue
                v = parse_num(p.get("value"))
                if v is not None:
                    found.append(v)
            if not found:
                return None
            # several stats can share one label (WeaponPower vs BaseAttackDamagePercent);
            # the generator reports the first non-zero one
            for v in found:
                if v:
                    return v
            return found[0]
        return None

    def item_by_slot_cost(self, slot: str | None, tier: int | None,
                          cost: float | None, exclude=()) -> list:
        out = []
        for i in self.item.values():
            if slot and i.get("item_slot_type") != slot:
                continue
            if tier is not None and i.get("item_tier") != tier:
                continue
            if cost is not None and parse_num(i.get("cost")) != cost:
                continue
            if i.get("shopable") is False or i.get("disabled"):
                continue
            if i["id"] in exclude:
                continue
            out.append(i)
        return out
