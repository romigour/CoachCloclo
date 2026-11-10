"""Client Garmin réel (python-garminconnect 0.3.x, sans garth).

Seul module qui parle à Garmin Connect. Tout appel passe par `_call`, qui
traduit les exceptions de la bibliothèque et fait une seule nouvelle tentative
après 5 s sur un 429. Le parsing est défensif : une donnée absente vaut None.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Literal

from coach.certs import install_system_ca
from coach.config import data_dir

# Avant l'import de garminconnect : curl_cffi lit ses certificats à l'import.
install_system_ca(data_dir())

from garminconnect import (  # noqa: E402
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

from coach.garmin.port import (  # noqa: E402
    ActivitySummary,
    GarminAuthRequired,
    GarminRateLimited,
    GarminUnavailable,
    LapSummary,
    Metrics,
    PersonalRecordSummary,
)

RETRY_DELAY_S = 5
PACE_MIN_S_KM, PACE_MAX_S_KM = 150, 600
# `wktStepIndex` (tour Garmin) -> `stepOrder` du workout : stepOrder = index + base.
# PROVISOIRE : base 1 supposée, non confirmée sur une activité réelle ; à vérifier
# avec le test live `test_activity_splits_capture` avant de s'y fier.
_STEP_INDEX_BASE = 1
# typeId Garmin des records personnels de course -> `PersonalRecordSummary.kind`
PR_KINDS: dict[int, str] = {
    1: "1k",
    2: "1mile",
    3: "5k",
    4: "10k",
    5: "half",
    6: "marathon",
    7: "longest_run",
}


class _NotFound(GarminUnavailable):
    """Ressource absente (404) : une métrique non calculée vaut None."""


def _num(v: Any) -> float | None:
    """Nombre fini, sinon None (booléens, chaînes, NaN et infinis exclus)."""
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    n = float(v)
    return n if math.isfinite(n) else None


def _int(v: Any) -> int | None:
    n = _num(v)
    return None if n is None else round(n)


def _first_dict(v: Any) -> dict:
    """La bibliothèque renvoie tantôt un dict, tantôt une liste de dicts."""
    if isinstance(v, list):
        v = next((x for x in reversed(v) if isinstance(x, dict)), {})
    return v if isinstance(v, dict) else {}


def _pace_s_km(speed: Any) -> int | None:
    """Allure (s/km) depuis la vitesse du seuil lactique.

    Garmin (latestLactateThreshold) exprime cette vitesse en dizaines de m/s
    (ex. 0.35 pour 3,5 m/s) ; toute valeur < 1 est donc multipliée par 10
    (< 1 m/s serait de la marche, pas un seuil). À confirmer sur capture réelle.
    """
    s = _num(speed)
    if s is None or s <= 0:
        return None
    if s < 1:
        s *= 10
    pace = round(1000 / s)
    # Garde de plausibilité (2:30 à 10:00 /km) : hors plage, unité probablement fausse.
    return pace if PACE_MIN_S_KM <= pace <= PACE_MAX_S_KM else None


def _running_zones(zones: Any) -> dict:
    if not isinstance(zones, list):
        return {}
    entries = [z for z in zones if isinstance(z, dict)]
    for sport in ("RUNNING", "DEFAULT"):
        for z in entries:
            if str(z.get("sport", "")).upper() == sport:
                return z
    return entries[0] if entries else {}


def _lap(raw: Any, index: int) -> LapSummary | None:
    """Tour Garmin normalisé ; ignoré s'il n'a pas de durée numérique."""
    if not isinstance(raw, dict):
        return None
    duration = _num(raw.get("duration"))
    if duration is None:
        return None
    speed = _num(raw.get("averageSpeed"))
    step_index = _int(raw.get("wktStepIndex"))
    return LapSummary(
        index=index,
        duration_s=duration,
        distance_m=_num(raw.get("distance")) or 0.0,
        avg_hr=_int(raw.get("averageHR")),
        max_hr=_int(raw.get("maxHR")),
        avg_pace_s_km=1000 / speed if speed is not None and speed > 0 else None,
        step_order=None if step_index is None else step_index + _STEP_INDEX_BASE,
        raw=raw,
    )


def _summary(a: Any) -> ActivitySummary | None:
    """Convertit une activité Garmin brute ; None si elle est inexploitable."""
    if not isinstance(a, dict):
        return None
    gid = _int(a.get("activityId"))
    try:
        d = date.fromisoformat(str(a.get("startTimeLocal", ""))[:10])
    except ValueError:
        return None
    if gid is None:
        return None
    atype = a.get("activityType")
    return ActivitySummary(
        garmin_id=gid,
        date=d,
        type_key=(atype.get("typeKey") if isinstance(atype, dict) else None) or "unknown",
        duration_s=_int(a.get("duration")) or 0,
        distance_m=_int(a.get("distance")) or 0,
        d_plus_m=_int(a.get("elevationGain")),
        avg_hr=_int(a.get("averageHR")),
        raw=a,
    )


def _map_login_errors(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except GarminConnectAuthenticationError as e:
        raise GarminAuthRequired("Connexion Garmin refusée ou expirée") from e
    except GarminConnectTooManyRequestsError as e:
        raise GarminRateLimited("Garmin limite les connexions, réessaie plus tard") from e
    except GarminConnectConnectionError as e:
        raise GarminUnavailable(f"Garmin injoignable : {e}") from e


class GarminClient:
    def __init__(self, api: Any, *, sleep: Callable[[float], None] = time.sleep):
        self._api = api
        self._sleep = sleep

    # --- authentification -------------------------------------------------

    @classmethod
    def from_tokens(cls, tokenstore: Path) -> GarminClient:
        api = Garmin()
        _map_login_errors(lambda: api.login(str(tokenstore)))
        return cls(api)

    @classmethod
    def start_login(
        cls, email: str, password: str, tokenstore: Path
    ) -> tuple[Literal["ok", "needs_mfa"], GarminClient | dict]:
        """Démarre la connexion. Le `state` MFA est à garder côté serveur.

        Les identifiants saisis priment : `login()` reçoit volontairement aucun
        tokenstore, sinon la bibliothèque réutiliserait les tokens enregistrés
        (périmés ou d'un autre compte) sans jamais essayer le mot de passe.
        """
        api = Garmin(email, password, return_on_mfa=True)
        status, state = _map_login_errors(api.login)
        if status == "needs_mfa":
            return "needs_mfa", state
        # En mode return_on_mfa, la bibliothèque ne persiste pas les tokens et
        # ne charge pas le profil : on persiste, puis on recharge proprement.
        _map_login_errors(lambda: api.client.dump(str(tokenstore)))
        return "ok", cls.from_tokens(tokenstore)

    @classmethod
    def finish_login(cls, state: dict, code: str, tokenstore: Path) -> GarminClient:
        api = Garmin()

        def go() -> None:
            api.resume_login(state, code)
            api.client.dump(str(tokenstore))

        _map_login_errors(go)
        return cls(api)

    # --- appel unique avec traduction d'erreurs ---------------------------

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        for attempt in (1, 2):
            try:
                return fn(*args, **kwargs)
            except GarminConnectTooManyRequestsError as e:
                if attempt == 1:
                    self._sleep(RETRY_DELAY_S)
                    continue
                raise GarminRateLimited("Garmin limite les requêtes, réessaie plus tard") from e
            except GarminConnectAuthenticationError as e:
                raise GarminAuthRequired("Connexion Garmin expirée") from e
            except GarminConnectNotFoundError as e:
                raise _NotFound(f"Ressource Garmin introuvable : {e}") from e
            except GarminConnectConnectionError as e:
                raise GarminUnavailable(f"Garmin indisponible : {e}") from e

    def _optional(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return self._call(fn, *args, **kwargs)
        except _NotFound:
            return None

    # --- lecture ----------------------------------------------------------

    def today(self) -> date:
        fn = getattr(self._api, "today", None)
        if fn is None:
            return date.today()
        return date.fromisoformat(fn().isoformat())

    def metrics(self) -> Metrics:
        api = self._api
        day = self.today().isoformat()
        max_metrics = _first_dict(self._optional(api.get_max_metrics_latest))
        lactate = self._optional(api.get_lactate_threshold, latest=True)
        hr = self._optional(api.get_heart_rates, day)
        zones = _running_zones(self._optional(api.get_heart_rate_zones_v2))
        preds = _first_dict(self._optional(api.get_race_predictions))

        lt = _first_dict(lactate.get("speed_and_heart_rate")) if isinstance(lactate, dict) else {}
        hr = hr if isinstance(hr, dict) else {}
        floors = [_int(zones.get(f"zone{i}Floor")) for i in range(1, 6)]
        return Metrics(
            vo2max=_num(_first_dict(max_metrics.get("generic")).get("vo2MaxPreciseValue")),
            # FC max : réglage utilisateur (zones) sinon max du jour (moins fiable).
            hr_max=_int(zones.get("maxHeartRateUsed")) or _int(hr.get("maxHeartRate")),
            hr_rest=_int(hr.get("restingHeartRate")),
            threshold_hr=_int(lt.get("heartRate")),
            threshold_pace_s_km=_pace_s_km(lt.get("speed")),
            pred_5k_s=_int(preds.get("time5K")),
            pred_10k_s=_int(preds.get("time10K")),
            pred_half_s=_int(preds.get("timeHalfMarathon")),
            pred_marathon_s=_int(preds.get("timeMarathon")),
            hr_zones=floors if all(f is not None for f in floors) else None,
        )

    def activities(self, start: date, end: date) -> list[ActivitySummary]:
        raw = self._call(self._api.get_activities_by_date, start.isoformat(), end.isoformat())
        return [x for x in map(_summary, raw if isinstance(raw, list) else []) if x]

    def activities_page(self, offset: int, limit: int) -> list[ActivitySummary]:
        """Historique paginé, du plus récent au plus ancien ([] en fin d'historique)."""
        raw = self._call(self._api.get_activities, offset, limit)
        return [x for x in map(_summary, raw if isinstance(raw, list) else []) if x]

    def activity_laps(self, garmin_id: int) -> list[LapSummary]:
        """Tours d'une activité ; `step_order` n'est renseigné que pour un workout."""
        raw = self._call(self._api.get_activity_splits, str(garmin_id))
        dtos = raw.get("lapDTOs") if isinstance(raw, dict) else None
        laps = (_lap(x, 0) for x in (dtos if isinstance(dtos, list) else []))
        kept = [lap for lap in laps if lap]
        # `index` = rang du tour conservé
        return [lap.model_copy(update={"index": i}) for i, lap in enumerate(kept)]

    def personal_records(self) -> list[PersonalRecordSummary]:
        """Records personnels de course ; les types inconnus sont ignorés."""
        raw = self._call(self._api.get_personal_record)
        out: list[PersonalRecordSummary] = []
        for r in raw if isinstance(raw, list) else []:
            if not isinstance(r, dict):
                continue
            kind = PR_KINDS.get(_int(r.get("typeId")))
            value = _num(r.get("value"))
            if kind is None or value is None:
                continue
            d = None
            for key in ("prStartTimeGmtFormatted", "actStartDateTimeInGMTFormatted"):
                try:
                    d = date.fromisoformat(str(r.get(key, ""))[:10])
                    break
                except ValueError:
                    continue
            out.append(
                PersonalRecordSummary(
                    kind=kind,
                    value=value,
                    garmin_activity_id=_int(r.get("activityId")),
                    date=d,
                )
            )
        return out

    # --- écriture ---------------------------------------------------------

    @staticmethod
    def _id(resp: Any, *keys: str) -> int:
        found = None
        if isinstance(resp, dict):
            found = next((_int(resp[k]) for k in keys if _int(resp.get(k))), None)
        if found is None:
            raise GarminUnavailable("Réponse Garmin inattendue (identifiant absent)")
        return found

    def upload_workout(self, workout: dict) -> int:
        """Renvoie le `workoutId` de la réponse."""
        return self._id(self._call(self._api.upload_workout, workout), "workoutId")

    def schedule(self, workout_id: int, d: date) -> int:
        """Renvoie `workoutScheduleId` (repli : `scheduledWorkoutId`, `id`)."""
        resp = self._call(self._api.schedule_workout, workout_id, d.isoformat())
        return self._id(resp, "workoutScheduleId", "scheduledWorkoutId", "id")

    def reschedule(self, schedule_id: int, d: date) -> None:
        self._call(self._api.reschedule_workout, schedule_id, d.isoformat())

    def unschedule(self, schedule_id: int) -> None:
        try:
            self._call(self._api.unschedule_workout, schedule_id)
        except _NotFound:
            pass  # déjà retiré

    def delete_workout(self, workout_id: int) -> None:
        try:
            self._call(self._api.delete_workout, workout_id)
        except _NotFound:
            pass  # déjà supprimé
