"""Map a puzzle family onto a numeric value per option, from public datasets.

Each rule receives (dataset, puzzle, option, context) and returns a float or
None. None means "unknown" — the caller then falls back to the learned store and
finally to a blind guess.
"""
from __future__ import annotations

import math
import re

from .data import Data, parse_num


# --------------------------------------------------------------------- helpers
def _get(obj, path, default=None):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
        if cur is None:
            return default
    return cur


def _ability(d: Data, opt, path, scale=1.0):
    a = d.ability.get(int(opt["entityId"]))
    if not a:
        return None
    v = _get(a, path)
    return None if v is None else scale * float(v)


def _hero_item(d: Data, opt, ctx, path, scale=1.0):
    hero = (ctx or {}).get("heroId")
    if hero is None:
        return None
    u = d.hero_usage(int(hero)).get(int(opt["entityId"]))
    if not u:
        return None
    v = _get(u, path)
    return None if v is None else scale * float(v)


def _hero_stat(d: Data, opt, stat):
    s = d.hero_stats.get(int(opt["entityId"]))
    if not s or not s.get("matches"):
        return None
    if stat == "winrate":
        return 100.0 * s["wins"] / s["matches"]
    key = "total_" + stat
    if key not in s:
        return None
    return s[key] / s["matches"]


def _lane(d: Data, opt, key):
    ln = d.lane.get(int(opt["entityId"]))
    if not ln or ln.get(key) is None:
        return None
    return float(ln[key])


# ----------------------------------------------------------------------- rules
def _item_static(d: Data, p, opt, ctx):
    label = (p.get("prompt") or {}).get("label")
    return d.item_prop(int(opt["entityId"]), label=label)


def _ability_damage_per_cast(d, p, opt, ctx):
    dmg = _ability(d, opt, "damage.mean")
    casts = _ability(d, opt, "casts.mean")
    if dmg is None or not casts:
        return None
    return dmg / casts


def _rank_percentile(d, p, opt, ctx):
    return d.rank_cdf().get(int(opt["entityId"]))


def _hero_pick_rate(d, p, opt, ctx):
    s = d.hero_stats.get(int(opt["entityId"]))
    if not s:
        return None
    return 100.0 * s["matches"] / d.total_hero_games()


def _hero_difficulty(d, p, opt, ctx):
    return d.difficulty.get(int(opt["entityId"]))


def _item_win_rate_hero(d, p, opt, ctx):
    return _hero_item(d, opt, ctx, "winRate", 100.0)


def _item_best_hero(d, p, opt, ctx):
    """Options are heroes; the item comes from the puzzle context."""
    item = (ctx or {}).get("itemId")
    if item is None:
        return None
    u = d.hero_usage(int(opt["entityId"])).get(int(item))
    return None if not u else 100.0 * u["winRate"]


def _item_impact_dpm(d, p, opt, ctx):
    v = _hero_item(d, opt, ctx, "figures.damage.mean")
    if v is not None:
        return v / 13.3          # per-game damage -> damage added per minute
    row = d.usage.get(int(opt["entityId"]))
    if not row:
        return None
    figs = row.get("figures") or {}
    for key in ("total_damage", "damage", "bonus"):
        f = figs.get(key) or {}
        if f.get("mean"):
            return f["mean"] / 13.3
    return None


def _ability_max_first(d, p, opt, ctx):
    """Share of games where this ability is maxed first, for the prompt's hero."""
    hero = (ctx or {}).get("heroId")
    a = d.ability.get(int(opt["entityId"]))
    if hero is None or not a:
        return None
    rows = d.ability_order.get(int(hero)) or []
    slot = a.get("abilityKey")
    for r in rows:
        if int(r.get("maxed_first_ability", -1)) == int(slot):
            tot = r.get("total_matches_sampled") or 0
            if tot:
                return 100.0 * float(r.get("match_count", 0)) / float(tot)
    return None


def _item_win_rate(d, p, opt, ctx):
    row = d.usage.get(int(opt["entityId"]))
    return None if not row else 100.0 * row["winRate"]


