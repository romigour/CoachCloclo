import type { Weekday } from "./dates";

export class ApiError extends Error {
  code: string;
  detail: unknown;
  status: number;
  constructor(code: string, detail: unknown, status = 0) {
    super(describe(code, detail));
    this.code = code;
    this.detail = detail;
    this.status = status;
  }
}

/** Message lisible : `detail` peut être une chaîne ou une liste {loc, msg} (validation 422). */
function describe(code: string, detail: unknown): string {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => {
      if (typeof d === "string") return d;
      const field = Array.isArray(d?.loc) ? d.loc.filter((x: unknown) => x !== "body").join(".") : "";
      const msg = d?.msg ?? "valeur invalide";
      return field ? `${field} : ${msg}` : msg;
    });
    if (parts.length) return parts.join(" ; ");
  }
  return `Erreur (${code})`;
}

export type Step = {
  kind: "warmup" | "active" | "recovery" | "cooldown";
  duration_s?: number | null;
  distance_m?: number | null;
  zone?: string | null;
};
export type StepGroup = { repeat: number; steps: Step[] };

/** Zones calculées côté serveur : allure en s/km (borne rapide puis lente), FC en bpm. */
export type Zones = {
  pace: Record<string, [number, number]> | null;
  hr: Record<string, [number, number]>;
  source: string[];
};

export type SessionStatus = "todo" | "exported" | "done" | "missed" | "sync_error";

export type Session = {
  id: number;
  order: number;
  type: string;
  title: string;
  description: string;
  target_kind: "pace" | "hr";
  status: SessionStatus;
  suggested_day: Weekday;
  sport: "run" | "bike";
  scheduled_date: string | null;
  chaining_note: string | null;
  steps: (Step | StepGroup)[];
  sync_error: string | null;
};

export type Priority = "principal" | "secondaire" | "plaisir";

/** Objectif de course (une course, sans les réglages du plan qui sont portés par le cycle). */
export type Goal = {
  id: number;
  type: "route" | "trail";
  distance_km: number;
  d_plus_m: number;
  race_date: string;
  priority: Priority;
  status: "active" | "done" | "archived";
  target_time_s: number | null;
  target_source: "user" | "claude" | null;
  gpx_summary: Record<string, unknown> | null;
};

/** Cycle d'entraînement : un plan et ses réglages, jusqu'à la course qui le termine. */
export type Cycle = {
  id: number;
  status: "active" | "done";
  plan_start: string;
  end_date: string;
  sessions_per_week: number;
  available_days: string[];
  long_run_day: string | null;
  include_bike: boolean;
  plan_accepted: boolean;
  needs_generation: boolean;
};

/** Corps de PATCH /api/cycle : seuls les champs modifiés ; `long_run_day: ""` retire le jour imposé. */
export type PlanSettingsInput = { available_days?: string[]; long_run_day?: string; include_bike?: boolean };

/** Corps de POST /api/cycle/next : réglages du plan et nombre de séances par semaine (2 à 7). */
export type NextCycleInput = PlanSettingsInput & { sessions_per_week?: number };

export type Activity = {
  id: number;
  date: string;
  type_key: string;
  duration_s: number | null;
  distance_m: number | null;
  d_plus_m: number | null;
  avg_hr: number | null;
  session_id: number | null;
  match_source: string | null;
};

export type Verdict = "in" | "fast" | "slow" | "hr_high" | "hr_low";

/** Un tour brut de la montre (sans le `raw` Garmin). */
export type Lap = {
  index: number;
  duration_s: number;
  distance_m: number;
  avg_hr: number | null;
  max_hr: number | null;
  avg_pace_s_km: number | null;
  step_order: number | null;
};

/** Une étape à plat (itérations dépliées) avec son prévu et son réalisé. */
export type StepResult = {
  group: number;
  iteration: number | null;
  position: number;
  kind: "warmup" | "active" | "recovery" | "cooldown";
  planned_duration_s: number | null;
  planned_distance_m: number | null;
  zone: string | null;
  target_low: number | null;
  target_high: number | null;
  done: boolean;
  duration_s: number | null;
  distance_m: number | null;
  avg_pace_s_km: number | null;
  avg_hr: number | null;
  verdict: Verdict | null;
};

export type StepComparison = {
  followed_workout: boolean;
  target_kind: "pace" | "hr";
  steps: StepResult[];
  laps: Lap[];
};

