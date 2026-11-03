import Link from "next/link";

export interface EmptyStateProps {
  title: string;
  text?: string;
  action?: { href: string; label: string };
}

/** Heading, optional text and an optional link: empty lists and `_empty` placeholder pages (ui-spec §5). */
export function EmptyState({ title, text, action }: EmptyStateProps) {
  return (
    <section className="panel" data-state="empty">
      <h1>{title}</h1>
      {text === undefined ? null : <p>{text}</p>}
      {action === undefined ? null : (
        <div className="panel__actions">
          <Link href={action.href}>{action.label}</Link>
        </div>
      )}
    </section>
  );
}
