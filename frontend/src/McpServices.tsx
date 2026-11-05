import {useState, type FormEvent} from 'react';
import {Icon} from './Icons';
import {Confirm, Empty, Field, Modal, PageHeader, SafeButton, Status} from './ui';
import type {ConsoleState, Mcp, Run} from './types';

function McpForm({instance, data, run, busy, close}: {instance?: Mcp; data: ConsoleState; run: Run; busy: boolean; close: () => void}) {
  const [error, setError] = useState('');
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    try {
      await run('mcp-instances' + (instance ? '/' + instance.id : ''), {name: form.get('name'), port: Number(form.get('port')), token: form.get('token'),
        knowledge_base_ids: form.getAll('knowledge_base_ids'), auto_start: form.get('auto_start') === 'on'}, instance ? 'PUT' : 'POST'); close();
    } catch (e) {setError((e as Error).message);}
  }
  return <Modal title={instance ? '编辑 MCP 服务' : '新建 MCP 服务'} onClose={close}><form onSubmit={save}><div className="modal-body">
    <div className="form-grid"><Field label="服务名称"><input autoFocus name="name" required maxLength={100} defaultValue={instance?.name} placeholder="例如：技术检索"/></Field><Field label="本机端口"><input name="port" type="number" required min={1024} max={65535} defaultValue={instance?.port ?? 8770}/></Field></div>
    <fieldset className="library-picker"><legend>关联知识库 <span className="muted">可多选</span></legend>{data.knowledge_bases.map(kb => <label key={kb.id}><input name="knowledge_base_ids" value={kb.id} type="checkbox" defaultChecked={instance?.knowledge_base_ids.includes(kb.id) ?? false}/><span>{kb.name}</span><Status value={kb.availability}/></label>)}</fieldset>
    <Field label="访问令牌" hint={instance ? '留空保留当前令牌；修改后需更新客户端配置。' : '留空将自动生成随机令牌。'}><input name="token" type="password" autoComplete="new-password" placeholder={instance ? '已设置，留空保留' : '自动生成安全令牌'}/></Field>
    <label className="check-label"><input name="auto_start" type="checkbox" defaultChecked={instance?.auto_start ?? false}/>随管理台自动启动</label>
    {instance?.runtime === 'running' ? <div className="callout">服务正在运行。保存后自动重启此 MCP；端口或令牌变更后，请重新复制客户端配置。</div> : null}
    <p className="hint">Streamable HTTP 地址为 http://127.0.0.1:端口/mcp。每个令牌仅允许访问所选知识库。</p>
    {error ? <p role="alert" className="form-error">{error}</p> : null}
    </div><div className="modal-footer"><button type="button" onClick={close}>取消</button><button className="primary" disabled={busy || !data.knowledge_bases.length}>{busy ? '正在应用配置…' : instance?.runtime === 'running' ? '保存并重启' : '保存服务'}</button></div></form></Modal>;
}
export function McpServices({data, run, busy}: {data: ConsoleState; run: Run; busy: boolean}) {
  const [form, setForm] = useState<Mcp | 'new' | null>(null);
  const [config, setConfig] = useState(''); const [copied, setCopied] = useState(false);
  const [confirm, setConfirm] = useState<{instance: Mcp; rotate: boolean} | null>(null);
  const action = (instance: Mcp, command: string) => run(`mcp-instances/${instance.id}/actions`, {action: command});
  return <><PageHeader title="MCP 服务" description="配置知识库访问入口、关联范围与独立令牌。"><button className="primary" onClick={() => setForm('new')}><Icon name="plus"/>新建 MCP 服务</button></PageHeader>
    <div className="toolbar"><span className="muted">Streamable HTTP · 本机访问</span><span className="toolbar-note">{data.mcp_instances.filter(m => m.runtime === 'running').length} / {data.mcp_instances.length} 个服务运行中</span></div>
    <div className="table-wrap"><table><thead><tr><th>服务名称 / 地址</th><th>关联知识库</th><th>运行状态</th><th>检索状态</th><th>访问令牌</th><th>操作</th></tr></thead><tbody>{data.mcp_instances.map(m => <tr key={m.id}><td><strong>{m.name}</strong><small className="block muted">{m.url}</small>{m.error ? <small className="block form-error">{m.error}</small> : null}</td><td>{m.knowledge_base_ids.length ? m.knowledge_base_ids.map(id => <span className="library-tag" key={id}>{data.knowledge_bases.find(k => k.id === id)?.name ?? '知识库缺失'}</span>) : <span className="muted">尚未关联知识库</span>}</td><td><Status value={m.runtime}/></td><td><Status value={m.availability}/></td><td><span className="secret-mask">••••••••</span><small className="block muted">独立令牌</small></td><td><div className="row-actions"><SafeButton disabled={busy || (m.runtime !== 'running' && !m.knowledge_base_ids.length)} action={() => action(m, m.runtime === 'running' ? 'stop' : 'start')}>{m.runtime === 'running' ? '停止' : '启动'}</SafeButton><SafeButton disabled={busy || m.runtime !== 'running'} action={() => action(m, 'test')}>测试</SafeButton><button className="text-button" onClick={() => setForm(m)} disabled={busy}>编辑</button></div><div className="row-actions secondary-actions"><SafeButton disabled={busy} action={async () => {const value = await run(`mcp-instances/${m.id}/client-config`); setCopied(false); setConfig(JSON.stringify(value, null, 2));}}>客户端配置</SafeButton><button className="text-button" disabled={m.runtime === 'running' || busy} onClick={() => setConfirm({instance: m, rotate: true})}>更换令牌</button>{m.id !== 'default' ? <button className="text-button danger" disabled={busy} onClick={() => setConfirm({instance: m, rotate: false})}>删除</button> : null}</div></td></tr>)}</tbody></table>{!data.mcp_instances.length ? <Empty icon="mcp">创建一个 MCP 服务，供客户端检索知识库</Empty> : null}</div>
    <div className="notes-section"><h3>运行与检索就绪</h3><p>“运行中”表示 MCP 已监听端口；关联知识库全部就绪后，检索状态才会显示 Ready。</p><p>跨库检索使用各库自己的 Embedding 模型。部分库不可用时，返回可用结果并附带警告。</p><p>名称、端口、知识库范围与令牌均可编辑。运行中保存会自动重启此 MCP，应用失败则恢复原配置。</p></div>
    {form ? <McpForm instance={form === 'new' ? undefined : form} data={data} run={run} busy={busy} close={() => setForm(null)}/> : null}
    {config ? <Modal title="MCP 客户端配置" onClose={() => setConfig('')} wide><div className="modal-body"><div className="callout">此配置包含访问令牌，仅复制到可信客户端。关闭此窗口后不会保留在浏览器存储中。</div><textarea className="config-code" aria-label="客户端配置 JSON" readOnly value={config} onFocus={e => e.target.select()}/><p className="hint">适用于支持 HTTP MCP 的客户端；其他客户端可能需要调整外层配置格式。</p></div><div className="modal-footer"><button onClick={() => setConfig('')}>关闭</button><button className="primary" onClick={() => {void navigator.clipboard.writeText(config).then(() => setCopied(true)).catch(() => setCopied(false));}}><Icon name="copy"/>{copied ? '已复制' : '复制配置'}</button></div></Modal> : null}
    {confirm ? <Confirm title={confirm.rotate ? '更换访问令牌' : '删除 MCP 服务'} busy={busy} onClose={() => setConfirm(null)} action={() => confirm.rotate ? action(confirm.instance, 'rotate_token') : run('mcp-instances/' + confirm.instance.id, undefined, 'DELETE')}>{confirm.rotate ? `更换“${confirm.instance.name}”的令牌后，旧令牌立即失效。请重新复制配置到客户端。` : `删除“${confirm.instance.name}”？关联知识库及数据将保留。`}</Confirm> : null}
  </>;
}
