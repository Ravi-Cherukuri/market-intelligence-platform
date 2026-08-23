import { createHmac, timingSafeEqual } from "node:crypto";
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

function safeEqual(left: string, right: string): boolean {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer);
}

function sessionSignature(username: string, password: string, expiresAt: string): string {
  return createHmac("sha256", password)
    .update(`field-intelligence:${username}:${expiresAt}`)
    .digest("base64url");
}

function validSession(token: string, username: string, password: string): boolean {
  const separator = token.indexOf(".");
  if (separator < 1) return false;
  const expiresAt = token.slice(0, separator);
  const signature = token.slice(separator + 1);
  if (!/^\d{13}$/.test(expiresAt) || Number(expiresAt) <= Date.now()) return false;
  return safeEqual(signature, sessionSignature(username, password, expiresAt));
}

export function proxy(request: NextRequest) {
  const expectedUser = process.env.ADMIN_USERNAME ?? "Admin";
  const expectedPassword = process.env.ADMIN_PASSWORD ?? "Password";
  const authorization = request.headers.get("authorization");
  const session = request.cookies.get("pilot_admin_session")?.value ?? "";
  let basicAuthenticated = false;

  if (authorization?.startsWith("Basic ")) {
    try {
      const decoded = Buffer.from(authorization.slice(6), "base64").toString("utf8");
      const separator = decoded.indexOf(":");
      const username = decoded.slice(0, separator);
      const password = decoded.slice(separator + 1);
      basicAuthenticated = separator >= 0 && safeEqual(username, expectedUser) && safeEqual(password, expectedPassword);
    } catch {
      // A malformed header receives the same generic challenge as bad credentials.
    }
  }

  const sessionAuthenticated = validSession(session, expectedUser, expectedPassword);
  if (basicAuthenticated || sessionAuthenticated) {
    const requestHeaders = new Headers(request.headers);
    // Background requests cannot reliably repeat the browser's Basic header.
    // The secret stays server-side while the backend receives the same pilot auth.
    if (!basicAuthenticated) {
      requestHeaders.set(
        "authorization",
        `Basic ${Buffer.from(`${expectedUser}:${expectedPassword}`).toString("base64")}`,
      );
    }
    const response = NextResponse.next({ request: { headers: requestHeaders } });
    if (basicAuthenticated) {
      const expiresAt = String(Date.now() + 60 * 60 * 8 * 1000);
      const signedSession = `${expiresAt}.${sessionSignature(expectedUser, expectedPassword, expiresAt)}`;
      response.cookies.set("pilot_admin_session", signedSession, {
        httpOnly: true,
        maxAge: 60 * 60 * 8,
        path: "/",
        sameSite: "strict",
        secure: request.nextUrl.protocol === "https:",
      });
    }
    return response;
  }

  return new NextResponse("Pilot administrator credentials required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Field Intelligence Pilot", charset="UTF-8"' },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.svg).*)"],
};
