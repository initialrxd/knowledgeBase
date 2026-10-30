import {useRef, useState, type FormEvent} from 'react';
import {api} from './api';
import {Field} from './ui';
import {SearchTimings, type SearchTimingSample, type SearchTimingsMs} from './SearchTimings';
import type {Embedding, KnowledgeBase, LibraryTuning, RetrievalTuning, Run} from './types';

type SearchResult = {results: {id: string; title: string; text: string; citation: string}[]; warnings: string[];
  timings_ms?: Partial<SearchTimingsMs> | null};

function SearchTest({kb, busy, tuning, validate}: {kb: KnowledgeBase; busy: boolean; tuning: RetrievalTuning; validate: () => boolean}) {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<SearchResult | null>(null);
  const [samples, setSamples] = useState<SearchTimingSample[]>([]);
  const [repetitions, setRepetitions] = useState(5);
  const [completed, setCompleted] = useState(0);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [tested, setTested] = useState('');
  const draftKey = JSON.stringify([tuning.search_mode, tuning.search_limit, tuning.search_category, tuning.search_document_id, query, repetitions]);
  const average = samples.length ? (samples.reduce((sum, sample) => sum + sample.duration_ms, 0) / samples.length).toFixed(1) : null;
  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (running || !validate()) return;
    setRunning(true); setError(''); setResult(null); setSamples([]); setCompleted(0); setTested(draftKey);
    const request = {query, mode: tuning.search_mode, limit: tuning.search_limit,
      category: tuning.search_category, document_id: tuning.search_document_id};
    const durations: SearchTimingSample[] = [];
    const warnings = new Set<string>();
    let found: SearchResult | null = null;
    try {
      for (let index = 0; index < repetitions; index++) {
        const started = performance.now();
        found = await api(`knowledge-bases/${kb.id}/search`, request) as SearchResult;
        durations.push({duration_ms: performance.now() - started, timings_ms: found.timings_ms});
        found.warnings.forEach(warning => warnings.add(warning));
        setCompleted(index + 1);
      }
      if (found) {setResult({...found, warnings: [...warnings]}); setSamples(durations);}
    } catch (e) {setError(`第 ${durations.length + 1}/${repetitions} 次检索失败，本轮未生成平均耗时：${(e as Error).message}`);}
    finally {setRunning(false);}
  }
  return <section className="search-test"><h3>检索测试</h3>
    <p className="hint">仅查询当前知识库“{kb.name}”，使用上方当前填写的检索参数，无需先保存。测试不会更改系统默认值；点击“保存检索配置”后才应用到后续系统查询。混合或向量模式会调用 Embedding API。</p>
    <p className="hint">使用相同参数连续检索 2–10 次，全部成功后计算平均耗时（含首次请求、网络及服务处理），展示最后一次的片段。混合或向量模式每次都会请求 Embedding API；中途失败时本轮不显示平均值。</p>
    <form onSubmit={search}><div className="inline-form"><input aria-label="测试问题" value={query} maxLength={8000} required disabled={running} placeholder="输入问题，对比检索结果与平均耗时" onChange={e => setQuery(e.target.value)}/><button disabled={busy || running || kb.runtime !== 'running'}>{running ? `检索中 ${completed}/${repetitions}` : '测试检索'}</button></div>
      <div className="test-repetitions"><Field label="测试次数" hint="仅用于本次测试，不保存到系统配置。"><input type="number" min={2} max={10} step={1} required disabled={running} value={repetitions} onChange={e => setRepetitions(Number(e.target.value))}/></Field></div>
    </form>
    {kb.runtime !== 'running' ? <p className="hint">先启动当前知识库，再测试检索。</p> : null}
    {error ? <p role="alert" className="form-error">{error}</p> : null}
    {result ? <div aria-live="polite">{tested !== draftKey ? <p className="hint" role="status">检索参数、问题或测试次数已修改，下方是上次测试结果，请重新测试。</p> : null}<p className="hint">返回 {result.results.length} 条 · 平均耗时 {average} ms（连续 {samples.length} 次成功检索）</p>
      <SearchTimings samples={samples}/>
      {result.warnings.map((warning, index) => <p className="form-error" key={index}>{warning}</p>)}
      {!result.results.length ? <p>没有找到匹配资料，可检查分类或文档范围。</p> : result.results.map(row => <article className="search-result" key={row.id}><strong>{row.title}</strong><p>{row.text}</p><small className="muted">{row.citation}</small></article>)}
    </div> : null}
  </section>;
}

