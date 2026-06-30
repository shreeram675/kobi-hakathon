import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  { params }: { params: { run_id: string } },
) {
  let body: { decision: string };
  try {
    body = (await request.json()) as { decision: string };
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  if (!body.decision || !["use_cache", "fresh"].includes(body.decision)) {
    return NextResponse.json({ error: "decision must be 'use_cache' or 'fresh'" }, { status: 400 });
  }

  try {
    const res = await fetch(`${BACKEND}/api/run/${params.run_id}/cache-decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => res.statusText);
      return NextResponse.json({ error: detail }, { status: res.status });
    }
    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json(
      { error: `Backend unreachable: ${(err as Error).message}` },
      { status: 502 },
    );
  }
}
