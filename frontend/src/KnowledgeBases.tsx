import {useState, type FormEvent} from 'react';
import {Icon} from './Icons';
import {JobHistory} from './JobHistory';
import {LibrarySettings} from './LibrarySettings';
import {Confirm, Empty, Field, Modal, PageHeader, SafeButton, Status} from './ui';
import {date, type ConsoleState, type KnowledgeBase, type Run} from './types';

function sourcePaths(kb: KnowledgeBase) {return kb.state?.roots.map(root => root.path) ?? kb.source_dirs ?? [];}

function Progress({kb}: {kb: KnowledgeBase}) {
  const job = kb.state?.jobs.find(j => j.status === 'running');
  let progress: {completed_chunks?: number; total_chunks?: number; stage?: string; document?: string} = {};
  try {progress = JSON.parse(job?.result || '{}');} catch { /* Old tasks may have no structured result. */ }
  const percentage = progress.total_chunks ? Math.round(100 * (progress.completed_chunks || 0) / progress.total_chunks) : null;
  return <div className="index-cell"><Status value={kb.index_status}/>{kb.index_status === 'indexing' && percentage !== null ? <div className="mini-progress" title="当前文档切片进度"><span style={{width: percentage + '%'}}/></div> : null}{kb.index_status === 'indexing' && percentage !== null ? <small>{percentage}%</small> : null}</div>;
}

function LibraryForm({kb, data, busy, run, onClose}: {kb?: KnowledgeBase; data: ConsoleState; busy: boolean; run: Run; onClose: () => void}) {
  const [error, setError] = useState('');
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const fields = new FormData(event.currentTarget);
    try {
      await run('knowledge-bases' + (kb ? '/' + kb.id : ''), {name: fields.get('name'), data_dir: fields.get('data_dir'),
        ...(!kb ? {source_dirs: String(fields.get('source_dirs') || '').split(/\r?\n/).map(path => path.trim()).filter(Boolean)} : {}),
        embedding_id: fields.get('embedding_id'), auto_start: fields.get('auto_start') === 'on'}, kb ? 'PUT' : 'POST');
      onClose();
    } catch (e) {setError((e as Error).message);}
  }
  return <Modal title={kb ? '编辑知识库' : '新建知识库'} onClose={onClose}><form onSubmit={save}><div className="modal-body">
    <Field label="知识库名称"><input name="name" autoFocus required maxLength={100} defaultValue={kb?.name} placeholder="例如：技术文档"/></Field>
    {!kb ? <Field label="数据源目录" hint="填写已存在的本机文件夹；多个目录每行一个。保存后自动登记并扫描其中的 PDF。"><textarea name="source_dirs" required rows={3} placeholder={'C:\\Knowledge\\Tech\nD:\\Documents\\Research'}/></Field> : null}
    <Field label="向量化存储目录" hint={kb ? '该目录保存向量、切片及元数据；已有数据迁移请使用导出与恢复。' : '必填，选择空目录或新目录，与数据源分开。向量保存到其 vectors 子目录，切片与元数据也保存在此处。'}><input name="data_dir" required defaultValue={kb?.data_dir} readOnly={!!kb} placeholder="例如 D:\KnowledgeIndexes\Tech"/></Field>
    <Field label="Embedding 配置"><select name="embedding_id" required defaultValue={kb?.embedding_id ?? data.embedding_profiles[0]?.id}>{data.embedding_profiles.map(p => <option key={p.id} value={p.id}>{p.name} · {p.model || '未配置模型'}</option>)}</select></Field>
    <label className="check-label"><input name="auto_start" type="checkbox" defaultChecked={kb?.auto_start ?? true}/>随管理台自动启动</label>
    {kb ? <p className="hint">更换 Embedding 配置后需重建索引。运行中的知识库会先保存当前批次，再应用配置。</p> : null}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
  </div><div className="modal-footer"><button type="button" onClick={onClose}>取消</button><button className="primary" disabled={busy || !data.embedding_profiles.length}>{busy ? '正在保存…' : '保存知识库'}</button></div></form></Modal>;
}

