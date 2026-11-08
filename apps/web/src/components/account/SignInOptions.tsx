import { useTranslations } from "next-intl";

/** Where a sign-in starts: the API, through the site's relay, which sends the player on. */
export function signInHref(provider: "steam" | "epic", returnTo: string): string {
  return `/api/v1/auth/${provider}?${new URLSearchParams({ return_to: returnTo })}`;
}

/**
 * The ways to sign in (T8.11): Steam's own button, as Valve asks, and Epic only once its review
 * passed (`FEATURE_EPIC_LOGIN`, section 8.4 of CLAUDE.md). Plain links: the API does the rest.
 */
export function SignInOptions({ epic, returnTo }: { epic: boolean; returnTo: string }) {
  const t = useTranslations("account");
  return (
    <div className="flex flex-wrap items-center gap-3">
      <a
        href={signInHref("steam", returnTo)}
        className="inline-block rounded focus-visible:outline-2"
      >
        {/* Valve's official button, served by the site: Steam never sees the visitors. */}
        {/* biome-ignore lint/performance/noImgElement: a fixed 180×35 image needs no optimizer. */}
        <img src="/steam/sign-in.png" alt={t("steam")} width={180} height={35} />
      </a>
      {epic ? (
        <a
          href={signInHref("epic", returnTo)}
          className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
        >
          {t("epic")}
        </a>
      ) : null}
    </div>
  );
}
