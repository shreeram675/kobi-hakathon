import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: { run_id: string } },
) {
  try {
    const res = await fetch(`${BACKEND}/api/run/${params.run_id}`, {
      cache: "no-store",
    });
    if (res.status === 404) {
      return NextResponse.json({ error: "run not found" }, { status: 404 });
    }
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { error: `Backend unreachable: ${(err as Error).message}` },
      { status: 502 },
    );
  }
}
