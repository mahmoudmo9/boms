/** Live page updates (v0.10.0 section 6). One server-sent-events stream (`/api/live/stream`) tells the open page
 * what changed; matching queries refetch, so a finished job (a Setad download, a harvest, an AI draft, a folder
 * rebuild, a backup) shows within about 2 s without a reload. If the stream keeps failing the provider polls
 * `/api/live/changes` every 2 s instead, and tries the stream again a minute later. Logic: lib/live.ts. */
import { useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { afterStreamError, type Batch, jobStates, matches, type Notice, POLL_MS, refreshAll, rootsFor, Seen, type Transport } from "../lib/live";

type JobNotice = Notice & { kind: "job" };
type AgentNotice = Notice & { kind: "agent" };
type LiveState = { transport: Transport; jobs: Record<string, JobNotice>; agent: AgentNotice | null; lastAt: number | null };
const LiveContext = createContext<LiveState>({ transport: "offline", jobs: {}, agent: null, lastAt: null });
const RETRY_STREAM_MS = 60_000;

export function LiveUpdatesProvider({ children, enabled = true }: { children: ReactNode; enabled?: boolean }) {
  const qc = useQueryClient();
  const [state, setState] = useState<LiveState>({ transport: "offline", jobs: {}, agent: null, lastAt: null });
  const seen = useRef(new Seen());
  const cursor = useRef<string | null>(null);

  const lastRefresh = useRef(0);
  const apply = useCallback((batch: Batch) => {
    cursor.current = batch.cursor;
    const fresh = seen.current.fresh(batch.notices);
    const all = refreshAll(batch, lastRefresh.current, Date.now());
    if (all) {                                 // more changed than the notices name: refresh everything shown
      lastRefresh.current = Date.now();
      void qc.invalidateQueries({ refetchType: "active" });
    }
    if (fresh.length === 0) return;
    const roots = rootsFor(fresh);
    if (!all) void qc.invalidateQueries({ predicate: (q) => matches(q.queryKey, roots), refetchType: "active" });
    const agent = [...fresh].reverse().find((n): n is AgentNotice => n.kind === "agent") ?? null;
    setState((s) => ({ ...s, jobs: jobStates(s.jobs, fresh), agent: agent ?? s.agent, lastAt: Date.now() }));
  }, [qc]);

  useEffect(() => {
    if (!enabled) return;
    let source: EventSource | null = null;
    let poll: number | undefined;
    let retry: number | undefined;
    let failures = 0;
    let stopped = false;
    const setTransport = (transport: Transport) => setState((s) => (s.transport === transport ? s : { ...s, transport }));

    const startPolling = () => {
      setTransport("polling");
      const tick = async () => {
        try { apply(await api<Batch>("/api/live/changes", { query: { since: cursor.current }, background: true })); setTransport("polling"); }
        catch { setTransport("offline"); }
      };
      void tick();
      poll = window.setInterval(() => void tick(), POLL_MS);
      retry = window.setTimeout(() => { window.clearInterval(poll); failures = 0; startStream(); }, RETRY_STREAM_MS);
    };
    const startStream = () => {
      if (stopped) return;
      if (typeof EventSource === "undefined") { startPolling(); return; }
      const url = cursor.current ? `/api/live/stream?since=${encodeURIComponent(cursor.current)}` : "/api/live/stream";
      source = new EventSource(url, { withCredentials: true });
      source.onopen = () => setTransport("stream");
      source.addEventListener("change", (e) => { failures = 0; apply(JSON.parse((e as MessageEvent).data) as Batch); });
      source.onerror = () => {
        failures += 1;
        if (afterStreamError(failures) === "polling") { source?.close(); source = null; startPolling(); }
      };
    };
    startStream();
    return () => { stopped = true; source?.close(); window.clearInterval(poll); window.clearTimeout(retry); };
  }, [enabled, apply]);

  return <LiveContext.Provider value={state}>{children}</LiveContext.Provider>;
}

export const useLive = () => useContext(LiveContext);

/** The live state of a job a button started: `null` until the feed has seen it. */
export function useJob(jobId: string | null | undefined): JobNotice | null {
  const { jobs } = useLive();
  return jobId ? jobs[jobId] ?? null : null;
}

/** A button that starts a job: busy from the click until the job is done or failed (so it cannot be pressed twice),
 * then `onFinished` with the final state. `start` returns the job id the API gave. */
export function useJobRunner(start: () => Promise<{ job_id: string }>, onFinished?: (status: "done" | "failed") => void) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const job = useJob(jobId);
  const finished = job && (job.status === "done" || job.status === "failed") ? job.status : null;
  const reported = useRef<string | null>(null);
  useEffect(() => {
    if (finished && jobId && reported.current !== jobId) { reported.current = jobId; onFinished?.(finished); }
  }, [finished, jobId, onFinished]);
  const run = useCallback(async () => {
    if (starting || (jobId && !finished)) return;
    setStarting(true);
    setError(null);
    try { setJobId((await start()).job_id); } catch (e) { setError(e); } finally { setStarting(false); }
  }, [start, starting, jobId, finished]);
  return { run, busy: starting || Boolean(jobId && !finished), status: job?.status ?? (jobId ? "queued" : null), error };
}
