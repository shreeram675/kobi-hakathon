import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  { params }: { params: { run_id: string } },
) {
  let body: { answer: string };
  try {
    body = (await request.json()) as { answer: string };
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  if (!body.answer || !body.answer.trim()) {
    return NextResponse.json({ error: "answer is required" }, { status: 400 });
  }

  try {
    const res = await fetch(`${BACKEND}/api/run/${params.run_id}/clarify`, {
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
