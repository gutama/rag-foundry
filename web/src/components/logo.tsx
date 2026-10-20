import {cx} from '../lib/cx';

/**
 * The RAG Foundry mark: an ingot in a hallmark frame. The ingot fill is the
 * one use of Ingot outside evidence, because the mark is the hallmark.
 */
export function Logo({
  size = 28,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 28 28"
      fill="none"
      aria-hidden="true"
      className={cx('text-fg', className)}
    >
      <rect
        x="1"
        y="1"
        width="26"
        height="26"
        rx="3"
        stroke="currentColor"
        strokeWidth="2"
      />
      <path
        d="M6.5 19.5L9.25 9.5h9.5l2.75 10z"
        className="fill-ingot-400"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}
