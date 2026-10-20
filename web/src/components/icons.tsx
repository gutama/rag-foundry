/**
 * Assay icons: 1.5px strokes on a 16px or 20px grid, drawn in currentColor.
 * Every icon is decorative; the control or label beside it carries the name.
 */

import type {ReactNode} from 'react';

interface IconProps {
  /** Rendered width and height in px. */
  size?: number;
  className?: string;
}

const STROKE = {
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const;

function Svg(props: IconProps & {viewBox: string; children: ReactNode}) {
  return (
    <svg
      width={props.size}
      height={props.size}
      viewBox={props.viewBox}
      fill="none"
      aria-hidden="true"
      className={props.className}
    >
      {props.children}
    </svg>
  );
}

export function SearchIcon({size = 20, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 20 20">
      <circle cx="9" cy="9" r="5.75" {...STROKE} />
      <path d="M13.25 13.25L17 17" {...STROKE} />
    </Svg>
  );
}

export function ArrowRightIcon({size = 16, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <path d="M3 8h9.5M8.75 4.25L12.5 8l-3.75 3.75" {...STROKE} />
    </Svg>
  );
}

export function ChevronDownIcon({size = 16, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <path d="M4 6l4 4 4-4" {...STROKE} />
    </Svg>
  );
}

export function ChevronLeftIcon({size = 16, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <path d="M10 4L6 8l4 4" {...STROKE} />
    </Svg>
  );
}

export function ChevronRightIcon({size = 16, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <path d="M6 4l4 4-4 4" {...STROKE} />
    </Svg>
  );
}

export function CheckIcon({size = 12, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <path d="M3.5 8.5l3 3 6-6.5" {...STROKE} strokeWidth={1.75} />
    </Svg>
  );
}

export function SpinnerIcon({size = 16, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <circle
        cx="8"
        cy="8"
        r="5.75"
        stroke="currentColor"
        strokeOpacity={0.35}
        strokeWidth={1.75}
      />
      <path
        d="M8 2.25a5.75 5.75 0 0 1 5.75 5.75"
        stroke="currentColor"
        strokeWidth={1.75}
        strokeLinecap="round"
      />
    </Svg>
  );
}

export function InfoIcon({size = 16, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <circle cx="8" cy="8" r="6.25" {...STROKE} />
      <path d="M8 7.25V11" {...STROKE} />
      <circle cx="8" cy="5.1" r="0.85" fill="currentColor" />
    </Svg>
  );
}

export function WarningIcon({size = 16, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <path d="M8 2.25L14.25 13H1.75z" {...STROKE} />
      <path d="M8 6.5v3" {...STROKE} />
      <circle cx="8" cy="11.25" r="0.85" fill="currentColor" />
    </Svg>
  );
}

export function ErrorIcon({size = 16, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <path
        d="M5.5 1.75h5l3.75 3.75v5l-3.75 3.75h-5L1.75 10.5v-5z"
        {...STROKE}
      />
      <path d="M8 5v3.5" {...STROKE} />
      <circle cx="8" cy="10.9" r="0.85" fill="currentColor" />
    </Svg>
  );
}

export function CandidateIcon({size = 14, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <circle cx="8" cy="8" r="6.25" {...STROKE} strokeDasharray="2.4 2.4" />
    </Svg>
  );
}

export function ValidatedIcon({size = 14, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <circle cx="8" cy="8" r="6.25" {...STROKE} />
      <path d="M8 1.75a6.25 6.25 0 0 1 0 12.5z" fill="currentColor" />
    </Svg>
  );
}

export function ApprovedIcon({size = 14, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <circle cx="8" cy="8" r="6.25" {...STROKE} />
      <path d="M5.25 8.25l1.9 1.9 3.6-3.9" {...STROKE} />
    </Svg>
  );
}

export function RejectedIcon({size = 14, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <circle cx="8" cy="8" r="6.25" {...STROKE} />
      <path d="M5.75 5.75l4.5 4.5M10.25 5.75l-4.5 4.5" {...STROKE} />
    </Svg>
  );
}

export function SupersededIcon({size = 14, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <path d="M2.5 8h9.5M9 4.75L12.25 8 9 11.25" {...STROKE} />
      <path d="M14 3v10" {...STROKE} />
    </Svg>
  );
}

export function GroundedIcon({size = 14, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <path
        d="M8 1.75l5.25 2v4c0 3.1-2.2 5.4-5.25 6.5C4.95 13.15 2.75 10.85 2.75 7.75v-4z"
        {...STROKE}
      />
      <path d="M5.6 8.1l1.6 1.6 3.2-3.4" {...STROKE} />
    </Svg>
  );
}

export function AbstainedIcon({size = 14, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 16 16">
      <circle cx="8" cy="8" r="6.25" {...STROKE} />
      <path d="M3.6 12.4l8.8-8.8" {...STROKE} />
    </Svg>
  );
}

export function LockIcon({size = 14, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 20 20">
      <rect x="4" y="8.75" width="12" height="8.5" rx="1.5" {...STROKE} />
      <path d="M6.75 8.75V6.5a3.25 3.25 0 0 1 6.5 0v2.25" {...STROKE} />
    </Svg>
  );
}

export function CollectionsIcon({size = 18, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 20 20">
      <rect x="2.75" y="4.75" width="14.5" height="11.5" rx="1.5" {...STROKE} />
      <path d="M2.75 8.25h14.5" {...STROKE} />
    </Svg>
  );
}

export function SourcesIcon({size = 18, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 20 20">
      <path d="M5 2.75h6.5L15.25 6.5v10.75H5z" {...STROKE} />
      <path d="M11.25 2.75V6.75h4" {...STROKE} />
    </Svg>
  );
}

export function CatalogIcon({size = 18, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 20 20">
      <circle cx="10" cy="4.5" r="2" {...STROKE} />
      <circle cx="4.5" cy="15.5" r="2" {...STROKE} />
      <circle cx="15.5" cy="15.5" r="2" {...STROKE} />
      <path d="M10 6.5v3.5M4.5 13.5V10h11v3.5" {...STROKE} />
    </Svg>
  );
}

export function StewardshipIcon({size = 18, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 20 20">
      <rect x="2.75" y="2.75" width="14.5" height="14.5" rx="2" {...STROKE} />
      <path d="M6 13.5l1.5-6h5l1.5 6z" {...STROKE} />
    </Svg>
  );
}

export function EvalsIcon({size = 18, className}: IconProps) {
  return (
    <Svg size={size} className={className} viewBox="0 0 20 20">
      <path d="M3 15.5l4-5 3.5 3 6.5-8.5" {...STROKE} />
    </Svg>
  );
}

/** Long arrow between lifecycle stages. */
export function FlowArrowIcon({className}: {className?: string}) {
  return (
    <svg
      width="40"
      height="12"
      viewBox="0 0 40 12"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <path d="M1 6h36M32 1.5L37.5 6 32 10.5" {...STROKE} />
    </svg>
  );
}

/** Downward arrow into the rejected state. */
export function FlowDownIcon({className}: {className?: string}) {
  return (
    <svg
      width="16"
      height="28"
      viewBox="0 0 16 28"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <path d="M8 1v24M3.5 20.5L8 26l4.5-5.5" {...STROKE} />
    </svg>
  );
}
