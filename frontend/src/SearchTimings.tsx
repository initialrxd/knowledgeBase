export type SearchTimingsMs = {
  total_ms: number;
  embedding_ms: number | null;
  keyword_ms: number | null;
  vector_ms: number | null;
  results_ms: number | null;
  other_ms: number;
};

export type SearchTimingSample = {duration_ms: number; timings_ms?: Partial<SearchTimingsMs> | null};

const metrics = [
  {key: 'duration_ms', label: '总耗时'},
  {key: 'server_ms', label: '服务端处理（汇总）'},
  {key: 'embedding_ms', label: '问题向量化'},
  {key: 'keyword_ms', label: '关键词检索'},
  {key: 'vector_ms', label: '向量检索'},
  {key: 'results_ms', label: '结果整理'},
  {key: 'other_ms', label: '服务端其他处理'},
  {key: 'overhead_ms', label: '请求额外开销'},
] as const;

type Metric = typeof metrics[number]['key'];

function value(sample: SearchTimingSample, key: Metric): number | null | undefined {
  if (key === 'duration_ms') return sample.duration_ms;
  if (key === 'overhead_ms') {
    const server = value(sample, 'server_ms');
    return typeof server === 'number' ? Math.max(0, sample.duration_ms - server) : undefined;
  }
  const measured = sample.timings_ms?.[key === 'server_ms' ? 'total_ms' : key];
  if (measured === null && key !== 'server_ms' && key !== 'other_ms') return null;
  return typeof measured === 'number' && Number.isFinite(measured) && measured >= 0 ? measured : undefined;
}

function format(measured: number | null | undefined) {
  return measured === undefined ? '不可用' : measured === null ? '未执行' : `${measured.toFixed(1)} ms`;
}

function average(samples: SearchTimingSample[], key: Metric) {
  const values = samples.map(sample => value(sample, key));
  if (!values.length || values.some(measured => measured === undefined)) return '不可用';
  const skipped = values.filter(measured => measured === null).length;
  if (skipped === values.length) return '未执行';
  const total = values.reduce<number>((sum, measured) => sum + (measured ?? 0), 0);
  return `${format(total / values.length)}${skipped ? `（跳过 ${skipped}/${values.length} 次）` : ''}`;
}

export function SearchTimings({samples}: {samples: SearchTimingSample[]}) {
  return <>
    <table className="timing-averages">
      <caption>各阶段平均耗时</caption>
      <thead><tr><th scope="col">阶段</th><th scope="col">平均耗时</th></tr></thead>
      <tbody>{metrics.map(metric => <tr key={metric.key}><th scope="row">{metric.label}</th><td>{average(samples, metric.key)}</td></tr>)}</tbody>
    </table>
    <p className="hint">服务端处理为各内部阶段之和，仅作汇总。请求额外开销包含管理台转发、传输、响应序列化及浏览器解析；问题向量化包含接口等待与重试。跳过的阶段按零计入整轮平均，全部跳过显示“未执行”；服务未返回的计时显示“不可用”。</p>
    <details className="timing-samples"><summary>查看每次耗时</summary>
      <div className="timing-scroll" tabIndex={0} role="region" aria-label="每次耗时明细，可横向滚动">
        <table className="timing-details"><caption>每次检索耗时</caption>
          <thead><tr><th scope="col">次数</th>{metrics.map(metric => <th scope="col" key={metric.key}>{metric.label}</th>)}</tr></thead>
          <tbody>{samples.map((sample, index) => <tr key={index}><th scope="row">第 {index + 1} 次</th>{metrics.map(metric => <td key={metric.key}>{format(value(sample, metric.key))}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </details>
  </>;
}
