"use client";

import { ConversationProvider, useConversation } from "@elevenlabs/react";
import { useCallback, useRef, useState } from "react";

const AGENT_ID = process.env.NEXT_PUBLIC_ELEVENLABS_AGENT_ID ?? "";

type Line = { id: number; role: "user" | "agent"; text: string };
type ToolEvent = {
  id: number;
  tool: string;
  params: Record<string, unknown>;
  result?: unknown;
  ms?: number;
  ok?: boolean;
};
type Intake = {
  patient_name?: string;
  body_area?: string;
  reason?: string;
  pain_level?: number;
  slot?: string;
  confirmation_code?: string;
};

export default function IntakeDemo() {
  return (
    <ConversationProvider>
      <Demo />
    </ConversationProvider>
  );
}

function Demo() {
  const [lines, setLines] = useState<Line[]>([]);
  const [events, setEvents] = useState<ToolEvent[]>([]);
  const [intake, setIntake] = useState<Intake>({});
  const [error, setError] = useState<string | null>(null);
  const nextId = useRef(0);

  const addEvent = (tool: string, params: Record<string, unknown>) => {
    const id = nextId.current++;
    setEvents((e) => [{ id, tool, params }, ...e]);
    return id;
  };
  const finishEvent = (id: number, result: unknown, ms: number, ok: boolean) =>
    setEvents((e) => e.map((ev) => (ev.id === id ? { ...ev, result, ms, ok } : ev)));

  // Client tools: the agent calls these in the browser; each one calls the
  // Python clinic API, so the rules live in code and every call is visible here.
  const callApi = useCallback(async (tool: string, path: string, params: Record<string, unknown>) => {
    const id = addEvent(tool, params);
    const t0 = performance.now();
    try {
      const res = await fetch(`/api/py/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      const data = await res.json();
      finishEvent(id, data, Math.round(performance.now() - t0), res.ok && data.ok !== false);
      return data;
    } catch (err) {
      const data = { ok: false, errors: [{ field: "system", problem: "clinic_api_unreachable" }] };
      finishEvent(id, { ...data, detail: String(err) }, Math.round(performance.now() - t0), false);
      return data;
    }
  }, []);

  const clientTools = {
    record_intake: (params: Record<string, unknown>) => {
      addEvent("record_intake", params);
      setIntake((cur) => ({ ...cur, ...(params as Intake) }));
    },
    check_availability: async (params: Record<string, unknown>) => {
      const data = await callApi("check_availability", "availability", params);
      return JSON.stringify(data);
    },
    book_appointment: async (params: Record<string, unknown>) => {
      const data = await callApi("book_appointment", "book", params);
      if (data.ok) {
        setIntake((cur) => ({
          ...cur,
          ...data.appointment,
          slot: data.appointment.label,
          confirmation_code: data.confirmation_code,
        }));
      }
      return JSON.stringify(data);
    },
  };

  const conversation = useConversation({
    clientTools,
    onMessage: (m) =>
      setLines((l) => [...l, { id: nextId.current++, role: m.role, text: m.message }]),
    onError: (message) => setError(String(message)),
  });

  const connected = conversation.status === "connected";
  const connecting = conversation.status === "connecting";

  const start = async () => {
    setError(null);
    setLines([]);
    setEvents([]);
    setIntake({});
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
      conversation.startSession({ agentId: AGENT_ID });
    } catch {
      setError("Microphone access is needed to talk to the clinic.");
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      {/* Left: the patient's view */}
      <section className="rounded-2xl border border-line bg-card p-6">
        <p className="text-xs font-medium uppercase tracking-wider text-muted">Patient view</p>
        <h2 className="mt-1 text-xl font-semibold">Book your first evaluation</h2>
        <p className="mt-1 text-sm text-muted">Speak English or Spanish. About two minutes.</p>

        <div className="mt-6 flex items-center gap-4">
          {connected ? (
            <button onClick={() => conversation.endSession()} className="btn btn-stop">
              End call
            </button>
          ) : (
            <button onClick={start} disabled={connecting || !AGENT_ID} className="btn btn-start">
              {connecting ? "Connecting…" : "Talk to the clinic"}
            </button>
          )}
          <StatusDot status={conversation.status} speaking={conversation.isSpeaking} />
        </div>
        {!AGENT_ID && (
          <p className="mt-3 text-sm text-warn">Agent not configured: run scripts/setup_agent.py.</p>
        )}
        {error && <p className="mt-3 text-sm text-warn">{error}</p>}

        <div className="mt-6 h-80 space-y-3 overflow-y-auto pr-1" aria-live="polite">
          {lines.length === 0 && (
            <p className="text-sm text-muted">The conversation transcript will appear here.</p>
          )}
          {lines.map((l) => (
            <div key={l.id} className={l.role === "user" ? "text-right" : ""}>
              <span
                className={`inline-block max-w-[85%] rounded-2xl px-3 py-2 text-sm ${
                  l.role === "user" ? "bg-accent text-white" : "bg-soft"
                }`}
              >
                {l.text}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* Right: what happens behind the voice */}
      <section className="rounded-2xl border border-line bg-card p-6">
        <p className="text-xs font-medium uppercase tracking-wider text-muted">Behind the voice</p>
        <h2 className="mt-1 text-xl font-semibold">Clinic system</h2>

        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <Field label="Patient" value={intake.patient_name} />
          <Field label="Body area" value={intake.body_area?.replace("_", " ")} />
          <Field label="Pain (0–10)" value={intake.pain_level?.toString()} />
          <Field label="Slot" value={intake.slot} />
          <div className="col-span-2">
            <Field label="Reason" value={intake.reason} />
          </div>
        </dl>
        {intake.confirmation_code && (
          <p className="mt-4 rounded-xl bg-ok-soft px-4 py-3 text-sm font-medium text-ok">
            Booked · confirmation {intake.confirmation_code}
          </p>
        )}

        <h3 className="mt-6 text-sm font-semibold">Tool calls</h3>
        <ol className="mt-2 max-h-80 space-y-2 overflow-y-auto pr-1">
          {events.length === 0 && (
            <li className="text-sm text-muted">Each call the agent makes to the clinic API shows up here.</li>
          )}
          {events.map((ev) => (
            <li key={ev.id} className="rounded-xl border border-line p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <code className="font-mono font-semibold">{ev.tool}</code>
                <span className={ev.ok === false ? "text-warn" : "text-muted"}>
                  {ev.ms !== undefined ? `${ev.ok ? "ok" : "rejected"} · ${ev.ms} ms` : ev.tool === "record_intake" ? "ui update" : "running…"}
                </span>
              </div>
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words font-mono text-muted">
                {JSON.stringify(ev.params)}
              </pre>
              {ev.result !== undefined && (
                <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words font-mono">
                  → {JSON.stringify(ev.result)}
                </pre>
              )}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string }) {
  return (
    <div className="rounded-xl bg-soft px-3 py-2">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 min-h-5 font-medium">{value ?? "—"}</dd>
    </div>
  );
}

function StatusDot({ status, speaking }: { status: string; speaking: boolean }) {
  const label = status !== "connected" ? status : speaking ? "agent speaking" : "listening";
  return (
    <span className="flex items-center gap-2 text-sm text-muted">
      <span
        className={`h-2.5 w-2.5 rounded-full ${
          status === "connected" ? (speaking ? "bg-accent animate-pulse" : "bg-ok") : "bg-line"
        }`}
      />
      {label}
    </span>
  );
}
