import { NextResponse } from "next/server";
import type { CreateRunBody } from "@/lib/types";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  let body: CreateRunBody;
  try {
    body = (await request.json()) as CreateRunBody;
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  if (!body.user_input || !body.user_input.trim()) {
    return NextResponse.json({ error: "user_input is required" }, { status: 400 });
  }

  try {
    const res = await fetch(`${BACKEND}/api/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { error: `Backend unreachable: ${(err as Error).message}` },
      { status: 502 },
    );
  }
}

export async function GET() {
  try {
    const res = await fetch(`${BACKEND}/api/run`, { cache: "no-store" });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { error: `Backend unreachable: ${(err as Error).message}` },
      { status: 502 },
    );
  }
}
