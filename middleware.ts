import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const password = process.env.CAMP_PASSWORD || "";
  if (!password) return NextResponse.next();

  const authed = request.cookies.get("bdsm_auth")?.value === password;
  const isLogin = request.nextUrl.pathname === "/login";

  if (!authed && !isLogin) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  if (authed && isLogin) {
    return NextResponse.redirect(new URL("/", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