export function KnowledgeBases({data, run, busy, navigate}: {data: ConsoleState; run: Run; busy: boolean; navigate: (page: string) => void}) {
  const [selection, select] = useState(''); const [search, setSearch] = useState(''); const [filter, setFilter] = useState('all');
  const [tab, setTab] = useState('overview'); const [form, setForm] = useState<KnowledgeBase | 'new' | null>(null);
  const [confirm, setConfirm] = useState<{title: string; message: string; action: () => Promise<unknown>} | null>(null);
  const [source, setSource] = useState('');
  const libraries = data.knowledge_bases.filter(k => (k.name + k.data_dir + sourcePaths(k).join(' ')).toLowerCase().includes(search.toLowerCase()) && (filter === 'all' || k.availability === filter));
  const selected = data.knowledge_bases.find(k => k.id === selection) ?? libraries[0];
  const profile = data.embedding_profiles.find(p => p.id === selected?.embedding_id);
  const action = (kb: KnowledgeBase, command: string) => run(`knowledge-bases/${kb.id}/actions`, {action: command});
  function confirmDelete(kb: KnowledgeBase) {
    const linked = data.mcp_instances.filter(m => m.knowledge_base_ids.includes(kb.id));
    const unlink = linked.length ? ` 将解除与 ${linked.map(m => `“${m.name}”`).join('、')} 的关联。解除后没有关联库的 MCP 服务将停止。` : '';
    setConfirm({title: '删除知识库', message: `确定删除“${kb.name}”？知识库将停止并从管理台删除，磁盘上的 PDF、索引和历史数据会保留。${unlink}`,
      action: () => run('knowledge-bases/' + kb.id, undefined, 'DELETE')});
  }
  return <>
    <PageHeader title="知识库" description="管理来源目录、索引与检索状态。"><button className="primary" onClick={() => setForm('new')}><Icon name="plus"/>新建知识库</button></PageHeader>
    <div className="toolbar"><div className="search-input"><Icon name="search"/><input aria-label="搜索知识库" placeholder="搜索知识库名称或目录路径" value={search} onChange={e => setSearch(e.target.value)}/></div><select aria-label="筛选可用状态" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部状态</option><option value="ready">Ready</option><option value="degraded">降级可用</option><option value="not_ready">未就绪</option><option value="unknown">未验证</option></select><span className="toolbar-note">{libraries.length} 个知识库</span></div>
    <div className="table-wrap"><table className="library-table"><thead><tr><th>知识库</th><th>来源目录</th><th>Embedding</th><th>向量化</th><th>可用状态</th><th>操作</th></tr></thead><tbody>{libraries.map(kb => <tr key={kb.id} className={selected?.id === kb.id ? 'selected' : ''}>
      <td><button className="row-name" onClick={() => select(kb.id)}>{kb.name}</button></td><td className="path-cell" title={sourcePaths(kb).join('\n')}>{sourcePaths(kb).length ? <>{sourcePaths(kb)[0]}{sourcePaths(kb).length > 1 ? <small>另有 {sourcePaths(kb).length - 1} 个目录</small> : null}</> : <span className="muted">尚未配置目录</span>}</td>
      <td className="model-cell">{data.embedding_profiles.find(p => p.id === kb.embedding_id)?.model || <span className="muted">尚未配置</span>}</td><td><Progress kb={kb}/></td><td><Status value={kb.availability} title={kb.reason}/></td>
      <td><div className="row-actions"><button className="text-button" onClick={() => {select(kb.id); setTab('overview');}}>查看</button><SafeButton disabled={busy} action={() => action(kb, kb.runtime === 'running' ? kb.index_status === 'failed' ? 'retry' : 'scan' : 'start')}>{kb.runtime === 'running' ? kb.index_status === 'failed' ? '重试' : '扫描' : '启动'}</SafeButton><button className="icon-button" title="编辑知识库" aria-label={'编辑' + kb.name} onClick={() => setForm(kb)}><Icon name="more"/></button><button className="text-button danger" disabled={busy} aria-label={'删除' + kb.name} onClick={() => confirmDelete(kb)}>删除</button></div></td>
    </tr>)}</tbody></table>{!libraries.length ? <Empty>{data.knowledge_bases.length ? '没有匹配的知识库' : '暂无知识库，可新建知识库开始使用'}</Empty> : null}</div>
    {selected ? <section className="detail-panel"><div className="detail-header"><div className="title-with-status"><h2>{selected.name}</h2><Status value={selected.availability}/></div><div className="row-actions"><Status value={selected.runtime}/><button className="icon-button" aria-label="编辑当前知识库" onClick={() => setForm(selected)}><Icon name="more"/></button></div></div>
      <div className="tabs" role="tablist" aria-label="知识库详情">{[['overview', '概览'], ['roots', '来源目录'], ['settings', '入库与检索'], ['jobs', '任务记录']].map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{label}</button>)}</div>
      {tab === 'settings' ? <LibrarySettings key={selected.id} kb={selected} profile={profile} run={run} busy={busy} navigate={navigate}/> : null}
      {tab === 'overview' ? <div className="overview-grid"><div><dl className="metadata"><dt>知识库名称</dt><dd>{selected.name}</dd><dt>数据源目录</dt><dd className="break-path">{sourcePaths(selected).join('；') || '尚未配置'}</dd><dt>向量化存储目录</dt><dd className="break-path">{selected.data_dir}<small className="block muted">实际向量：{selected.vector_dir}</small></dd><dt>Embedding 模型</dt><dd>{profile?.model || '尚未配置'}</dd><dt>当前索引状态</dt><dd><Status value={selected.index_status}/></dd><dt>最后成功扫描</dt><dd>{date(selected.state?.last_successful_scan?.at)}</dd><dt>文档 / 切片</dt><dd>{selected.state ? `${selected.state.counts.live_documents.toLocaleString()} / ${selected.state.counts.chunks.toLocaleString()}` : '启动后可查看'}</dd></dl>
        <p className="availability-reason"><span className="info-dot">i</span>{selected.reason}</p><div className="detail-actions"><SafeButton className="button" disabled={busy} action={() => action(selected, selected.runtime === 'running' ? 'stop' : 'start')}>{selected.runtime === 'running' ? '停止知识库' : '启动知识库'}</SafeButton><SafeButton className="button" disabled={busy || selected.runtime !== 'running'} action={() => action(selected, selected.state?.paused ? 'resume' : 'pause')}>{selected.state?.paused ? '恢复处理' : '暂停处理'}</SafeButton><button disabled={busy || selected.runtime !== 'running'} onClick={() => setConfirm({title: '重建向量索引', message: '将使用当前 Embedding 配置重新生成索引，可能产生 API 费用。新索引完成后才切换，旧索引会保留。', action: () => action(selected, 'reindex')})}>重建索引</button></div>
        <button className="text-button danger detach" disabled={busy} onClick={() => confirmDelete(selected)}>删除知识库</button></div>
        <div className="related"><h3>关联的 MCP 服务</h3><div className="table-wrap"><table><thead><tr><th>服务名称</th><th>端口</th><th>运行状态</th><th>操作</th></tr></thead><tbody>{data.mcp_instances.filter(m => m.knowledge_base_ids.includes(selected.id)).map(m => <tr key={m.id}><td>{m.name}</td><td>{m.port}</td><td><Status value={m.runtime}/></td><td><button className="text-button" onClick={() => navigate('mcp')}>管理服务</button></td></tr>)}</tbody></table>{!data.mcp_instances.some(m => m.knowledge_base_ids.includes(selected.id)) ? <Empty icon="mcp">尚未关联 MCP 服务</Empty> : null}</div><p className="hint">MCP 可关联多个知识库，分别设置访问令牌。</p></div>
      </div> : null}
      {tab === 'roots' ? <div className="tab-content"><form className="inline-form" onSubmit={e => {e.preventDefault(); void run(`knowledge-bases/${selected.id}/roots`, {path: source}).then(() => setSource('')).catch(() => {});}}><input aria-label="来源目录路径" required placeholder="粘贴本机文件夹路径，例如 C:\Knowledge\Tech" value={source} onChange={e => setSource(e.target.value)}/><button className="primary" disabled={busy || selected.runtime !== 'running'}><Icon name="plus"/>添加目录</button></form><p className="hint">目录须已存在，递归监听 PDF 变化。移除来源会保留已导入资料。</p>{selected.state?.roots.map(root => <div className="source-row" key={root.id}><Icon name="folder"/><span className="break-path">{root.path}</span><Status value={root.enabled ? 'running' : 'paused'}/><SafeButton disabled={busy} action={() => run(`knowledge-bases/${selected.id}/roots`, {id: root.id, enabled: !root.enabled})}>{root.enabled ? '停用' : '启用'}</SafeButton><button className="text-button danger" onClick={() => setConfirm({title: '移除来源目录', message: `停止同步 ${root.path}，保留已导入的文档及索引。`, action: () => run(`knowledge-bases/${selected.id}/roots`, {id: root.id, remove: true})})}>移除</button></div>)}{!selected.state?.roots.length ? <Empty icon="folder">{selected.runtime === 'running' ? '添加第一个来源目录，开始构建知识库' : '先启动知识库，再管理来源目录'}</Empty> : null}{selected.state?.last_scan?.errors.map(error => <p key={error} className="form-error">{error}</p>)}</div> : null}
      {tab === 'jobs' ? <div className="tab-content"><div className="section-heading"><p className="hint">最近 50 条任务；总体状态基于完整队列统计。</p><SafeButton disabled={busy || selected.runtime !== 'running'} action={() => action(selected, 'retry')}>重试失败任务</SafeButton></div><JobHistory jobs={selected.state?.jobs ?? []}/></div> : null}
    </section> : null}
    {form ? <LibraryForm kb={form === 'new' ? undefined : form} data={data} busy={busy} run={run} onClose={() => setForm(null)}/> : null}
    {confirm ? <Confirm title={confirm.title} action={confirm.action} busy={busy} onClose={() => setConfirm(null)}>{confirm.message}</Confirm> : null}
  </>;
}
