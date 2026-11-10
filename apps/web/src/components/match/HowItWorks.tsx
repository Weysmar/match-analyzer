/**
 * "How it is detected" (T16.3, section 4, rule 7 of docs/PLAN-V2.md): what each term on the page
 * means, in one sentence, folded away until asked for. Plain HTML, no client JavaScript.
 */
export function HowItWorks({
  summary,
  items,
}: {
  summary: string;
  items: readonly { term: string; definition: string }[];
}) {
  if (items.length === 0) return null;
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-xs font-medium text-slate-600 underline dark:text-slate-400">
        {summary}
      </summary>
      <dl className="mt-2 flex flex-col gap-2">
        {items.map((item) => (
          <div key={item.term}>
            <dt className="font-medium">{item.term}</dt>
            <dd className="text-slate-600 dark:text-slate-400">{item.definition}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
