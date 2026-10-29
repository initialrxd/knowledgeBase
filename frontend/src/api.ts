import { useCallback, useEffect, useRef, useState } from 'react';
import type {ConsoleState} from './types';
export class ApiError extends Error {constructor(message: string, public status: number) {super(message);}}
export async function api(path: string, body?: unknown, method = 'POST') {
  const response = await fetch('/manager/api/' + path, {method, credentials: 'same-origin',
    headers: body === undefined ? undefined : {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) {
    const message = typeof result.detail === 'string' ? result.detail : '请检查输入字段';
    throw new ApiError(message, response.status);
  }
  return result;
}
export function useConsole() {
  const [data, setData] = useState<ConsoleState | null>(null);
  const [error, setError] = useState('');
  const [login, setLogin] = useState(false);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(0);
  const pending = useRef(false);
  const mounted = useRef(true);
  const refresh = useCallback(async () => {
    if (pending.current) return;
    pending.current = true;
    try {const result = await api('state', undefined, 'GET'); if (mounted.current) {setData(result); setError(''); setLogin(false);}}
    catch (e) {if (mounted.current) {if (e instanceof ApiError && e.status === 401) setLogin(true); else setError((e as Error).message);}}
    finally {pending.current = false;}
  }, []);
  useEffect(() => {
    mounted.current = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {await refresh(); if (mounted.current) timer = setTimeout(poll, 3000);}
    const token = new URLSearchParams(location.hash.slice(1)).get('login');
    if (token) {
      history.replaceState({}, '', location.pathname);
      api('login', {token}).catch(e => {setError(e.message); setLogin(true);}).then(poll);
    } else void poll();
    return () => {mounted.current = false; clearTimeout(timer);};
  }, [refresh]);
  useEffect(() => {if (!notice) return; const timer = setTimeout(() => setNotice(''), 6000); return () => clearTimeout(timer);}, [notice]);
  const run = useCallback(async (path: string, body?: unknown, method = 'POST') => {
    setBusy(x => x + 1); setNotice('');
    try {
      let result = await api(path, body, method);
      while (result.status === 'queued' || result.status === 'running') {
        await new Promise(resolve => setTimeout(resolve, 800));
        result = await api('operations/' + result.id, undefined, 'GET');
      }
      if (result.status === 'failed') throw new Error(result.error || '操作失败');
      const value = result.result ?? result;
      setNotice(value.test_ok === false ? '连接测试失败：' + value.test_error : value.tools ? 'MCP 连接正常，已发现 ' + value.tools.length + ' 个工具' : '操作已完成');
      await refresh();
      return value;
    } catch (e) {setNotice((e as Error).message); throw e;}
    finally {setBusy(x => x - 1);}
  }, [refresh]);
  return {data, error, login, notice, busy, refresh, run, setNotice};
}
