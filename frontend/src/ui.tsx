import {cloneElement, createContext, useContext, useEffect, useId, useRef, type ReactElement, type ReactNode} from 'react';
import {Icon} from './Icons';
const labels: Record<string, string> = {ready: 'Ready', degraded: '降级可用', not_ready: '未就绪', unknown: '未验证',
  empty: '空库', pending: '待处理', indexing: '处理中', paused: '已暂停', complete: '已完成', stale: '待重建', failed: '失败',
  running: '运行中', stopped: '已停止', starting: '启动中', stopping: '停止中', error: '异常', queued: '排队中', done: '完成', cancelled: '已取消'};
export function Status({value, title}: {value: string; title?: string}) {
  const tone = ['ready', 'complete', 'running', 'done'].includes(value) ? 'green' : ['failed', 'error'].includes(value) ? 'red'
    : ['degraded', 'stale', 'paused'].includes(value) ? 'amber' : ['indexing', 'starting', 'stopping', 'queued'].includes(value) ? 'blue' : 'gray';
  return <span className={'status ' + tone} title={title}><span className={value === 'indexing' || value === 'starting' ? 'status-dot spinner' : 'status-dot'}/>{labels[value] ?? value}</span>;
}
export function Modal({title, children, onClose, wide = false}: {title: string; children: ReactNode; onClose: () => void; wide?: boolean}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {ref.current?.showModal(); return () => ref.current?.close();}, []);
  return <dialog ref={ref} className={wide ? 'modal wide' : 'modal'} onCancel={e => {e.preventDefault(); onClose();}} onClick={e => {if (e.target === ref.current) onClose();}} aria-label={title}>
    <div className="modal-header"><h2>{title}</h2><button type="button" className="icon-button" onClick={onClose} aria-label="关闭"><Icon name="close"/></button></div>{children}</dialog>;
}
export function Field({label, hint, children}: {label: string; hint?: string; children: ReactNode}) {
  const id = useId();
  const control = cloneElement(children as ReactElement<Record<string, unknown>>, {'aria-labelledby': id, 'aria-describedby': hint ? id + '-hint' : undefined});
  return <label className="field"><span id={id}>{label}</span>{control}{hint ? <small id={id + '-hint'}>{hint}</small> : null}</label>;
}
export const RefreshContext = createContext<() => Promise<void>>(async () => {});
export function PageHeader({title, description, children}: {title: string; description: string; children: ReactNode}) {
  const refresh = useContext(RefreshContext);
  return <header className="page-header"><div><h1>{title}</h1><p>{description}</p></div><div className="header-actions"><button onClick={() => {void refresh();}}><Icon name="refresh"/>刷新</button>{children}</div></header>;
}
export function Empty({children, icon = 'database'}: {children: ReactNode; icon?: string}) {
  return <div className="empty"><Icon name={icon} size={30}/><p>{children}</p></div>;
}
export function SafeButton({children, action, className = 'text-button', disabled = false}: {children: ReactNode; action: () => Promise<unknown>; className?: string; disabled?: boolean}) {
  return <button className={className} disabled={disabled} onClick={() => {void action().catch(() => {});}}>{children}</button>;
}
export function Confirm({title, children, action, onClose, busy}: {title: string; children: ReactNode; action: () => Promise<unknown>; onClose: () => void; busy: boolean}) {
  return <Modal title={title} onClose={onClose}><div className="modal-body"><p>{children}</p></div><div className="modal-footer"><button onClick={onClose}>取消</button><SafeButton className="primary" disabled={busy} action={async () => {await action(); onClose();}}>确认{busy ? '处理中…' : ''}</SafeButton></div></Modal>;
}
