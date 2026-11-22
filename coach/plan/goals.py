"""Règles pures des objectifs : blocs et courses rapprochées, fin de cycle, classification d'un changement."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from coach.plan.models import Goal

MIN_GAP_DAYS = 14  # en deçà, deux blocs non-Plaisir forment un groupe rapproché
BLOCK_MAX_GAP_DAYS = 2  # jusque-là, deux courses forment un bloc (week-end défi)

ChangeKind = Literal["close", "draft", "regenerate", "shrink", "adjust", "horizon"]


def goal_label(goal: Goal) -> str:
    """Libellé court d'un objectif, distance au format français."""
    distance = f"{goal.distance_km:g}".replace(".", ",")
    prefix = "Trail" if goal.type == "trail" else "Course sur route"
    return f"{prefix} de {distance} km"


def one_line(text: str) -> str:
    """Texte sur une seule ligne (retours à la ligne et espaces répétés réduits à une espace), pour les prompts."""
    return " ".join(text.split())


def cycle_end(goals: list[Goal]) -> date | None:
    """Fin du cycle : bloc du premier Principal, ou bloc affûté de son groupe rapproché s'il est plus
    tardif ; sans Principal, fin du dernier bloc."""
    if not goals:
        return None
    first = next((g for g in sorted(goals, key=lambda g: g.race_date) if g.priority == "principal"), None)
    if first is None:
        return race_blocks(goals)[-1].end
    p = next(p for g, p in _placements(goals) if g is first)
    return p.tapered.end if p.role == "integre" else p.block.end


def classify_change(
    *, plan_accepted: bool, old_end: date, new_end: date | None, touched_in_cycle: bool
) -> ChangeKind:
    """Nature du changement d'objectif sur le cycle courant."""
    if new_end is None:
        return "close"
    if new_end != old_end:
        if not plan_accepted:
            return "draft"
        return "regenerate" if new_end > old_end else "shrink"
    if touched_in_cycle:
        return "draft" if not plan_accepted else "adjust"
    return "horizon"


# --- blocs et courses rapprochées ---------------------------------------------------------------

Role = Literal["affute", "integre", "rebond"]
_RANK = {"principal": 3, "secondaire": 2, "plaisir": 1}


def goal_key(goal: Goal) -> int:
    """Clé d'un objectif : son id, 0 pour un objectif pas encore enregistré (comme `NEW_GOAL_ID`)."""
    return goal.id if goal.id is not None else 0


def _dated(goal: Goal) -> str:
    return f"{goal_label(goal)} ({goal.race_date:%d/%m})"


@dataclass(frozen=True, eq=False)
class RaceBlock:
    """Courses enchaînées (au plus `BLOCK_MAX_GAP_DAYS` jours entre deux), préparées comme un seul défi."""

    goals: tuple[Goal, ...]  # triés par date

    @property
    def start(self) -> date:
        return self.goals[0].race_date

    @property
    def end(self) -> date:
        return self.goals[-1].race_date

    @property
    def priority(self) -> str:
        return max((g.priority for g in self.goals), key=_RANK.__getitem__)

    @property
    def distance_km(self) -> float:
        return sum(g.distance_km for g in self.goals)

    @property
    def d_plus_m(self) -> int:
        return sum(g.d_plus_m for g in self.goals)


@dataclass(frozen=True, eq=False)
class Proximity:
    """Place d'un objectif : son bloc, et dans un groupe rapproché son rôle et le bloc affûté."""

    block: RaceBlock
    role: Role | None
    tapered: RaceBlock | None
    group: tuple[RaceBlock, ...]


def race_blocks(goals: Iterable[Goal]) -> list[RaceBlock]:
    """Blocs des objectifs (archivés ignorés), triés par date."""
    ordered = sorted((g for g in goals if g.status != "archived"), key=lambda g: g.race_date)
    chunks: list[list[Goal]] = []
    for g in ordered:
        if chunks and (g.race_date - chunks[-1][-1].race_date).days <= BLOCK_MAX_GAP_DAYS:
            chunks[-1].append(g)
        else:
            chunks.append([g])
    return [RaceBlock(tuple(c)) for c in chunks]


