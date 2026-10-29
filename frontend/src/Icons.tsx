const paths: Record<string, React.ReactNode> = {
  book: <><path d="M5 3h14a1 1 0 0 1 1 1v17H6a3 3 0 0 1-3-3V5a2 2 0 0 1 2-2Z"/><path d="M7 3v14M3 18h17M10 7h6M10 11h6"/></>,
  database: <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/></>,
  settings: <><path d="m10 3-1 3-3 1-3 3 2 2-1 3 3 3 3-1 2 2 3-1 1-3 3-2-1-4-3-1-1-3Z"/><circle cx="12" cy="11" r="3"/></>,
  mcp: <><circle cx="6" cy="12" r="3"/><circle cx="18" cy="5" r="3"/><circle cx="18" cy="19" r="3"/><path d="m9 11 6-4M9 13l6 4"/></>,
  search: <><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/></>,
  plus: <path d="M12 4v16M4 12h16"/>,
  refresh: <><path d="M20 7V3l-4 2M4 17v4l4-2M20 7A8 8 0 0 0 5 6M4 17a8 8 0 0 0 15 1"/></>,
  monitor: <><rect x="3" y="3" width="18" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></>,
  close: <path d="m6 6 12 12M6 18 18 6"/>,
  chevron: <path d="m6 9 6 6 6-6"/>,
  check: <path d="m5 12 4 4L19 6"/>,
  folder: <path d="M3 6h7l2 2h9v12H3ZM3 6V4h7l2 2"/>,
  more: <><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></>,
  copy: <><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/></>,
};
export function Icon({name, size = 19, className = ''}: {name: string; size?: number; className?: string}) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className}>{paths[name] ?? paths.book}</svg>;
}
