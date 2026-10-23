import { NextResponse, type NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const key = request.nextUrl.searchParams.get("key");
  if (key) {
    const path = request.nextUrl.pathname || "/";
    const body = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=${path}"><script>location.replace(${JSON.stringify(path)})</script></head><body></body></html>`;
    const response = new NextResponse(body, {
      status: 200,
      headers: { "content-type": "text/html; charset=utf-8" },
    });
    response.cookies.set("lore_key", key, { httpOnly: true, sameSite: "lax", path: "/" });
    return response;
  }
  if (!request.cookies.get("lore_key")) {
    return NextResponse.rewrite(new URL("/locked", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