def _buy_rate(d, p, opt, ctx, top=False):
    """Approximate share of a hero's games that include the item.

    The generator's own number is computed on a narrower sample we cannot
    reproduce, but the ordering tracks this ratio closely.
    """
    item = (ctx or {}).get("itemId")
    hero = (ctx or {}).get("heroId")
    if item is not None and hero is None:      # options are heroes
        hid = int(opt["entityId"])
        idx, hero_games = d.hero_usage_top(hid) if top else (d.hero_usage(hid), None)
        if hero_games is None:
            hero_games = d.hero_total(hid) or (d.hero_stats.get(hid) or {}).get("matches")
        row = idx.get(int(item))
        if not row or not hero_games:
            return 0.0
        return 100.0 * row["games"] / hero_games
    if hero is not None:                        # options are items
        idx, hero_games = d.hero_usage_top(int(hero)) if top else (d.hero_usage(int(hero)), None)
        if hero_games is None:
            hero_games = d.hero_total(int(hero)) or (d.hero_stats.get(int(hero)) or {}).get("matches")
        row = idx.get(int(opt["entityId"]))
        if not row or not hero_games:
            return 0.0
        return 100.0 * row["games"] / hero_games
    return None


def _buy_rate_top(d, p, opt, ctx):
    return _buy_rate(d, p, opt, ctx, top=True)


def _wpa(d, p, opt, ctx):
    """Win-chance gained by buying the item, in percent (0.295 -> +0.3%)."""
    hero = (ctx or {}).get("heroId")
    if hero is None:
        return None
    row = d.hero_wpa(int(hero)).get(opt.get("name") or "")
    return None if not row else 100.0 * float(row["mean_wpa"])


def _wpa_buy_time(d, p, opt, ctx):
    hero = (ctx or {}).get("heroId")
    if hero is not None:
        row = d.hero_wpa(int(hero)).get(opt.get("name") or "")
        if row and row.get("mean_purchase_time_min") is not None:
            return float(row["mean_purchase_time_min"])
    dist = d.item_spread(int(opt["entityId"])).get("bought_s") or {}
    v = dist.get("p50")
    return None if v is None else float(v) / 60.0


# Coarse classes for non-hero units, used when no table has the exact number.
# Hero base health is 700-900; structures sit at 5.5k-6k. Heights: ~2.4m vs 12-14m.
UNIT_PRIORS = {"height": (2.45, 12.6), "health": (780.0, 5700.0), "souls": (150.0, 1600.0)}


STRUCTURE_WORDS = ("guardian", "walker", "shrine", "patron", "barrack")


def _unit_prior(d, p, opt, field):
    """Coarse prior, only for entities we can classify by name."""
    eid = int(opt["entityId"])
    hero_prior, struct_prior = UNIT_PRIORS[field]
    name = (opt.get("name") or "").lower()
    if eid in d.hero:
        return hero_prior
    if any(w in name for w in STRUCTURE_WORDS):
        return struct_prior
    return None


def _unit_health(d, p, opt, ctx):
    eid = int(opt["entityId"])
    h = d.hero.get(eid)
    if h:
        v = _get(h, "starting_stats.max_health.value")
        if v is not None:
            return float(v)
    ent = d.misc.get(eid)
    if ent and ent.get("health"):
        return float(ent["health"])
    return _unit_prior(d, p, opt, "health")


def _unit_height(d, p, opt, ctx):
    return _unit_prior(d, p, opt, "height")


def _unit_souls(d, p, opt, ctx):
    ent = d.misc.get(int(opt["entityId"]))
    if ent:
        for k in ("goldAmount", "goldPerMinuteAmount"):
            v = parse_num(ent.get(k))
            if v is not None:
                return v
    return _unit_prior(d, p, opt, "souls")


