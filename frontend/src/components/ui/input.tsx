import { clsx } from "clsx";

type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  label: string;
};

export function Input({ className, id, label, ...props }: InputProps) {
  const inputId = id ?? props.name;
  return (
    <label className="grid min-w-0 gap-2 text-sm font-medium text-ink" htmlFor={inputId}>
      {label}
      <input
        id={inputId}
        className={clsx(
          "min-h-11 w-full min-w-0 rounded-lg border border-line bg-white/[0.06] px-3 text-sm text-ink outline-none transition placeholder:text-slate-500 disabled:cursor-not-allowed disabled:opacity-50 focus:border-brand-500/70 focus:ring-4 focus:ring-brand-100",
          className,
        )}
        {...props}
      />
    </label>
  );
}
