"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";

const NAV_LINKS = [
  { href: "/", label: "Quadrant" },
  { href: "/scoreboard", label: "Scoreboard" },
  { href: "/tickers", label: "Tickers" },
  { href: "/map", label: "Map" },
  { href: "/backtest", label: "Backtest" },
  { href: "/thesis", label: "Thesis" },
];

export function Nav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  return (
    <>
      {/* Desktop nav */}
      <nav className="hidden gap-1 md:flex">
        {NAV_LINKS.map((l) => {
          const active = pathname === l.href;
          return (
            <Link
              key={l.href}
              href={l.href}
              aria-current={active ? "page" : undefined}
              className={`rounded px-2 py-1 text-sm transition-colors ${
                active
                  ? "bg-gray-100 font-medium text-gray-900"
                  : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              {l.label}
            </Link>
          );
        })}
      </nav>

      {/* Mobile hamburger */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center justify-center rounded p-1.5 text-gray-600 hover:bg-gray-100 md:hidden"
        aria-label={open ? "Close navigation menu" : "Open navigation menu"}
        aria-expanded={open}
        aria-controls="mobile-nav-menu"
      >
        {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>

      {/* Mobile menu */}
      {open && (
        <nav
          id="mobile-nav-menu"
          className="absolute left-0 right-0 top-full z-50 border-b border-gray-200 bg-white px-6 py-2 shadow-lg md:hidden"
        >
          <div className="mx-auto flex max-w-6xl flex-col gap-1">
            {NAV_LINKS.map((l) => {
              const active = pathname === l.href;
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  onClick={() => setOpen(false)}
                  aria-current={active ? "page" : undefined}
                  className={`rounded px-2 py-2 text-sm transition-colors ${
                    active
                      ? "bg-gray-100 font-medium text-gray-900"
                      : "text-gray-600 hover:bg-gray-100"
                  }`}
                >
                  {l.label}
                </Link>
              );
            })}
          </div>
        </nav>
      )}
    </>
  );
}
