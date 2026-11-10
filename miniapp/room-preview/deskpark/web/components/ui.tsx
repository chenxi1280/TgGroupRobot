import { X } from 'lucide-react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { useEffect, useState } from 'react';

type Variant = 'primary' | 'secondary' | 'ghost' | 'gold' | 'danger' | 'felt' | 'felt-primary';

export function Button({
  variant = 'secondary',
  size = 'md',
  block,
  className = '',
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: 'sm' | 'md' | 'lg';
  block?: boolean;
}) {
  return (
    <button
      className={`btn btn--${variant} btn--${size} ${block ? 'btn--block' : ''} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

export function IconButton({
  label,
  className = '',
  children,
  active,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean }) {
  return (
    <button
      className={`iconbtn ${active ? 'is-active' : ''} ${className}`}
      aria-label={label}
      title={label}
      {...rest}
    >
      {children}
    </button>
  );
}

/** 底部弹出面板（移动端）/ 居中对话框（桌面端） */
export function Sheet({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  tone = 'paper',
  dismissible = true,
  wide,
}: {
  open: boolean;
  onClose?: () => void;
  title?: ReactNode;
  subtitle?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  tone?: 'paper' | 'felt';
  dismissible?: boolean;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open || !dismissible) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose?.();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, dismissible, onClose]);
  if (!open) return null;
  return (
    <div className={`sheet-backdrop tone-${tone}`} onClick={() => dismissible && onClose?.()}>
      <div
        className={`sheet ${wide ? 'sheet--wide' : ''}`}
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        {(title || (dismissible && onClose)) && (
          <header className="sheet__head">
            <div>
              {title && <h2 className="sheet__title">{title}</h2>}
              {subtitle && <p className="sheet__subtitle">{subtitle}</p>}
            </div>
            {dismissible && onClose && (
              <button className="sheet__close" onClick={onClose} aria-label="关闭">
                <X size={18} />
              </button>
            )}
          </header>
        )}
        <div className="sheet__body">{children}</div>
        {footer && <footer className="sheet__foot">{footer}</footer>}
      </div>
    </div>
  );
}

export function Segmented<T extends string | number | boolean>({
  value,
  options,
  onChange,
  disabled,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
  disabled?: boolean;
}) {
  return (
    <div className={`segmented ${disabled ? 'is-disabled' : ''}`} role="radiogroup">
      {options.map((o) => (
        <button
          key={String(o.value)}
          role="radio"
          aria-checked={o.value === value}
          className={o.value === value ? 'is-on' : ''}
          onClick={() => !disabled && onChange(o.value)}
          disabled={disabled}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      className={`switch ${checked ? 'is-on' : ''}`}
      onClick={() => !disabled && onChange(!checked)}
      disabled={disabled}
    >
      <span />
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <div className="field__label">
        <span>{label}</span>
        {hint && <small>{hint}</small>}
      </div>
      <div className="field__control">{children}</div>
    </div>
  );
}

/** 轻提示 */
let pushToast: ((msg: string, tone?: 'info' | 'error') => void) | null = null;
export function toast(msg: string, tone: 'info' | 'error' = 'info') {
  pushToast?.(msg, tone);
}

export function ToastHost() {
  const [items, setItems] = useState<{ id: number; msg: string; tone: string }[]>([]);
  useEffect(() => {
    let seq = 0;
    pushToast = (msg, tone = 'info') => {
      const id = ++seq;
      setItems((list) => [...list.filter((x) => x.msg !== msg), { id, msg, tone }].slice(-3));
      window.setTimeout(() => setItems((list) => list.filter((x) => x.id !== id)), 2400);
    };
    return () => {
      pushToast = null;
    };
  }, []);
  return (
    <div className="toasts" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast tone-${t.tone}`}>
          {t.msg}
        </div>
      ))}
    </div>
  );
}
