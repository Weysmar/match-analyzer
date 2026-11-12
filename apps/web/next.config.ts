import path from "node:path";
import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// Read when the site is built: rewrites are fixed at that point.
const api = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

// The production image (apps/web/Dockerfile) asks for a standalone server: only the files it
// traces, from the repository root, whose workspace holds the dependencies. `next start` stays as
// it was for the end-to-end test.
const standalone = process.env.NEXT_OUTPUT === "standalone";

const config: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  ...(standalone
    ? { output: "standalone" as const, outputFileTracingRoot: path.join(process.cwd(), "../..") }
    : {}),
  // The browser talks to the API through the site: same origin, first-party cookies (step 8).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default createNextIntlPlugin("./src/i18n/request.ts")(config);
