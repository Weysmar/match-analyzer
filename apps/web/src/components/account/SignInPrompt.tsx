import { useTranslations } from "next-intl";
import { SignInOptions } from "./SignInOptions";

/**
 * Offered once a first match is analyzed (T8.11), never before: trying the tool asks for nothing.
 * Signing in attaches this session's matches to the account.
 */
export function SignInPrompt({ epic, returnTo }: { epic: boolean; returnTo: string }) {
  const t = useTranslations("account.prompt");
  return (
    <aside
      aria-labelledby="sign-in-prompt"
      className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900"
    >
      <h2 id="sign-in-prompt" className="font-semibold">
        {t("title")}
      </h2>
      <p className="text-sm text-slate-600 dark:text-slate-300">{t("lead")}</p>
      <SignInOptions epic={epic} returnTo={returnTo} />
    </aside>
  );
}
