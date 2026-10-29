import {useState, type FormEvent} from 'react';
import {api, useConsole} from './api';
import {KnowledgeBases} from './KnowledgeBases';
import {Embeddings} from './Embeddings';
import {McpServices} from './McpServices';
import {Icon} from './Icons';
import {RefreshContext} from './ui';
import {date} from './types';

const pages = [{id: 'knowledge', label: '知识库', icon: 'database', path: '/'}, {id: 'embedding', label: 'Embedding 配置', icon: 'settings', path: '/embedding'}, {id: 'mcp', label: 'MCP 服务', icon: 'mcp', path: '/mcp'}];
export function App() {
  const {data, error, login, notice, busy, refresh, run} = useConsole();
  const [page, setPage] = useState(pages.find(p => p.path === location.pathname)?.id ?? 'knowledge');
  const [loginError, setLoginError] = useState('');
  function navigate(id: string) {setPage(id); history.replaceState({}, '', pages.find(p => p.id === id)?.path ?? '/');}
  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget;
    try {await api('login', {token: new FormData(form).get('token')}); form.reset(); await refresh();}
    catch (e) {setLoginError((e as Error).message);}
  }
  return <RefreshContext.Provider value={refresh}><div className="app-shell"><aside className="sidebar"><a className="brand" href="/" onClick={e => {e.preventDefault(); navigate('knowledge');}}><span className="brand-mark"><Icon name="book" size={23}/></span><span>知识库管理台</span></a><nav aria-label="主导航">{pages.map(p => <button key={p.id} aria-current={page === p.id ? 'page' : undefined} className={page === p.id ? 'nav-item active' : 'nav-item'} onClick={() => navigate(p.id)}><Icon name={p.icon} size={22}/>{p.label}</button>)}</nav><div className="sidebar-bottom"><Icon name="monitor"/><span>本机管理 · 127.0.0.1</span></div></aside>
    <main><div className="utility-bar"><span className={'connection ' + (error ? 'offline' : '')}><span className="status-dot"/>{error ? '连接中断 · 显示最后数据' : '本地管理服务运行中'}<span className="host-label"> · 127.0.0.1</span></span></div>
      {login ? <section className="login-panel"><span className="brand-mark large"><Icon name="book" size={30}/></span><h1>连接本机管理台</h1><p>使用启动脚本打开登录链接，或输入现有管理员令牌。</p><form onSubmit={signIn}><label className="field"><span>管理员令牌</span><input type="password" name="token" required autoComplete="current-password" autoFocus placeholder="KB_ADMIN_TOKEN"/></label><button className="primary">登录管理台</button></form>{loginError || error ? <p className="form-error" role="alert">{loginError || error}</p> : null}<p className="hint">按 README 中对应系统的启动命令打开本机登录链接。</p></section> : data ? <><div className="page-content">{error ? <div className="callout error-callout" role="alert">{error} · 最后刷新 {date(data.checked_at)}</div> : null}{data.demo_mode ? <div className="callout">当前为显式测试模式，向量不具备语义检索能力。</div> : null}{page === 'knowledge' ? <KnowledgeBases data={data} run={run} busy={busy > 0} navigate={navigate}/> : page === 'embedding' ? <Embeddings data={data} run={run} busy={busy > 0}/> : <McpServices data={data} run={run} busy={busy > 0}/>}</div><footer className="page-footer"><span>最后刷新 {date(data.checked_at)}</span><span>{busy ? '正在处理操作，请稍候…' : '配置与数据保存在本机'}</span></footer></> : <div className="loading-state"><span className="loading-spinner"/><p>{error || '正在读取知识库配置…'}</p></div>}
    </main>{notice ? <div className="toast" role="status">{notice}</div> : null}</div></RefreshContext.Provider>;
}
