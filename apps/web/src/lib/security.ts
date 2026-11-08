/**
 * The site's security headers (section 10 of CLAUDE.md). Scripts only run with this request's
 * nonce: an injected script has no way to guess it. The one origin the browser may talk to besides
 * the site is the object store, which receives uploads directly.
 */

export interface PolicyOptions {
  nonce: string;
  development: boolean;
  /** The site is served over https: anything it loads over http is then a mistake. */
  secure: boolean;
  /** Where presigned uploads go, such as `http://127.0.0.1:9000`. */
  uploadOrigin: string | null;
}

export function contentSecurityPolicy({
  nonce,
  development,
  secure,
  uploadOrigin,
}: PolicyOptions): string {
  // React needs eval in development to rebuild error stacks; its overlay injects inline styles.
  const scripts = [`'self'`, `'nonce-${nonce}'`, `'strict-dynamic'`];
  if (development) scripts.push(`'unsafe-eval'`);
  const styles = development ? [`'self'`, `'unsafe-inline'`] : [`'self'`, `'nonce-${nonce}'`];
  const connect = [`'self'`];
  if (uploadOrigin) connect.push(uploadOrigin);
  const directives = [
    `default-src 'self'`,
    `script-src ${scripts.join(" ")}`,
    `style-src ${styles.join(" ")}`,
    `img-src 'self' data:`,
    `font-src 'self'`,
    `connect-src ${connect.join(" ")}`,
    `object-src 'none'`,
    `base-uri 'self'`,
    `form-action 'self'`,
    `frame-ancestors 'none'`,
  ];
  // Not on a local http site: it would turn the uploads to the local store into https and break them.
  if (secure) directives.push("upgrade-insecure-requests");
  return directives.join("; ");
}

/** The origin of a URL, or null when it is not one: what a CSP source expects. */
export function originOf(url: string | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

export function securityHeaders(siteUrl: string): Record<string, string> {
  const headers: Record<string, string> = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
  };
  // Over https only: a browser told so over http would refuse the development server afterwards.
  if (siteUrl.startsWith("https://")) {
    headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains";
  }
  return headers;
}
