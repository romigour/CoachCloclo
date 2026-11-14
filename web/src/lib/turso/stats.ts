// Ports de `get_stats_activities`, `get_stats_records` (coach/api/app.py) et `stat_row` (coach/stats/normalize.py).
import type { Family, PersonalRecord, RaceInfo, StatActivity } from "../api";
import type { Db } from "./db";

type Row = Record<string, unknown>;

const FAMILY_KEYS: Record<Exclude<Family, "other">, string[]> = {
  run: ["running", "treadmill_running", "track_running", "street_running", "indoor_running", "virtual_run"],
  trail: ["trail_running", "ultra_run"],
  bike: ["cycling", "road_biking", "mountain_biking", "gravel_cycling", "indoor_cycling", "virtual_ride", "e_bike_fitness"],
  swim: ["lap_swimming", "open_water_swimming", "swimming"],
  strength: ["strength_training", "indoor_cardio", "hiit", "yoga", "pilates"],
  walk: ["walking", "hiking", "casual_walking"],
};
const FAMILIES = new Map<string, Family>(
  Object.entries(FAMILY_KEYS).flatMap(([f, keys]) => keys.map((k) => [k, f as Family] as const)),
);

// Champs bruts extraits en SQL (jamais raw_json entier) : valeur + type JSON, seulement si raw_json est un objet valide.
const OBJ = "json_valid(raw_json) AND json_type(raw_json) = 'object'";
const field = (alias: string, path: string) =>
  `CASE WHEN ${OBJ} THEN json_extract(raw_json, '${path}') END AS ${alias}, ` +
  `CASE WHEN ${OBJ} THEN json_type(raw_json, '${path}') END AS ${alias}_t`;
const ZONES = [1, 2, 3, 4, 5];

const STATS_SQL = `SELECT a.id AS id, a.garmin_activity_id AS garmin_id, a.date AS date, a.type_key AS type_key,
  a.duration_s AS duration_s, a.distance_m AS distance_m, a.d_plus_m AS d_plus_m, a.avg_hr AS avg_hr,
  ${field("start", "$.startTimeLocal")}, ${field("name", "$.activityName")},
  ${field("max_hr", "$.maxHR")}, ${field("vo2max", "$.vO2MaxValue")},
  ${ZONES.map((i) => field(`z${i}`, `$.hrTimeInZone_${i}`)).join(", ")},
  CASE WHEN ${OBJ} THEN json_extract(raw_json, '$.eventType.typeKey') END AS event_type,
  r.id AS race_id, r.name AS race_name, r.official_time_s AS race_official_time_s,
  r.overall_rank AS race_overall_rank, r.overall_total AS race_overall_total, r.category AS race_category,
  r.category_rank AS race_category_rank, r.category_total AS race_category_total, r.excluded AS race_excluded
FROM activity a LEFT JOIN race r ON r.activity_id = a.id ORDER BY a.date, a.id`;

const isNum = (t: unknown) => t === "integer" || t === "real";
/** Port de `_finite` : nombre fini JSON (booléens et chaînes exclus), sinon null. */
const finiteRaw = (v: unknown, t: unknown): number | null => (isNum(t) && Number.isFinite(Number(v)) ? Number(v) : null);
/** Colonne numérique : null si absente. */
const finiteCol = (v: unknown): number | null =>
  typeof v === "number" || typeof v === "bigint" ? (Number.isFinite(Number(v)) ? Number(v) : null) : null;
/** Port de `_positive`. */
const positiveCol = (v: unknown): number | null => {
  const n = finiteCol(v);
  return n !== null && n > 0 ? n : null;
};
const text = (v: unknown, t: unknown): string | null => (t === "text" && typeof v === "string" ? v : null);
const intOrNull = (v: unknown): number | null => (v === null || v === undefined ? null : Number(v));
const strOrNull = (v: unknown): string | null => (v === null || v === undefined ? null : String(v));

function raceOf(r: Row, isRace: boolean): RaceInfo | null {
  const hasRow = r.race_id !== null && r.race_id !== undefined;
  if (hasRow && !Number(r.race_excluded)) {
    return {
      name: strOrNull(r.race_name),
      official_time_s: intOrNull(r.race_official_time_s),
      overall_rank: intOrNull(r.race_overall_rank),
      overall_total: intOrNull(r.race_overall_total),
      category: strOrNull(r.race_category),
      category_rank: intOrNull(r.race_category_rank),
      category_total: intOrNull(r.race_category_total),
    };
  }
  if (!hasRow && isRace) {
    return {
      name: null, official_time_s: null, overall_rank: null, overall_total: null,
      category: null, category_rank: null, category_total: null,
    };
  }
  return null;
}

function statRow(r: Row): StatActivity {
  const zones = ZONES.map((i) => finiteRaw(r[`z${i}`], r[`z${i}_t`]));
  return {
    id: Number(r.id),
    garmin_id: Number(r.garmin_id),
    date: String(r.date),
    start: text(r.start, r.start_t),
    name: text(r.name, r.name_t),
    family: FAMILIES.get(String(r.type_key)) ?? "other",
    type_key: String(r.type_key),
    duration_s: positiveCol(r.duration_s),
    distance_m: positiveCol(r.distance_m),
    d_plus_m: finiteCol(r.d_plus_m),
    avg_hr: finiteCol(r.avg_hr),
    max_hr: finiteRaw(r.max_hr, r.max_hr_t),
    vo2max: finiteRaw(r.vo2max, r.vo2max_t),
    hr_zones_s: zones.every((z) => z !== null) ? (zones as number[]) : null,
    race: raceOf(r, r.event_type === "race"),
  };
}

export async function statsActivities(db: Db): Promise<{ activities: StatActivity[] }> {
  const { rows } = await db.execute(STATS_SQL);
  return { activities: rows.map(statRow) };
}

export async function statsRecords(db: Db): Promise<{ records: PersonalRecord[] }> {
  const { rows } = await db.execute("SELECT kind, value, garmin_activity_id, date FROM personalrecord ORDER BY id");
  return {
    records: rows.map((r) => ({
      kind: r.kind as PersonalRecord["kind"],
      value: Number(r.value),
      garmin_activity_id: intOrNull(r.garmin_activity_id),
      date: strOrNull(r.date),
    })),
  };
}
