import { type NextRequest, NextResponse } from "next/server";
import { contentSecurityPolicy, originOf, securityHeaders } from "@/lib/security";

/**
 * Runs before every page: a fresh nonce, the content security policy that names it, and the other
 * security headers. Next.js reads the nonce from the request's policy and puts it on its own
 * scripts. The API sets its own headers, so `/api` is left out.
 */
export function proxy(request: NextRequest): NextResponse {
  const nonce = btoa(crypto.randomUUID());
  const siteUrl = process.env.SITE_URL ?? "http://localhost:3000";
  const policy = contentSecurityPolicy({
    nonce,
    development: process.env.NODE_ENV === "development",
    secure: siteUrl.startsWith("https://"),
    uploadOrigin: originOf(process.env.S3_PUBLIC_ENDPOINT ?? process.env.S3_ENDPOINT),
  });
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  for (const [name, value] of Object.entries(securityHeaders(siteUrl))) {
    response.headers.set(name, value);
  }
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!api|health|_next/static|_next/image|favicon.ico).*)",
      // Prefetches render no page: they need no policy.
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
