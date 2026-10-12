import { ArrowUpRight } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export function Card({ children, className = "", label }: { children: ReactNode; className?: string; label: string }) {
  return <section aria-label={label} className={`card ${className}`}>{children}</section>;
}

export function Button({ children, className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" className={`button ${className}`} {...props}>{children}</button>;
}

export function Badge({ children, subtle = false }: { children: ReactNode; subtle?: boolean }) {
  return <span className={`badge${subtle ? " badge-subtle" : ""}`}>{children}</span>;
}

export function TextAction({ children, onClick, className = "" }: { children: ReactNode; onClick: () => void; className?: string }) {
  return <button type="button" className={`text-action ${className}`} onClick={onClick}><span>{children}</span><ArrowUpRight size={14} /></button>;
}

export function Tabs<T extends string>({ options, value, onChange, label }: { options: readonly T[]; value: T; onChange: (value: T) => void; label: string }) {
  return <div className="tabs" role="group" aria-label={label}>{options.map(option =>
    <button key={option} type="button" aria-pressed={value === option} onClick={() => onChange(option)}>{option}</button>
  )}</div>;
}