export type Comparison =
  | { available: false; reason: "no_activity" | "no_laps" }
  | ({ available: true } & StepComparison);

/** Famille de sport normalisée côté serveur. */
export type Family = "run" | "trail" | "bike" | "swim" | "strength" | "walk" | "other";

/** Résultat de course rattaché à une activité (tous les champs sont optionnels côté saisie). */
export type RaceInfo = {
  name: string | null;
  official_time_s: number | null;
  overall_rank: number | null;
  overall_total: number | null;
  category: string | null;
  category_rank: number | null;
  category_total: number | null;
};

/** Ligne de /api/stats/activities. */
export type StatActivity = {
  id: number;
  garmin_id: number;
  date: string;
  start: string | null;
  name: string | null;
  family: Family;
  type_key: string;
  duration_s: number | null;
  distance_m: number | null;
  d_plus_m: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  vo2max: number | null;
  hr_zones_s: number[] | null;
  race: RaceInfo | null;
};

export type PersonalRecord = {
  kind: "1k" | "1mile" | "5k" | "10k" | "half" | "marathon" | "longest_run";
  value: number;
  garmin_activity_id: number | null;
  date: string | null;
};

export type HistoryState = {
  status: "idle" | "running" | "done" | "error";
  imported: number;
  error: string | null;
};

export type Week = { week_index: number; week_monday: string; sessions: Session[] };
export type EventKind = "unavailable" | "injury" | "light_week" | "fatigue";

/** Imprévu déclaré (GET /api/cycle/events). */
export type CoachEvent = {
  id: number;
  kind: EventKind;
  start_date: string;
  end_date: string | null;
  max_sessions: number | null;
  days: string[] | null;
  session_id: number | null;
  note: string | null;
};

/** Corps de POST /api/cycle/events. */
export type EventInput = {
  kind: EventKind;
  start_date?: string;
  end_date?: string;
  max_sessions?: number;
  days?: string[];
  session_id?: number;
  note?: string;
};

/** L'imprévu est enregistré même si Claude échoue : `proposal_id` est alors nul et `error` renseigné. */
export type EventResult = { event_id: number; proposal_id: number | null; error: string | null };

/** Plan du cycle actif : `goals` tombent dans le cycle, `horizon` au-delà (du plus proche au plus lointain). */
export type Plan = {
  cycle: Cycle | null;
  goals: Goal[];
  horizon: Goal[];
  weeks: Week[];
  open_injury?: CoachEvent | null;
};

/** Cible du cycle : son premier Principal (comme `cycle_end` côté serveur), sinon la course du dernier
 * jour, sinon le dernier objectif du cycle. Un Plaisir le lendemain du Principal prolonge la fin du cycle
 * sans en devenir la cible. */
export function cycleGoal(plan: Pick<Plan, "cycle" | "goals">): Goal | null {
  const cycle = plan.cycle;
  if (!cycle) return null;
  const inCycle = [...plan.goals]
    .filter((g) => g.race_date <= cycle.end_date)
    .sort((a, b) => a.race_date.localeCompare(b.race_date) || a.id - b.id);
  return (
    inCycle.find((g) => g.priority === "principal") ??
    plan.goals.find((g) => g.race_date === cycle.end_date) ??
    plan.goals.at(-1) ??
    null
  );
}

export type Status = {
  garmin: "ok" | "auth_required" | "unavailable";
  llm_mode: "cli" | "api";
  pending_proposal_id: number | null;
  /** Cycle actif (réglages et plan), nul sans plan en cours. */
  cycle: Cycle | null;
  /** Objectifs à venir, du plus proche au plus lointain. */
  goals: Goal[];
  next_goal: Goal | null;
  /** Objectifs courus, du plus récent au plus ancien. */
  past_goals: Goal[];
  /** Dernier cycle terminé, seulement sans cycle actif : réglages repris par « Préparer le cycle suivant ». */
  last_cycle: Cycle | null;
  has_activities: boolean;
  history: HistoryState;
  /** Base de données indisponible (cloud injoignable, schéma trop récent) : message à afficher ; nul sinon. */
  storage?: StorageError | null;
};

export type StorageError = { code: string; detail: string };

