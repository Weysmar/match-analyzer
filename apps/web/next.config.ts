import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// Read when the site is built: rewrites are fixed at that point.
const api = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

const config: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  // The browser talks to the API through the site: same origin, first-party cookies (step 8).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default createNextIntlPlugin("./src/i18n/request.ts")(config);
