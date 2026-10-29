import {date, type Job} from './types';
import {Empty, Status} from './ui';

const kinds: Record<string, string> = {ingest: '文档导入', reindex: '重建索引', export: '导出', import: '恢复', benchmark: '解析测试'};
function resultOf(job: Job): Record<string, unknown> {
  try {
    const value = JSON.parse(job.result || '{}');
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  } catch {return {};}
}
function details(job: Job, result: Record<string, unknown>): string {
  if (job.error) return job.error;
  if (job.status === 'queued') return '等待处理';
  if (job.status === 'cancelled') return '已取消';
  if (result.stage === 'extracting') return typeof result.total_pages === 'number'
    ? `正在解析：${result.completed_pages ?? 0} / ${result.total_pages} 页` : '正在解析文档';
  if (result.stage === 'embedding') return `正在向量化：${result.completed_chunks ?? 0} / ${result.total_chunks ?? '?'} 个切片`;
  if (result.stage === 'publishing') return '正在保存索引';
  if (result.status === 'unchanged') return '文件未变化，已跳过';
  if (result.status === 'duplicate') return '已存在相同文件，已去重';
  if (result.status === 'deleted') return '文档已移除';
  const counts = [typeof result.pages === 'number' ? `${result.pages} 页` : '',
    typeof result.chunks === 'number' ? `${result.chunks} 个切片` : '',
    typeof result.documents === 'number' ? `${result.documents} 份文档` : ''].filter(Boolean);
  if (job.status === 'done') return counts.length ? `处理完成 · ${counts.join(' · ')}` : '处理完成';
  if (result.interrupted) return '已保存检查点，等待继续';
  return job.status === 'running' ? '正在处理' : '处理失败';
}
export function JobHistory({jobs}: {jobs: Job[]}) {
  return <div className="table-wrap"><table className="job-table"><thead><tr><th>文件名 / 任务</th><th>状态</th><th>详情</th><th>更新时间</th></tr></thead><tbody>{jobs.map(job => {
    const result = resultOf(job);
    const name = job.filename || (typeof result.document === 'string' ? result.document : '')
      || (job.kind === 'reindex' ? '全部文档' : kinds[job.kind] || '知识库任务');
    return <tr key={job.id}><td className="job-filename" title={job.source_path || undefined}><strong>{name}</strong>
      <small className="block muted">{kinds[job.kind] || '知识库任务'} · 尝试 {job.attempts} 次</small></td>
      <td><Status value={job.status}/></td><td className="job-detail">{details(job, result)}</td><td className="nowrap">{date(job.updated)}</td></tr>;
  })}</tbody></table>{!jobs.length ? <Empty>暂无任务记录</Empty> : null}</div>;
}