/** État de la mise à jour (GET /api/update, présent seulement dans l'appli de bureau). */
export type UpdateView = {
  current: string;
  latest: string | null;
  available: boolean;
  state: "idle" | "checking" | "downloading" | "installing" | "failed";
  progress: number;
  error: string | null;
};

/** Mode LAN (GET/POST /api/lan, présent seulement dans l'appli de bureau). */
export type LanView = { enabled: boolean; has_pin: boolean; addresses: string[]; local: boolean };

/** Stockage des données (GET /api/storage) : jamais le jeton, seulement sa présence. */
export type StorageView = { mode: "local" | "turso"; turso_url: string | null; has_turso_token: boolean };

/** État de l'écran d'accueil (GET /api/setup/status, présent seulement dans l'appli de bureau). */
export type SetupStatus = {
  claude_cli: boolean;
  claude_auth: boolean;
  claude_step: "idle" | "installing" | "logging_in" | "failed";
  claude_error: string | null;
  garmin: "ok" | "auth_required" | "unavailable";
  llm_mode: "cli" | "api";
};

/** Clé `localStorage` : l'utilisateur a passé l'étape Claude. */
const CLAUDE_SKIPPED_KEY = "coach.claudeSkipped";

export function claudeSkipped(): boolean {
  try {
    return localStorage.getItem(CLAUDE_SKIPPED_KEY) === "1";
  } catch {
    return false;
  }
}

export function skipClaude(): void {
  try {
    localStorage.setItem(CLAUDE_SKIPPED_KEY, "1");
  } catch {
    // stockage indisponible : le choix ne vaut que pour l'écran en cours
  }
}

/** La configuration est terminée : Garmin connecté, et Claude connecté, en mode clé API ou passé. */
export function setupDone(s: SetupStatus, claudeSkipped: boolean): boolean {
  return s.garmin === "ok" && (s.llm_mode === "api" || s.claude_auth || claudeSkipped);
}

export type SettingsView = { llm_mode: "cli" | "api"; anthropic_model: string | null; has_api_key: boolean };

export type SessionSpec = {
  week_index: number;
  order: number;
  suggested_day: Weekday;
  type: string;
  target_kind: "pace" | "hr";
  title: string;
  description: string;
  chaining_note?: string | null;
  sport?: "run" | "bike";
  steps: (Step | StepGroup)[];
};

export type Change = {
  op: "modify" | "add" | "remove";
  session_id: number | null;
  session: SessionSpec | null;
  reason: string;
};

export type Proposal = { id: number; created_at: string; analysis: string; changes: Change[] };

export type HrZone = "Z1" | "Z2" | "Z3" | "Z4" | "Z5";

export type AidStation = { km: number; name: string; kind: "eau" | "complet"; cutoff: string | null; stop_min: number };

export type RaceSettings = {
  start_time: string;
  carbs_g_h: number;
  water_ml_h: number;
  carry_ml: number;
  aid_stations: AidStation[];
};

export type RaceSegment = {
  kind: "montée" | "plat" | "descente";
  start_km: number;
  end_km: number;
  eq_km: number;
  d_plus_m: number;
  d_minus_m: number;
  index: number;
  avg_grade_pct: number;
  time_s: number | null;
  pace_s_km: number | null;
  elapsed_s: number | null;
  clock: string | null;
  target_kind: "pace" | "hr";
  target_low: number | null;
  target_high: number | null;
  target_zone: HrZone | null;
};

export type Passage = { elapsed_s: number; clock: string; margin_min: number | null; status: "ok" | "serré" | "hors délai" | null };

export type AidPassage = { station: AidStation; passage: Passage };

export type NutritionLeg = {
  from_name: string;
  to_name: string;
  from_km: number;
  to_km: number;
  duration_s: number;
  carbs_g: number;
  water_ml: number;
  over_capacity: boolean;
};

export type RacePlan = {
  distance_km: number;
  eq_km: number;
  stops_s: number;
  target_time_s: number | null;
  reference_time_s: number | null;
  segments: RaceSegment[];
  aid_passages: AidPassage[];
  nutrition: NutritionLeg[];
  warnings: string[];
};

export type RaceView = {
  goal_id: number;
  goal_type: "route" | "trail";
  race_date: string;
  settings: RaceSettings;
  basis_date: string;
  profile: [number, number][] | null;
  plan: RacePlan;
  workout_id: number | null;
  export_error: string | null;
  export_stale: boolean;
  target_time_s: number | null;
  target_source: "user" | "claude" | null;
};

