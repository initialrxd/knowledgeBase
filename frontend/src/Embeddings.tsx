import {useState, type FormEvent} from 'react';
import {Icon} from './Icons';
import {Confirm, Empty, Field, Modal, PageHeader, SafeButton, Status} from './ui';
import {date, type ConsoleState, type Embedding, type Run} from './types';

function EmbeddingForm({profile, data, run, busy, close}: {profile?: Embedding; data: ConsoleState; run: Run; busy: boolean; close: () => void}) {
  const [error, setError] = useState('');
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    const value = Object.fromEntries(form.entries());
    try {await run('embedding-profiles' + (profile ? '/' + profile.id : ''), {...value, dimensions: Number(value.dimensions), batch_size: Number(value.batch_size)}, profile ? 'PUT' : 'POST'); close();}
    catch (e) {setError((e as Error).message);}
  }
  const affected = data.knowledge_bases.filter(k => k.embedding_id === profile?.id);
  return <Modal title={profile ? '编辑 Embedding 配置' : '新建 Embedding 配置'} onClose={close}><form onSubmit={save}><div className="modal-body">
    <Field label="配置名称"><input name="name" autoFocus required maxLength={100} defaultValue={profile?.name} placeholder="例如：文档 Embedding"/></Field>
    <Field label="API Base URL" hint="OpenAI 兼容地址；如提供商要求，请包含 /v1。"><input type="url" name="base_url" required defaultValue={profile?.base_url} placeholder="https://api.example.com/v1"/></Field>
    <div className="form-grid"><Field label="Endpoint"><input name="endpoint" required defaultValue={profile?.endpoint ?? '/embeddings'}/></Field><Field label="模型名称"><input name="model" required defaultValue={profile?.model} placeholder="提供商的 Embedding 模型 ID"/></Field></div>
    <Field label="API Key" hint={profile?.key_set ? '已设置；留空保留原密钥。' : '密钥仅保存在本机，不会在列表中回显。'}><input name="api_key" type="password" autoComplete="new-password" required={!profile?.key_set} placeholder={profile?.key_set ? '已设置，留空保留' : '输入 API Key'}/></Field>
    <div className="form-grid"><Field label="向量维度" hint="0 表示从响应检测。"><input name="dimensions" type="number" min={0} max={65536} required defaultValue={profile?.dimensions ?? 0}/></Field><Field label="批大小"><input name="batch_size" type="number" min={1} max={256} required defaultValue={profile?.batch_size ?? 8}/></Field></div>
    <Field label="Revision" hint="提供商更换模型版本时，用新 Revision 区分索引。"><input name="revision" required defaultValue={profile?.revision ?? 'default'}/></Field>
    {affected.length ? <div className="callout">此配置被 {affected.map(k => k.name).join('、')} 使用。保存将等待当前批次完成后重启这些库；更换模型参数后请重建索引。</div> : null}
    {error ? <p role="alert" className="form-error">{error}</p> : null}
  </div><div className="modal-footer"><button type="button" onClick={close}>取消</button><button className="primary" disabled={busy}>{busy ? '正在应用配置…' : '保存配置'}</button></div></form></Modal>;
}
export function Embeddings({data, run, busy}: {data: ConsoleState; run: Run; busy: boolean}) {
  const [form, setForm] = useState<Embedding | 'new' | null>(null);
  const [removing, setRemoving] = useState<Embedding | null>(null);
  return <><PageHeader title="Embedding 配置" description="连接模型 API，为不同知识库选择合适的向量模型。"><button className="primary" onClick={() => setForm('new')}><Icon name="plus"/>新建配置</button></PageHeader>
    <div className="callout quiet"><span className="info-dot">i</span>一套配置可供多个知识库使用。连接测试发送一条短文本；更换模型后，各库独立重建索引。</div>
    <div className="table-wrap"><table><thead><tr><th>配置名称 / API</th><th>模型</th><th>维度</th><th>API Key</th><th>连接状态</th><th>关联知识库</th><th>操作</th></tr></thead><tbody>{data.embedding_profiles.map(p => <tr key={p.id}><td><strong>{p.name}</strong><small className="block muted break-path api-url">{p.base_url || '尚未配置地址'}</small></td><td>{p.model || <span className="muted">尚未配置</span>}<small className="block muted">{p.revision}</small></td><td>{p.dimensions || p.measured_dimensions || '自动'}</td><td><span className="secret-mask">{p.key_set ? '••••••••' : '未设置'}</span></td><td><Status value={p.test_ok === null ? 'unknown' : p.test_ok ? 'ready' : 'failed'}/><small className="block muted">{p.tested_at ? date(p.tested_at) : '尚未测试'}</small>{p.test_ok ? <small className="muted">{p.latency_ms} ms</small> : null}</td><td>{data.knowledge_bases.filter(k => k.embedding_id === p.id).map(k => <span className="library-tag" key={k.id}>{k.name}</span>)}{!p.knowledge_base_ids.length ? <span className="muted">未关联</span> : null}</td><td><div className="row-actions"><button className="text-button" onClick={() => setForm(p)}>编辑</button><SafeButton disabled={busy} action={() => run(`embedding-profiles/${p.id}/test`)}>测试</SafeButton><button className="icon-button" title="删除未使用的配置" aria-label={'删除' + p.name} disabled={busy || p.knowledge_base_ids.length > 0} onClick={() => setRemoving(p)}><Icon name="close" size={16}/></button></div></td></tr>)}</tbody></table>{!data.embedding_profiles.length ? <Empty icon="settings">添加第一套 Embedding API 配置</Empty> : null}</div>
    {data.embedding_profiles.filter(p => p.test_ok === false).map(p => <div className="callout error-callout" key={p.id}><strong>{p.name}</strong><span>{p.test_error}</span><button className="text-button" onClick={() => setForm(p)}>检查配置</button></div>)}
    <div className="notes-section"><h3>配置与索引</h3><p>地址、模型、维度或 Revision 变化后，相关知识库会显示“待重建”。重建完成后才发布新索引。</p><p>只更新 API Key 不改变向量索引。所有密钥保存在本机，不包含在知识库迁移包中。</p></div>
    {form ? <EmbeddingForm profile={form === 'new' ? undefined : form} data={data} run={run} busy={busy} close={() => setForm(null)}/> : null}
    {removing ? <Confirm title="删除 Embedding 配置" busy={busy} onClose={() => setRemoving(null)} action={() => run('embedding-profiles/' + removing.id, undefined, 'DELETE')}>删除配置“{removing.name}”？</Confirm> : null}
  </>;
}
