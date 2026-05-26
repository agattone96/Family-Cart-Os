import { sql } from "../lib/db";

export default async function handler(req: any, res: any) {
  if (req.method && req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ ok: false, error: "Method Not Allowed" });
  }

  try {
    const rows = (await sql`SELECT NOW() AS now;`) as Array<{ now: string }>;
    return res.status(200).json({ ok: true, now: rows[0]?.now ?? null });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return res.status(500).json({ ok: false, error: message });
  }
}
