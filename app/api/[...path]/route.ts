import { NextRequest } from "next/server";

type Context = { params: Promise<{ path: string[] }> };

async function forward(request: NextRequest, context: Context) {
  const { path } = await context.params;
  const base = process.env.CAMP_SERVER_URL || "http://127.0.0.1:8765";
  const target = new URL(`/api/${path.map(encodeURIComponent).join("/")}`, base);
  target.search = request.nextUrl.search;

  const headers: Record<string, string> = { Accept: "application/json" };
  const contentType = request.headers.get("content-type");
  if (contentType) headers["Content-Type"] = contentType;

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.text(),
      cache: "no-store",
    });
    return new Response(await upstream.arrayBuffer(), {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") || "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return Response.json(
      { error: "bad_gateway", message: "夏令营服务端尚未启动或无法连接" },
      { status: 502 },
    );
  }
}

export const GET = forward;
export const POST = forward;
export const HEAD = forward;
