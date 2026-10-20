import {
  useId,
  useState,
  type FormEvent,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from 'react';

import {cx} from '../lib/cx';
import {Button} from './button';
import {ChevronDownIcon, ErrorIcon, SearchIcon} from './icons';

const CONTROL =
  'h-10 rounded-control border border-border-control bg-surface text-fg';

interface FieldFrameProps {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  /** Schema path in mono, e.g. "policy-document v3 · effective_date". */
  meta?: string;
  children: ReactNode;
}

/** Label above, then the control, then the error or hint below. */
function FieldFrame({id, label, error, hint, meta, children}: FieldFrameProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-label">
        {label}
      </label>
      {children}
      {error && (
        <span
          id={`${id}-error`}
          className="flex items-start gap-1.5 text-label font-normal text-danger-fg"
        >
          <ErrorIcon size={14} className="mt-px shrink-0" />
          {error}
        </span>
      )}
      {hint && !error && (
        <span
          id={`${id}-hint`}
          className="text-label font-normal text-fg-muted"
        >
          {hint}
        </span>
      )}
      {meta && (
        <span className="font-mono text-[0.6875rem] leading-4 text-fg-muted">
          {meta}
        </span>
      )}
    </div>
  );
}

function describedBy(id: string, error?: string, hint?: string) {
  if (error) return `${id}-error`;
  if (hint) return `${id}-hint`;
  return undefined;
}

type TextFieldProps = Omit<FieldFrameProps, 'id' | 'children'> &
  InputHTMLAttributes<HTMLInputElement>;

export function TextField({
  label,
  error,
  hint,
  meta,
  id: givenId,
  className,
  ...input
}: TextFieldProps) {
  const fallbackId = useId();
  const id = givenId ?? fallbackId;
  return (
    <FieldFrame id={id} label={label} error={error} hint={hint} meta={meta}>
      <input
        id={id}
        type="text"
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, error, hint)}
        className={cx(
          CONTROL,
          'px-3 text-body',
          error && 'border-[1.5px] border-danger-fg',
          className,
        )}
        {...input}
      />
    </FieldFrame>
  );
}

type SelectFieldProps = Omit<FieldFrameProps, 'id' | 'children'> &
  SelectHTMLAttributes<HTMLSelectElement> & {
    options: string[];
  };

/** A select whose options are identifiers, so they are set in mono. */
export function SelectField({
  label,
  error,
  hint,
  meta,
  options,
  id: givenId,
  className,
  ...select
}: SelectFieldProps) {
  const fallbackId = useId();
  const id = givenId ?? fallbackId;
  return (
    <FieldFrame id={id} label={label} error={error} hint={hint} meta={meta}>
      <select
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, error, hint)}
        className={cx(CONTROL, 'px-2.5 font-mono text-code', className)}
        {...select}
      >
        {options.map(option => (
          <option key={option}>{option}</option>
        ))}
      </select>
    </FieldFrame>
  );
}

/** The question box. Submits the trimmed question; empty input is ignored. */
export function AskBar({
  placeholder = 'Ask about policies, contracts or records',
  scopeLabel,
  onScope,
  onAsk,
  className,
}: {
  placeholder?: string;
  /** Shows a scope button, e.g. "Scope · 3 collections". */
  scopeLabel?: string;
  onScope?: () => void;
  onAsk: (question: string) => void;
  className?: string;
}) {
  const [question, setQuestion] = useState('');

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) return;
    onAsk(trimmed);
    setQuestion('');
  }

  return (
    <form
      role="search"
      onSubmit={submit}
      className={cx(
        'flex h-14 items-center gap-2.5 rounded-panel border border-border-control bg-surface pr-2 pl-4',
        'focus-within:border-action focus-within:shadow-[0_0_0_3px_var(--rf-cobalt-100)] dark:focus-within:shadow-[0_0_0_3px_var(--rf-cobalt-900)]',
        className,
      )}
    >
      <SearchIcon className="shrink-0 text-fg-muted" />
      <input
        type="text"
        aria-label="Ask a question"
        placeholder={placeholder}
        value={question}
        onChange={event => setQuestion(event.target.value)}
        className="h-10 min-w-0 grow bg-transparent text-[0.9375rem] text-fg placeholder:text-fg-muted focus-visible:outline-none"
      />
      {scopeLabel && (
        <button
          type="button"
          onClick={onScope}
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-control border border-border-control bg-bg px-2.5 text-label whitespace-nowrap text-fg-secondary hover:bg-surface-sunken"
        >
          {scopeLabel}
          <ChevronDownIcon size={12} />
        </button>
      )}
      <Button type="submit" variant="primary">
        Ask
      </Button>
    </form>
  );
}
