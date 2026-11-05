import {useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {ApiError, api} from './api';
import {Icon} from './Icons';
import {date} from './types';
import {Empty, Field} from './ui';

type Source = {id: string; label: string; path: string};
type LogTail = {status: 'ok' | 'missing' | 'unreadable'; lines: string[]; truncated: boolean; updated_at?: number};
const issue = /\b(?:ERROR|WARN(?:ING)?|CRITICAL|FATAL|Traceback)\b|\b\w+(?:Error|Exception):|失败|异常/i;

export function RuntimeLogs() {
  const [sources, setSources] = useState<Source[]>([]);
  const [source, setSource] = useState('manager.err');
  const [tail, setTail] = useState<LogTail | null>(null);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [follow, setFollow] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const logView = useRef<HTMLPreElement>(null);
  const showLatest = useRef(true);
  const search = query.trim().toLowerCase();
  const {lines, lastMatch, lastIssue, matches} = useMemo(() => {
    let lastMatch = -1, lastIssue = -1, matches = 0;
    const lines = (tail?.lines ?? []).map((text, index) => {
      const match = Boolean(search && text.toLowerCase().includes(search));
      const hasIssue = issue.test(text);
      if (match) {lastMatch = index; matches += 1;}
      if (hasIssue) lastIssue = index;
      return {text, match, hasIssue};
    });
    return {lines, lastMatch, lastIssue, matches};
  }, [tail, search]);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const [available, result] = await Promise.all([
          api('logs', undefined, 'GET', controller.signal),
          api('logs/' + encodeURIComponent(source), undefined, 'GET', controller.signal),
        ]);
        if (controller.signal.aborted) return;
        const view = logView.current;
        showLatest.current = !view || view.scrollHeight - view.clientHeight - view.scrollTop < 8;
        setSources(available);
        setTail(result);
        setError('');
      } catch (e) {
        if (!controller.signal.aborted) setError(e instanceof ApiError ? e.message : '无法读取日志，请检查管理台连接');
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          if (follow) timer = setTimeout(load, 5000);
        }
      }
    }
    void load();
    return () => {controller.abort(); clearTimeout(timer);};
  }, [source, refresh, follow]);

  useLayoutEffect(() => {
    const view = logView.current;
    if (view && showLatest.current) view.scrollTop = view.scrollHeight;
  }, [tail]);

  function jump(index: number) {
    const view = logView.current;
    const line = view?.children[index] as HTMLElement | undefined;
    if (view && line) view.scrollTop = line.offsetTop - view.clientHeight / 3;
  }

  return <section aria-labelledby="logs-title">
    <header className="page-header">
      <div><h1 id="logs-title">运行日志</h1><p>查看本机服务的输出，定位异常并查看前后记录。</p></div>
      <div className="header-actions"><button disabled={loading} onClick={() => {setLoading(true); setRefresh(x => x + 1);}}><Icon name="refresh"/>刷新日志</button></div>
    </header>
    <div className="log-controls">
      <Field label="日志来源"><select value={source} disabled={!sources.length} onChange={e => {
        setTail(null); setError(''); setLoading(true); setSource(e.target.value);
      }}>{sources.length ? sources.map(item => <option key={item.id} value={item.id}>{item.label}</option>)
        : <option value="manager.err">管理台 / MCP · 诊断输出</option>}</select></Field>
      <Field label="关键词"><input type="search" value={query} placeholder="例如 timeout、HTTP 401" onChange={e => setQuery(e.target.value)}
        onKeyDown={e => {if (e.key === 'Enter') jump(lastMatch);}}/></Field>
      <button disabled={lastMatch < 0} onClick={() => jump(lastMatch)}>定位匹配</button>
      <button disabled={lastIssue < 0} onClick={() => jump(lastIssue)}>最近错误或警告</button>
      <label className="check-label"><input type="checkbox" checked={follow} onChange={e => setFollow(e.target.checked)}/>自动刷新（5 秒）</label>
    </div>
    {error ? <div className="callout error-callout" role="alert">{error}{tail ? ' · 以下为上次读取的日志' : ''}</div> : null}
    <div className="table-wrap">
      {lines.length ? <pre ref={logView} className="log-view" aria-label="日志内容" tabIndex={0}>{lines.map((line, i) =>
        <span key={i} className={line.match ? 'log-match' : line.hasIssue ? 'log-issue' : undefined}>{line.text}{'\n'}</span>)}</pre>
        : <Empty icon="logs">{loading ? '正在读取日志…' : tail?.status === 'missing' ? '此来源尚无日志文件。独立服务使用后台启动时会保存输出。'
          : tail?.status === 'unreadable' ? '无法打开此日志文件，请检查本机文件权限。' : tail ? '日志文件暂无内容。' : '暂无可显示的日志。'}</Empty>}
    </div>
    {tail?.status === 'ok' ? <p className="hint log-meta">
      {lines.length} 行 · 日志更新 {date(tail.updated_at)}
      {tail.truncated ? <> · 仅显示文件末尾（最多 1,000 行 / 128 KiB），更早记录见 <code>{sources.find(item => item.id === source)?.path}</code></> : null}
      {search ? ` · ${matches} 行匹配` : ''}
    </p> : null}
  </section>;
}
