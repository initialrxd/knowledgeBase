export type Job = {id: string; kind: string; status: string; attempts: number; error?: string; result?: string; updated: number};
export type Root = {id: string; path: string; enabled: number};
export type LibraryState = {counts: Record<string, number>; indexed_documents: number; active_profile?: string;
  configured_profile: string; paused: boolean; roots: Root[]; jobs: Job[]; jobs_summary: Record<string, number>;
  last_scan?: {at: number; enqueued: number; errors: string[]}; last_successful_scan?: {at: number}; missing_sources: {path: string}[]};
export type KnowledgeBase = {id: string; name: string; data_dir: string; vector_dir: string; source_dirs?: string[]; embedding_id: string; auto_start: boolean;
  runtime: string; index_status: string; availability: string; reason: string; state: LibraryState | null; checked_at?: number};
export type Embedding = {id: string; name: string; base_url: string; endpoint: string; model: string; dimensions: number;
  revision: string; batch_size: number; key_set: boolean; test_ok: boolean | null; tested_at: number | null;
  test_error?: string; latency_ms?: number; measured_dimensions?: number; knowledge_base_ids: string[]};
export type Mcp = {id: string; name: string; port: number; knowledge_base_ids: string[]; auto_start: boolean;
  runtime: string; availability: string; ready: boolean; url: string; error?: string};
export type ConsoleState = {knowledge_bases: KnowledgeBase[]; embedding_profiles: Embedding[]; mcp_instances: Mcp[];
  checked_at: number; demo_mode: boolean};
export type Run = (path: string, body?: unknown, method?: string) => Promise<unknown>;
export function date(value?: number | null) {return value ? new Date(value * 1000).toLocaleString('zh-CN', {hour12: false}) : '尚无记录';}
