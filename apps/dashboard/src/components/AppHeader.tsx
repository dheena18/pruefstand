"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { LocaleSwitch } from "./LocaleSwitch";
import { ThemeToggle } from "./ThemeToggle";
import { t, type Locale } from "@/lib/i18n";

export interface AppHeaderProps {
  locale: Locale;
  /** "Try it" is linked only when `NEXT_PUBLIC_DEMO_API_URL` is set at build (UI-25). */
  demoEnabled: boolean;
  githubUrl: string;
}

const FOCUSABLE = "a[href], button:not([disabled])";

/** Keep Tab inside `sheet`; Escape closes it. Returns the handler for `keydown`. */
export function trapFocus(event: KeyboardEvent, sheet: HTMLElement, close: () => void): void {
  if (event.key === "Escape") {
    close();
    return;
  }
  if (event.key !== "Tab") return;
  const items = Array.from(sheet.querySelectorAll<HTMLElement>(FOCUSABLE));
  const first = items[0];
  const last = items[items.length - 1];
  if (first === undefined || last === undefined) return;
  const active = document.activeElement;
  if (event.shiftKey && active === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}

/** Sticky header: wordmark, Runs / Try it / Licences, locale switch, theme toggle; a sheet below 640 px. */
export function AppHeader({ locale, demoEnabled, githubUrl }: AppHeaderProps) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const sheet = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = sheet.current;
    if (!open || element === null) return;
    const close = () => {
      setOpen(false);
      button.current?.focus();
    };
    const onKey = (event: KeyboardEvent) => {
      trapFocus(event, element, close);
    };
    element.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const links = [
    { href: `/${locale}/`, label: t(locale, "nav.runs") },
    ...(demoEnabled ? [{ href: `/${locale}/try/`, label: t(locale, "nav.try") }] : []),
    { href: `/${locale}/licences/`, label: t(locale, "nav.licences") },
  ];
  return (
    <header className="app-header">
      <div className="app-header__bar">
        <Link className="app-header__brand" href={`/${locale}/`}>
          Prüfstand
        </Link>
        <nav className="app-header__nav" aria-label={t(locale, "nav.main")}>
          {links.map((link) => (
            <Link key={link.href} href={link.href}>
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="app-header__tools">
          <LocaleSwitch locale={locale} />
          <ThemeToggle locale={locale} />
          <a href={githubUrl}>GitHub ↗</a>
        </div>
        <button
          ref={button}
          type="button"
          className="btn app-header__menu"
          aria-expanded={open}
          aria-controls="app-sheet"
          onClick={() => {
            setOpen(!open);
          }}
        >
          {t(locale, "nav.menu")}
        </button>
      </div>
      <div id="app-sheet" ref={sheet} className="app-sheet" hidden={!open}>
        {links.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            onClick={() => {
              setOpen(false);
            }}
          >
            {link.label}
          </Link>
        ))}
        <LocaleSwitch locale={locale} />
        <ThemeToggle locale={locale} />
        <a href={githubUrl}>GitHub ↗</a>
      </div>
    </header>
  );
}