export type GoalInput = {
  type: "route" | "trail";
  distance_km: number;
  d_plus_m: number;
  race_date: string;
  /** Réglages du plan : seulement pour le premier objectif (aucun cycle actif). */
  sessions_per_week?: number;
  target_time?: string;
  gpx?: File | null;
  available_days?: string[];
  long_run_day?: string;
  include_bike?: boolean;
  priority?: Priority;
};

/** Effet d'un changement d'objectif sur le plan : proposition d'ajustement à relire, ou plan à régénérer. */
export type PlanChange = { proposal_id: number | null; needs_generation: boolean };
export type GoalChange = PlanChange & { goal: Goal };
/** Corps de PATCH /api/goals/{id} : seuls les champs modifiés. */
export type GoalUpdate = { race_date?: string; target_time?: string; priority?: Priority };

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  let payload: BodyInit | undefined;
  if (method !== "GET") headers["X-Coach"] = "1";
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: payload, credentials: "same-origin" });
  } catch {
    throw new ApiError("network", "Impossible de joindre le serveur CoachCloclo", 0);
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    const err = (data ?? {}) as { code?: string; detail?: unknown };
    throw new ApiError(err.code ?? `http_${res.status}`, err.detail ?? res.statusText, res.status);
  }
  return data as T;
}

const get = <T>(p: string) => request<T>("GET", p);
const put = <T>(p: string, b: unknown) => request<T>("PUT", p, b);
const patch = <T>(p: string, b: unknown) => request<T>("PATCH", p, b);
const del = <T>(p: string) => request<T>("DELETE", p);
const post = <T>(p: string, b?: unknown) => request<T>("POST", p, b ?? {});