RULES = {
    # abilities ------------------------------------------------------------
    "ability_casts": lambda d, p, o, c: _ability(d, o, "casts.mean"),
    "ability_people_hit": lambda d, p, o, c: _ability(d, o, "enemiesPerCast.mean"),
    "ability_hit_rate": lambda d, p, o, c: _ability(d, o, "hitRatePooled", 100.0),
    "ability_damage_game": lambda d, p, o, c: _ability(d, o, "damage.mean"),
    "ability_damage_per_cast": _ability_damage_per_cast,
    "ability_debuff_time": lambda d, p, o, c: _ability(d, o, "debuffS.mean"),
    "ability_kills": lambda d, p, o, c: _ability(d, o, "kills.mean"),
    "ability_hit_range": lambda d, p, o, c: _ability(d, o, "distance.meanM"),
    "ability_max_first": _ability_max_first,
    # heroes ---------------------------------------------------------------
    "hero_win_rate": lambda d, p, o, c: _hero_stat(d, o, "winrate"),
    "hero_kills": lambda d, p, o, c: _hero_stat(d, o, "kills"),
    "hero_deaths": lambda d, p, o, c: _hero_stat(d, o, "deaths"),
    "hero_assists": lambda d, p, o, c: _hero_stat(d, o, "assists"),
    "hero_objective_damage": lambda d, p, o, c: _hero_stat(d, o, "boss_damage"),
    "hero_pick_rate": _hero_pick_rate,
    "hero_difficulty": _hero_difficulty,
    "est_rank_percentile": _rank_percentile,
    # lane -----------------------------------------------------------------
    "lane_souls": lambda d, p, o, c: _lane(d, o, "avg_net_worth"),
    "lane_denies": lambda d, p, o, c: _lane(d, o, "avg_denies"),
    "lane_win_rate": lambda d, p, o, c: _lane(d, o, "win_rate_percent"),
    "lane_creep_kills": lambda d, p, o, c: _lane(d, o, "avg_creep_kills"),
    "lane_draw_rate": lambda d, p, o, c: _lane(d, o, "draw_rate_percent"),
    "lane_loss_rate": lambda d, p, o, c: _lane(d, o, "loss_rate_percent"),
    # items ----------------------------------------------------------------
    "item_stat_compare": _item_static,
    "item_win_rate": _item_win_rate,
    "item_stat_pick": _item_static,
    "item_win_rate_hero": _item_win_rate_hero,
    "item_best_hero": _item_best_hero,
    "item_impact_dpm": _item_impact_dpm,
    "item_buy_time_hero": _wpa_buy_time,
    "est_item_buy_time": _wpa_buy_time,
    "item_wpa_hero": _wpa,
    "item_buy_rate_hero": _buy_rate,
    "top2_item_buy_rate_hero": _buy_rate_top,
    # units ----------------------------------------------------------------
    "unit_health": _unit_health,
    "unit_height": _unit_height,
    "scale_unit_height": _unit_height,
    "scale_unit_height": _unit_height,
    "unit_souls": _unit_souls,
}

# estimate-style families reuse the statistic behind their base family
ESTIMATE_ALIASES = {
    "est_ability_casts": "ability_casts",
    "est_ability_hit_rate": "ability_hit_rate",
    "est_ability_enemies_hit": "ability_people_hit",
    "est_ability_damage_game": "ability_damage_game",
    "est_ability_debuff_s": "ability_debuff_time",
    "est_ability_hit_distance": "ability_hit_range",
    "est_hero_assists": "hero_assists",
    "est_hero_kills": "hero_kills",
    "est_hero_deaths": "hero_deaths",
    "est_unit_health": "unit_health",
    "est_item_buy_rate_hero": "item_buy_rate_hero",
    "est_unit_height": "unit_height",
}


def family_rule(family: str):
    if family in RULES:
        return RULES[family]
    alias = ESTIMATE_ALIASES.get(family)
    return RULES.get(alias) if alias else None


def value_for(d: Data, puzzle: dict, opt: dict):
    fn = family_rule(puzzle.get("family", ""))
    if fn is None:
        return None
    try:
        v = fn(d, puzzle, opt, puzzle.get("context") or {})
    except (KeyError, TypeError, ValueError):
        return None
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def values_for(d: Data, puzzle: dict) -> dict:
    out = {}
    for opt in puzzle.get("options") or []:
        v = value_for(d, puzzle, opt)
        if v is not None:
            out[opt["id"]] = v
    return out