export function LibrarySettings({kb, profile, run, busy, navigate}: {kb: KnowledgeBase; profile?: Embedding; run: Run; busy: boolean; navigate: (page: string) => void}) {
  const [value, setValue] = useState<LibraryTuning>(kb.tuning);
  const [error, setError] = useState({ingestion: '', retrieval: ''});
  const [saved, setSaved] = useState({ingestion: false, retrieval: false});
  const retrievalForm = useRef<HTMLFormElement>(null);
  const overlapInvalid = value.chunk_overlap >= value.chunk_tokens;
  function change<K extends keyof LibraryTuning>(key: K, next: LibraryTuning[K]) {
    const scope = key.startsWith('search_') ? 'retrieval' : 'ingestion';
    setValue(previous => ({...previous, [key]: next}));
    setSaved(previous => ({...previous, [scope]: false})); setError(previous => ({...previous, [scope]: ''}));
  }
  async function save(event: FormEvent<HTMLFormElement>, scope: 'ingestion' | 'retrieval') {
    event.preventDefault(); setError(previous => ({...previous, [scope]: ''})); setSaved(previous => ({...previous, [scope]: false}));
    if (scope === 'ingestion' && overlapInvalid) {setError(previous => ({...previous, ingestion: '重叠长度必须小于切片长度'})); return;}
    const patch = Object.fromEntries(Object.entries(value).filter(([key]) => key.startsWith('search_') === (scope === 'retrieval')));
    try {await run(`knowledge-bases/${kb.id}/tuning/${scope}`, patch, 'PUT'); setSaved(previous => ({...previous, [scope]: true}));}
    catch (e) {setError(previous => ({...previous, [scope]: (e as Error).message}));}
  }
  return <div className="tab-content library-settings">
    <div className="callout quiet">入库与检索配置分别保存。调整检索参数后可直接在下方测试，保存后才更新系统默认值。保存时运行中的库会等待当前批次完成后重启。</div>
    <form onSubmit={event => save(event, 'ingestion')}><fieldset disabled={busy} className="settings-fieldset"><legend>向量化配置</legend>
      <div className="settings-summary"><span>Embedding 批大小 <strong>{profile?.batch_size ?? '—'}</strong> · {profile?.name || '尚未配置'}</span><button type="button" className="text-button" onClick={() => navigate('embedding')}>调整批大小</button></div>
      <p className="hint">批大小由共享 Embedding 配置管理，可先试 16，再试 32；关联该配置的知识库都会受影响。</p>
      <div className="form-grid">
        <Field label="切片长度（token）" hint="64–8000。增大可减少片段数，但可能降低精确定位能力。"><input type="number" min={64} max={8000} step={1} required value={value.chunk_tokens} onChange={e => change('chunk_tokens', Number(e.target.value))}/></Field>
        <Field label="重叠长度（token）" hint="必须小于切片长度。减少重叠可减少重复处理。"><input type="number" min={0} max={value.chunk_tokens - 1} step={1} required aria-invalid={overlapInvalid} value={value.chunk_overlap} onChange={e => change('chunk_overlap', Number(e.target.value))}/></Field>
        <Field label="OCR 模式" hint="关闭后，扫描页中的文字可能无法进入知识库。"><select value={value.ocr_mode} onChange={e => change('ocr_mode', e.target.value as LibraryTuning['ocr_mode'])}><option value="auto">按需识别（推荐）</option><option value="off">关闭 OCR</option><option value="force">强制识别每页</option></select></Field>
        <Field label="PDF 版面提取" hint="原生文字读取更快；结构化提取适合表格和复杂版面。"><select value={value.pdf_layout} onChange={e => change('pdf_layout', e.target.value as LibraryTuning['pdf_layout'])}><option value="native">原生文字</option><option value="structured">结构化版面</option></select></Field>
        <Field label="API 并发上限" hint="1–16。用于并发请求；当前入库批次仍逐批执行。"><input type="number" min={1} max={16} step={1} required value={value.api_concurrency} onChange={e => change('api_concurrency', Number(e.target.value))}/></Field>
        <Field label="识别插图中的文字" hint="开启后增加图片区域 OCR 耗时；不解析图中的连接关系。"><select value={String(value.ocr_image_regions)} onChange={e => change('ocr_image_regions', e.target.value === 'true')}><option value="false">关闭</option><option value="true">开启</option></select></Field>
      </div>
      <p className="hint">切片、版面或 OCR 参数用于后续新增或更新的文档。已有且未变化的资料需重新导入才能重新切片，可能产生 Embedding 费用；扫描和“重建向量索引”不会重新切片这些资料。</p>
    </fieldset>
    {overlapInvalid || error.ingestion ? <p className="form-error" role="alert">{error.ingestion || '重叠长度必须小于切片长度'}</p> : null}
    <div className="settings-actions"><button className="primary" disabled={busy || overlapInvalid}>保存入库配置</button>{saved.ingestion ? <span className="settings-saved" role="status">入库配置已保存</span> : null}</div>
    </form>
    <form ref={retrievalForm} className="retrieval-settings" onSubmit={event => save(event, 'retrieval')}><fieldset disabled={busy} className="settings-fieldset"><legend>检索配置</legend>
      <p className="hint">可先修改并测试，确认效果后点击“保存检索配置”。保存后用于 HTTP / MCP 和内置问答中未显式指定的参数。</p>
      <div className="form-grid">
        <Field label="检索模式" hint="关键词模式跳过云端问题向量化；混合模式兼顾语义与术语。"><select value={value.search_mode} onChange={e => change('search_mode', e.target.value as LibraryTuning['search_mode'])}><option value="hybrid">混合检索（推荐）</option><option value="keyword">仅关键词（更快）</option><option value="vector">仅向量</option></select></Field>
        <Field label="返回片段数" hint="1–50。可从 10 调至 5；数量减少可能影响召回。"><input type="number" min={1} max={50} step={1} required value={value.search_limit} onChange={e => change('search_limit', Number(e.target.value))}/></Field>
        <Field label="默认分类范围" hint="包含子分类；留空查询全部分类。"><input maxLength={1000} value={value.search_category} placeholder="例如：雷达/校准" onChange={e => change('search_category', e.target.value)}/></Field>
        <Field label="默认文档 ID" hint="32 位小写十六进制 ID；留空查询全部文档。"><input pattern="[a-f0-9]{32}" maxLength={32} value={value.search_document_id} placeholder="留空表示不限定文档" onChange={e => change('search_document_id', e.target.value)}/></Field>
      </div>
      <p className="hint">当前设置属于“{kb.name}”。多库 MCP 如需仅查询此库，可传 knowledge_base_id：<code className="break-path">{kb.id}</code>。分类与文档同时填写时取交集；调用时传空字符串可清除对应默认范围。</p>
    </fieldset>
    {error.retrieval ? <p className="form-error" role="alert">{error.retrieval}</p> : null}
    <div className="settings-actions"><button className="primary" disabled={busy}>保存检索配置</button>{saved.retrieval ? <span className="settings-saved" role="status">检索配置已保存</span> : null}</div>
    </form>
    <SearchTest kb={kb} busy={busy} tuning={value} validate={() => retrievalForm.current?.reportValidity() ?? false}/>
  </div>;
}
