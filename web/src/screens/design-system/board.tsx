import type {ReactNode} from 'react';

import {cx} from '../../lib/cx';

/** Small mono uppercase label above a group of specimens. */
export function Overline({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cx(
        'font-mono text-overline text-fg-muted uppercase',
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Caption under a specimen, e.g. "hover" or "compact · 32". */
export function Caption({children}: {children: ReactNode}) {
  return (
    <span className="font-mono text-[0.6875rem] text-fg-muted">{children}</span>
  );
}

/** A specimen with its caption centered below. */
export function Specimen({
  caption,
  children,
}: {
  caption: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2">
      {children}
      <Caption>{caption}</Caption>
    </div>
  );
}

/** Board title: numbered overline, large heading and a short intro. */
export function BoardHeader({
  overline,
  title,
  children,
}: {
  overline: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <header className="flex flex-col justify-between gap-6 lg:flex-row lg:items-end lg:gap-16">
      <div className="flex flex-col gap-3">
        <span className="font-mono text-label tracking-[0.08em] text-fg-muted uppercase">
          {overline}
        </span>
        <h1 className="text-[2.25rem] leading-[2.75rem] font-semibold tracking-[-0.02em] sm:text-[3rem] sm:leading-[3.25rem]">
          {title}
        </h1>
      </div>
      <p className="max-w-[41.25rem] text-body-lg text-fg-secondary">
        {children}
      </p>
    </header>
  );
}

/** A section title over a strong rule, with a mono note on the right. */
export function SectionHeading({title, note}: {title: string; note?: string}) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-fg pb-2.5">
      <h2 className="text-title-2">{title}</h2>
      {note && (
        <span className="font-mono text-label font-normal text-fg-muted">
          {note}
        </span>
      )}
    </div>
  );
}

/** Page frame for a board. */
export function Board({children}: {children: ReactNode}) {
  return (
    <div className="mx-auto flex w-full max-w-[90rem] flex-col gap-11 px-4 py-10 sm:px-16 sm:py-14">
      {children}
    </div>
  );
}
