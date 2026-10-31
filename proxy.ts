import { createHmac, scryptSync, timingSafeEqual } from "node:crypto";
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

type Role = "admin" | "reports";
type Account = { role: Role; username: string; secret: string; verify: (password: string) => boolean };

function safeEqual(left: string, right: string): boolean {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer);
}

function verifyScrypt(password: string, verifier: string): boolean {
  try {
    const [algorithm, n, r, p, salt, digest] = verifier.split("$");
    if (algorithm !== "scrypt") return false;
    const expected = Buffer.from(digest, "base64url");
    const actual = scryptSync(password, Buffer.from(salt, "base64url"), expected.length, {
      N: Number(n), r: Number(r), p: Number(p), maxmem: 64 * 1024 * 1024,
    });
    return expected.length === actual.length && timingSafeEqual(expected, actual);
  } catch {
    return false;
  }
}

function accounts(): Account[] {
  const adminUser = process.env.ADMIN_USERNAME ?? "Admin";
  const adminPassword = process.env.ADMIN_PASSWORD ?? "Password";
  const reportUser = process.env.REPORT_USERNAME ?? "Reports";
  const reportVerifier = process.env.REPORT_PASSWORD_HASH ?? "";
  return [
    { role: "admin", username: adminUser, secret: adminPassword, verify: (value) => safeEqual(value, adminPassword) },
    { role: "reports", username: reportUser, secret: reportVerifier, verify: (value) => verifyScrypt(value, reportVerifier) },
  ];
}

function signature(account: Account, expiresAt: string): string {
  return createHmac("sha256", account.secret)
    .update(`field-intelligence:${account.role}:${account.username}:${expiresAt}`)
    .digest("base64url");
}

function accountFromSession(token: string, candidates: Account[]): Account | null {
  const [role, expiresAt, supplied] = token.split(".");
  if (!/^[0-9]{13}$/.test(expiresAt ?? "") || Number(expiresAt) <= Date.now()) return null;
  const account = candidates.find((item) => item.role === role);
  return account && safeEqual(supplied ?? "", signature(account, expiresAt)) ? account : null;
}

function internalReportSignature(account: Account): string {
  return createHmac("sha256", account.secret).update(`field-intelligence:internal:${account.role}`).digest("hex");
}

export function proxy(request: NextRequest) {
  const candidates = accounts();
  const authorization = request.headers.get("authorization");
  let account: Account | null = accountFromSession(request.cookies.get("fieldintel_session")?.value ?? "", candidates);

  if (authorization?.startsWith("Basic ")) {
    try {
      const decoded = Buffer.from(authorization.slice(6), "base64").toString("utf8");
      const separator = decoded.indexOf(":");
      const username = decoded.slice(0, separator);
      const password = decoded.slice(separator + 1);
      account = candidates.find((item) => separator >= 0 && safeEqual(username, item.username) && item.verify(password)) ?? null;
    } catch {
      account = null;
    }
  }

  if (!account) {
    return new NextResponse("Field Intelligence credentials required", {
      status: 401,
      headers: { "WWW-Authenticate": 'Basic realm="Field Intelligence Pilot", charset="UTF-8"' },
    });
  }

  const requestHeaders = new Headers(request.headers);
  if (account.role === "admin" && !authorization) {
    requestHeaders.set("authorization", `Basic ${Buffer.from(`${account.username}:${account.secret}`).toString("base64")}`);
  }
  if (account.role === "reports") {
    requestHeaders.delete("authorization");
    requestHeaders.set("x-fieldintel-role", account.role);
    requestHeaders.set("x-fieldintel-auth", internalReportSignature(account));
  }
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  if (authorization) {
    const expiresAt = String(Date.now() + 60 * 60 * 8 * 1000);
    response.cookies.set("fieldintel_session", `${account.role}.${expiresAt}.${signature(account, expiresAt)}`, {
      httpOnly: true, maxAge: 60 * 60 * 8, path: "/", sameSite: "strict",
      secure: request.nextUrl.protocol === "https:",
    });
  }
  return response;
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.svg).*)"] };
