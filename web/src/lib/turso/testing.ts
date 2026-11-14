// Les tests tournent depuis web/ (cwd). Aide de test uniquement (client Node, base en mémoire) : jamais importée par le code de production.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createClient } from "@libsql/client";
import type { Db } from "./db";

export async function loadFixtureDb(name: "active" | "between"): Promise<Db> {
  const sql = readFileSync(resolve(process.cwd(), "src/lib/turso/__fixtures__", `${name}.sql`), "utf8");
  const client = createClient({ url: ":memory:" });
  await client.executeMultiple(sql);
  return client as unknown as Db;
}