export const api = {
  status: () => get<Status>("/status"),
  pin: (pin: string) => post<{ status: string }>("/auth/pin", { pin }),
  login: (email: string, password: string) =>
    post<{ status: "ok" | "needs_mfa"; login_id?: string }>("/garmin/login", { email, password }),
  mfa: (login_id: string, code: string) => post<{ status: string }>("/garmin/mfa", { login_id, code }),
  /** `null` sous `coach start` (pas d'appli de bureau : l'endpoint répond 404). */
  setupStatus: async (): Promise<SetupStatus | null> => {
    try {
      return await get<SetupStatus>("/setup/status");
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  },
  /** `null` sous `coach start` (pas d'appli de bureau : l'endpoint répond 404). */
  update: async (): Promise<UpdateView | null> => {
    try {
      return await get<UpdateView>("/update");
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  },
  /** `null` sous `coach start` (pas d'appli de bureau : l'endpoint répond 404). */
  lan: async (): Promise<LanView | null> => {
    try {
      return await get<LanView>("/lan");
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  },
  setLan: (enabled: boolean, pin?: string) => post<LanView>("/lan", pin === undefined ? { enabled } : { enabled, pin }),
  storage: () => get<StorageView>("/storage"),
  enableCloud: (url: string, token: string, replaceLocal: boolean) =>
    post<StorageView>("/storage/cloud", { url, token, replace_local: replaceLocal }),
  disableCloud: () => del<StorageView>("/storage/cloud"),
  wipeCloud: () => post<StorageView>("/storage/cloud/wipe"),
  checkUpdate: () => post<UpdateView>("/update/check"),
  installUpdate: () => post<{ status: string }>("/update/install"),
  version: () => get<{ version: string }>("/version"),
  installClaude: () => post<{ status: string }>("/setup/claude/install"),
  loginClaude: () => post<{ status: string }>("/setup/claude/login"),
  settings: () => get<SettingsView>("/settings"),
  saveSettings: (s: { llm_mode: "cli" | "api"; anthropic_api_key?: string; anthropic_model?: string }) =>
    request<SettingsView>("PUT", "/settings", s),
  createGoal: (g: GoalInput) => {
    const f = new FormData();
    f.set("type", g.type);
    f.set("distance_km", String(g.distance_km));
    f.set("d_plus_m", String(g.d_plus_m));
    f.set("race_date", g.race_date);
    if (g.sessions_per_week != null) f.set("sessions_per_week", String(g.sessions_per_week));
    if (g.target_time) f.set("target_time", g.target_time);
    if (g.gpx) f.set("gpx", g.gpx);
    if (g.available_days) f.set("available_days", g.available_days.join(","));
    if (g.long_run_day) f.set("long_run_day", g.long_run_day);
    if (g.include_bike) f.set("include_bike", "true");
    if (g.priority) f.set("priority", g.priority);
    return post<GoalChange>("/goals", f);
  },
  updateGoal: (goalId: number, body: GoalUpdate) => patch<GoalChange>(`/goals/${goalId}`, body),
  /** Retire (archive) un objectif ; même effet sur le plan qu'un ajout. */
  removeGoal: (goalId: number) => del<PlanChange>(`/goals/${goalId}`),
  updatePlanSettings: (body: PlanSettingsInput) => patch<{ cycle: Cycle; proposal_id: number }>("/cycle", body),
  /** Crée le cycle suivant (à générer) ; `body` surcharge les réglages repris du dernier cycle. */
  nextCycle: (body?: NextCycleInput) => post<Cycle>("/cycle/next", body),
  generate: () => post<{ summary: string; weeks: number }>("/cycle/generate"),
  accept: () => post<{ status: string }>("/cycle/accept"),
  plan: () => get<Plan>("/plan"),
  racePlan: (goalId: number) => get<RaceView>(`/goals/${goalId}/race-plan`),
  saveRacePlan: (goalId: number, settings: RaceSettings) => put<RaceView>(`/goals/${goalId}/race-plan`, settings),
  refreshRacePlan: (goalId: number) => post<RaceView>(`/goals/${goalId}/race-plan/refresh`),
  reimportRacePlan: (goalId: number) => post<RaceView>(`/goals/${goalId}/race-plan/reimport`),
  exportRacePlan: (goalId: number) => post<RaceView>(`/goals/${goalId}/race-plan/export`),
  exportCheck: (id: number, date: string) =>
    get<{ warnings: string[] }>(`/sessions/${id}/export-check?date=${encodeURIComponent(date)}`),
  exportSession: (id: number, date: string) => post<{ warnings: string[] }>(`/sessions/${id}/export`, { date }),
  moveSession: (id: number, date: string) => post<{ warnings: string[] }>(`/sessions/${id}/move`, { date }),
  unschedule: (id: number) => post<{ status: string }>(`/sessions/${id}/unschedule`),
  retry: (id: number) => post<{ status: string }>(`/sessions/${id}/retry`),
  activities: (week: number) => get<Activity[]>(`/activities?week=${week}`),
  zones: () => get<Zones | null>("/zones"),
  comparison: (sessionId: number) => get<Comparison>(`/sessions/${sessionId}/comparison`),
  freeActivities: (days: number, sport: "run" | "bike" = "run") =>
    get<Activity[]>(`/activities/free?days=${days}&sport=${sport}`),
  match: (activityId: number, sessionId: number | null) =>
    post<{ status: string }>(`/activities/${activityId}/match`, { session_id: sessionId }),
  sync: () => post<Record<string, unknown>>("/sync"),
  pendingProposal: () => get<Proposal | null>("/proposals/pending"),
  acceptProposal: (id: number) => post<{ sync_error_ids: number[] }>(`/proposals/${id}/accept`),
  rejectProposal: (id: number) => post<{ status: string }>(`/proposals/${id}/reject`),
  statsActivities: () => get<{ activities: StatActivity[] }>("/stats/activities"),
  statsRecords: () => get<{ records: PersonalRecord[] }>("/stats/records"),
  saveRace: (activityId: number, race: Partial<RaceInfo>) => request<StatActivity>("PUT", `/races/${activityId}`, race),
  removeRace: (activityId: number) => del<{ status: string }>(`/races/${activityId}`),
  createEvent: (body: EventInput) => post<EventResult>("/cycle/events", body),
  requestAdjustment: () => post<{ proposal_id: number }>("/cycle/adjust"),
  /** Imprévus du cycle actif ; liste vide sans plan en cours. */
  events: () => get<CoachEvent[]>("/cycle/events"),
  deleteEvent: (id: number) => del<{ status: string }>(`/events/${id}`),
  resumeInjury: (id: number, date: string) => post<EventResult>(`/events/${id}/resume`, { date }),
  importHistory: () => post<{ status: string }>("/history/import"),
};
