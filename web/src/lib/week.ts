import type { Session, Week } from "./api";
import { addDays, defaultExportDate, weekDays } from "./dates";

/** Jour où la séance apparaît : sa date planifiée si elle tombe dans la semaine, sinon son jour conseillé. */
export function sessionDate(s: Session, weekMonday: string): string {
  return s.scheduled_date && weekDays(weekMonday).includes(s.scheduled_date)
    ? s.scheduled_date
    : defaultExportDate(weekMonday, s.suggested_day);
}

export type Day = { date: string; sessions: Session[] };

/** Les 7 jours de la semaine avec leurs séances. */
export function days(week: Week): Day[] {
  return weekDays(week.week_monday).map((date) => ({
    date,
    sessions: week.sessions.filter((s) => sessionDate(s, week.week_monday) === date),
  }));
}

/** Semaine qui contient `today`, sinon la prochaine à venir, sinon la dernière. */
export function currentWeek(weeks: Week[], today: string): Week | null {
  return (
    weeks.find((w) => w.week_monday <= today && today <= addDays(w.week_monday, 6)) ??
    weeks.find((w) => w.week_monday > today) ??
    weeks.at(-1) ??
    null
  );
}

/** Séance à mettre en avant : celle du jour, sinon la prochaine non réalisée de la semaine. */
export function focusSession(week: Week | null, today: string): Session | null {
  if (!week) return null;
  const dated = week.sessions
    .map((s) => ({ s, date: sessionDate(s, week.week_monday) }))
    .sort((a, b) => a.date.localeCompare(b.date) || a.s.order - b.s.order);
  return (
    dated.find((x) => x.date === today)?.s ??
    dated.find((x) => x.date > today && x.s.status !== "done")?.s ??
    null
  );
}

/** Nombre de jours avant la course (0 le jour J). */
export function daysUntil(today: string, raceDate: string): number {
  const ms = Date.parse(`${raceDate}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`);
  return Math.round(ms / 86_400_000);
}

/** Séances pas encore faites de la semaine en cours et des suivantes (candidates à une fatigue). */
export function openSessions(weeks: Week[], today: string): Session[] {
  return weeks
    .filter((w) => addDays(w.week_monday, 6) >= today)
    .flatMap((w) => w.sessions)
    .filter((s) => s.status !== "done");
}