def _groups(blocks: list[RaceBlock]) -> list[list[RaceBlock]]:
    """Groupes rapprochés : blocs non-Plaisir à moins de `MIN_GAP_DAYS` jours de proche en proche."""
    groups: list[list[RaceBlock]] = []
    for b in (b for b in blocks if b.priority != "plaisir"):
        if groups and (b.start - groups[-1][-1].end).days < MIN_GAP_DAYS:
            groups[-1].append(b)
        else:
            groups.append([b])
    return groups


def proximity(goals: Iterable[Goal]) -> dict[int, Proximity]:
    """Bloc, rôle et bloc affûté de chaque objectif (clé `goal_key`).

    Dans un groupe rapproché, le bloc affûté est le plus prioritaire, à égalité le plus tardif ;
    ceux d'avant sont intégrés à son affûtage, ceux d'après sont des courses de rebond.
    """
    return {goal_key(g): p for g, p in _placements(goals)}


def _placements(goals: Iterable[Goal]) -> list[tuple[Goal, Proximity]]:
    """`proximity` par objectif, sans clé : sûr même avec plusieurs objectifs sans id."""
    blocks = race_blocks(goals)
    roles: dict[int, tuple[Role, RaceBlock, tuple[RaceBlock, ...]]] = {}
    for group in _groups(blocks):
        if len(group) < 2:
            continue
        tapered = max(reversed(group), key=lambda b: _RANK[b.priority])  # égalité : le plus tardif
        members = tuple(group)
        for b in group:
            role: Role = "affute" if b is tapered else "integre" if b.end < tapered.start else "rebond"
            roles[id(b)] = (role, tapered, members)
    result: list[tuple[Goal, Proximity]] = []
    for b in blocks:
        role, tapered, members = roles.get(id(b), (None, None, (b,)))
        p = Proximity(block=b, role=role, tapered=tapered, group=members)
        result += [(g, p) for g in b.goals]
    return result


def block_label(block: RaceBlock) -> str:
    """« Trail de 20 km (27/03) + Trail de 30 km (28/03) »."""
    return " + ".join(_dated(g) for g in block.goals)


def proximity_label(goal: Goal, prox: dict[int, Proximity]) -> str | None:
    """Libellé court sous l'objectif (« Bloc avec … », « Intégré à l'affûtage de … »), None s'il est isolé."""
    p = prox.get(goal_key(goal))
    if p is None:
        return None
    parts: list[str] = []
    others = [x for x in p.block.goals if goal_key(x) != goal_key(goal)]
    if others:
        parts.append("Bloc avec " + " + ".join(_dated(x) for x in others))
    if p.role == "integre":
        parts.append(f"Intégré à l'affûtage de {block_label(p.tapered)}")
    elif p.role == "rebond":
        parts.append(f"Course de rebond après {block_label(p.tapered)}")
    elif p.role == "affute":
        parts.append("Affûté (courses rapprochées)")
    return " · ".join(parts) or None


def _join_and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " et " + items[-1]


def proximity_notice(goal: Goal, prox: dict[int, Proximity]) -> str | None:
    """Avertissement après l'ajout ou la modification d'un objectif d'un bloc ou d'un groupe rapproché."""
    p = prox.get(goal_key(goal))
    if p is None:
        return None
    sentences: list[str] = []
    if len(p.block.goals) > 1:
        sentences.append(f"{block_label(p.block)} seront préparés comme un seul bloc.")
    if p.role is not None:
        text = (
            f"{_join_and([block_label(b) for b in p.group])} sont à moins de {MIN_GAP_DAYS} jours : "
            f"{block_label(p.tapered)} sera affûté"
        )
        for b in p.group:
            if b is p.tapered:
                continue
            fate = "sera intégré à son affûtage" if b.end < p.tapered.start else "sera une course de rebond"
            text += f" ; {block_label(b)} {fate}"
        sentences.append(text + ".")
    return " ".join(sentences) or None
