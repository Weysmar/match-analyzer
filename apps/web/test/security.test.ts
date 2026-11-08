import { describe, expect, it } from "vitest";
import { contentSecurityPolicy, originOf, securityHeaders } from "../src/lib/security";

function directives(policy: string): Map<string, string[]> {
  return new Map(
    policy.split(";").map((directive) => {
      const [name = "", ...sources] = directive.trim().split(/\s+/);
      return [name, sources];
    }),
  );
}

describe("content security policy", () => {
  const production = directives(
    contentSecurityPolicy({
      nonce: "abc",
      development: false,
      secure: true,
      uploadOrigin: "https://store.example.test",
    }),
  );

  it("upgrades stray http requests on an https site only", () => {
    expect(production.has("upgrade-insecure-requests")).toBe(true);
    const local = directives(
      contentSecurityPolicy({
        nonce: "abc",
        development: false,
        secure: false,
        uploadOrigin: "http://127.0.0.1:9000",
      }),
    );
    expect(local.has("upgrade-insecure-requests")).toBe(false);
  });

  it("runs only scripts carrying the nonce", () => {
    expect(production.get("script-src")).toEqual(["'self'", "'nonce-abc'", "'strict-dynamic'"]);
  });

  it("never allows eval or inline code in production", () => {
    const policy = [...production.values()].flat();
    expect(policy).not.toContain("'unsafe-eval'");
    expect(policy).not.toContain("'unsafe-inline'");
  });

  it("lets the browser upload to the object store and nowhere else", () => {
    expect(production.get("connect-src")).toEqual(["'self'", "https://store.example.test"]);
  });

  it("forbids framing, plugins and foreign forms", () => {
    expect(production.get("frame-ancestors")).toEqual(["'none'"]);
    expect(production.get("object-src")).toEqual(["'none'"]);
    expect(production.get("form-action")).toEqual(["'self'"]);
    expect(production.get("base-uri")).toEqual(["'self'"]);
  });

  it("allows what React needs in development only", () => {
    const development = directives(
      contentSecurityPolicy({ nonce: "abc", development: true, secure: false, uploadOrigin: null }),
    );
    expect(development.get("script-src")).toContain("'unsafe-eval'");
    expect(development.get("connect-src")).toEqual(["'self'"]);
  });
});

describe("origins", () => {
  it.each([
    ["http://127.0.0.1:9000", "http://127.0.0.1:9000"],
    ["https://store.example.test/bucket/key?x=1", "https://store.example.test"],
    ["not a url", null],
    [undefined, null],
    ["", null],
  ])("%s gives %s", (url, origin) => {
    expect(originOf(url)).toBe(origin);
  });
});

describe("security headers", () => {
  it("are set on every page", () => {
    const headers = securityHeaders("http://localhost:3000");
    expect(headers["X-Content-Type-Options"]).toBe("nosniff");
    expect(headers["X-Frame-Options"]).toBe("DENY");
    expect(headers["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
  });

  it("include HSTS over https only", () => {
    expect(securityHeaders("http://localhost:3000")["Strict-Transport-Security"]).toBeUndefined();
    expect(securityHeaders("https://example.test")["Strict-Transport-Security"]).toContain(
      "max-age",
    );
  });
});
