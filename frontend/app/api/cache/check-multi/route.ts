import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  // Forward all `programs` values as repeated query params
  const programs = searchParams.getAll("programs");
  const qs = programs.map((p) => `programs=${encodeURIComponent(p)}`).join("&");
  try {
    const res = await fetch(
      `${BACKEND}/api/cache/check-multi${qs ? `?${qs}` : ""}`,
      { cache: "no-store" },
    );
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { error: `Backend unreachable: ${(err as Error).message}` },
      { status: 502 },
    );
  }
}
