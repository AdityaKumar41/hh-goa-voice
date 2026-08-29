import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const languages = ["auto", "en", "as", "bn", "gu", "hi", "kn", "ml", "mr", "ne", "or", "pa", "sa", "ta", "te", "ur"];
const stages = ["transcript", "retrieval", "generation", "verified"];

type Citation = { passage_id: string; text: string; language: string; score: number; source_type?: string; source_title?: string };
type Result = { trace_id: string; transcript: string; detected_language: string; answer: string; confidence: number; grounded: boolean; refused: boolean; refusal_reason?: string; citations: Citation[]; timings_ms: Record<string, number>; mode?: "normal" | "fast" };

function retrievalMs(timings: Record<string, number> | undefined): number {
  return typeof timings?.retrieval === "number" ? timings.retrieval : 0;
}

function App() {
  const [text, setText] = useState("");
  const [language, setLanguage] = useState("auto");
  const [mode, setMode] = useState<"normal" | "fast">("fast");
  const [recording, setRecording] = useState(false);
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState("ready");
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [streamedAnswer, setStreamedAnswer] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [health, setHealth] = useState<any>(null);
  const [benchmark, setBenchmark] = useState<any>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  useEffect(() => { fetch("/api/health").then(r => r.json()).then(setHealth).catch(() => setHealth(null)); }, []);
  useEffect(() => { fetch("/api/benchmark").then(r => r.json()).then(setBenchmark).catch(() => setBenchmark(null)); }, []);

  async function submit(audioBase64?: string, queryText?: string) {
    setError(""); setResult(null); setSourcesOpen(false); setStreamedAnswer(""); setStage("starting"); setLoading(true);
    try {
      const body = JSON.stringify({ text: queryText !== undefined ? (queryText || undefined) : (text || undefined), language: language === "auto" ? undefined : language, audio_base64: audioBase64, mode });
      const response = await fetch("/api/query/stream", { method: "POST", headers: { "Content-Type": "application/json" }, body });
      if (!response.ok) { const p = await response.json().catch(() => ({})); throw new Error(p.detail || `Request failed (${response.status})`); }
      if (!response.body) throw new Error("The streaming response was unavailable.");
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n"); buffer = frames.pop() || "";
        for (const frame of frames) {
          const type = frame.match(/^event: (.+)$/m)?.[1]; const data = frame.match(/^data: (.+)$/m)?.[1]; if (!type || !data) continue;
          const payload = JSON.parse(data);
          if (type === "answer.token") setStreamedAnswer(c => c + (payload.token || ""));
          if (type === "transcript.ready") { setStage("transcript"); if (payload.transcript) setText(payload.transcript); }
          if (type === "retrieval.started") setStage("retrieval");
          if (type === "generation.started") setStage("generation");
          if (type === "run.result") {
            const safe = { ...payload, answer: payload.answer || "I could not produce a grounded answer.", citations: payload.citations || [] } as Result;
            setText(safe.transcript); setResult(safe); setStreamedAnswer(safe.answer); setStage(safe.refused ? "refused" : "verified");
          }
          if (type === "run.failed") throw new Error(payload.detail || "The research run failed.");
        }
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : "The research run failed."); }
    finally { setLoading(false); }
  }

  function startRecording() {
    navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
      chunks.current = []; const instance = new MediaRecorder(stream); recorder.current = instance;
      instance.ondataavailable = e => chunks.current.push(e.data);
      instance.onstop = () => { stream.getTracks().forEach(t => t.stop()); const reader = new FileReader(); reader.onloadend = () => submit(String(reader.result)); reader.readAsDataURL(new Blob(chunks.current, { type: "audio/webm" })); };
      instance.start(); setRecording(true);
    }).catch(() => setError("Microphone access is needed for voice. Allow it in the browser and try again."));
  }
  function stopRecording() { setRecording(false); recorder.current?.stop(); }
  function resetAll() { setText(""); setResult(null); setStreamedAnswer(""); setError(""); setStage("ready"); setSourcesOpen(false); }

  const indexReady = health?.dependencies?.qdrant === "configured";
  const statusLabel = result?.refused ? "Needs better evidence" : result ? "Grounded response" : "Ready for research";
  const visibleAnswer = loading ? streamedAnswer : result?.answer || "";
  const live = retrievalMs(result?.timings_ms) + (result?.mode === "fast" ? (result.timings_ms.total || 0) : 0);

  return <main className="app-shell">
    <header className="nav-bar"><a className="brand" href="/" aria-label="Hacker House Research Lab"><img src="/assets/Hacker house.png" alt="Hacker House" /><span>RESEARCH LAB</span></a><div className="nav-status"><span className="status-light" />{indexReady ? "CORPUS ONLINE" : "REPRESENTATIVE INDEX"}<span className="nav-divider" /> MSMARCO-XI</div><div className="nav-meta">GOA / 2026</div></header>
    <div className="workspace">
      <aside className="side-rail"><div className="rail-number">01</div><div className="rail-copy"><span>VOICE RESEARCH</span><strong>Ask clearly.<br />Verify everything.</strong></div><div className="rail-bottom"><span>14 LANGUAGES</span><span>READ-ONLY TOOLS</span><span>CITED OUTPUT</span></div></aside>
      <section className="main-column">
        <div className="intro-row"><div><p className="kicker">HACKER HOUSE CORE / RESEARCH ASSISTANT</p><h1>Find the signal.</h1><p className="lede">Speak a question. The lab detects your language, searches its indexed research, and tells you when it cannot verify a claim.</p></div><div className="mode-card"><span>MODE</span><strong>{mode === "fast" ? "FAST · &lt;200MS" : "FULL · LLM"}</strong><small>{mode === "fast" ? "Local extractive · instant" : "Hosted AI · polished"}</small></div></div>
        <div className="query-card">
          <div className="card-top"><span>VOICE QUERY</span><div className="mode-switch"><button className={mode === "fast" ? "mode-btn active" : "mode-btn"} onClick={() => setMode("fast")} title="Local extractive answer — whole path under 200ms">FAST <small>&lt;200ms</small></button><button className={mode === "normal" ? "mode-btn active" : "mode-btn"} onClick={() => setMode("normal")} title="Full hosted LLM answer">FULL</button></div></div>
          <div className={recording ? "voice-input listening" : "voice-input"}>
            {recording ? <span className="listening-label"><i className="recording-dot" /> Listening… speak your question</span>
              : text ? <span className="voicetext">{text}</span>
              : <span className="voice-placeholder">Tap record, speak your question in any language — no typing.</span>}
          </div>
          <div className="query-tools"><span className="voice-hint">{text ? (result?.detected_language ? result.detected_language.toUpperCase() : language === "auto" ? "AUTO DETECTED" : language.toUpperCase()) : "AUTO DETECTION"}</span><label className="language-control">LANGUAGE <select value={language} onChange={e => setLanguage(e.target.value)}>{languages.map(item => <option key={item} value={item}>{item === "auto" ? "Auto detect" : item.toUpperCase()}</option>)}</select></label></div>
          <div className="query-footer">
            <button className="record-button active" onClick={recording ? stopRecording : startRecording}>{recording ? "■ STOP" : "🎙 RECORD"}</button>
            {text && !loading && <button className="submit-button" onClick={() => submit()}>RUN ↗</button>}
            {text && !recording && <button className="reset-button" onClick={resetAll}>✕ CLEAR</button>}
          </div>
        </div>
        <div className="run-strip"><span className="section-index">02</span><span className="run-title">RESEARCH RUN</span><span className="run-id">{result ? result.trace_id.slice(0, 10) : "NO ACTIVE RUN"}</span></div>
        <div className="pipeline-steps">{stages.map((item, index) => <div className={stage === item || (stage === "verified" && index < 3) ? "pipeline-step active" : "pipeline-step"} key={item}><span>{String(index + 1).padStart(2, "0")}</span>{item}</div>)}</div>
        {benchmark && <div className="benchmark-strip"><span className="benchmark-label">LATENCY ANALYTICS · P50/{benchmark.p50_ms || "–"} P70/{benchmark.p70_ms || "–"} P95/{benchmark.p95_ms || "–"} P100/{benchmark.p100_ms || "–"}ms</span><span className={benchmark.under_200ms ? "benchmark-ok" : "benchmark-fail"}>{benchmark.under_200ms ? "✓ ALL UNDER 200ms" : "OVER 200ms"} · {benchmark.queries} QUERIES</span></div>}
        {error && <div className="error-state"><strong>RUN INTERRUPTED</strong><span>{error}</span><button className="error-link" onClick={resetAll}>Try again</button></div>}
        {!result && !error && !loading && <div className="empty-state"><span className="empty-mark">↘</span><div><strong>Your research answer will appear here.</strong><p>Speak with the RECORD button, or try a question like “When is Hacker House Goa?” — sources stay attached to every run.</p></div></div>}
        {loading && <div className="live-answer"><div className="answer-label"><span className="live-pulse" /> LIVE ANSWER <small>{stage.toUpperCase()}</small></div><p>{visibleAnswer || "Preparing the evidence trail…"}<span className="typing-cursor" /></p></div>}
        {result && <div className="result-block">
          <article className={result.refused ? "answer-panel refused" : "answer-panel"}>
            <div className="answer-heading"><span className="answer-state"><i />{statusLabel}</span><span>{result.mode === "fast" ? "FAST" : "FULL"} · {result.detected_language.toUpperCase()} · {Math.round(result.confidence * 100)}%</span></div>
            {result.refused ? <div className="refusal-card"><strong>NOT ANSWERED</strong><p>{result.answer}</p>{result.refusal_reason && <span className="refusal-reason">{result.refusal_reason}</span>}</div> : <h2>{visibleAnswer}</h2>}
          </article>
          {!result.refused && result.citations.length > 0 && (
            <div className="sources-block">
              <button className="sources-toggle" onClick={() => setSourcesOpen(o => !o)} aria-expanded={sourcesOpen}><span>SOURCES · {result.citations.length}</span><span className="sources-chev">{sourcesOpen ? "▾" : "▸"}</span></button>
              {sourcesOpen && <ol className="source-list">{result.citations.map((citation, index) => <li className="source-item" key={citation.passage_id}><span className="source-index">{String(index + 1).padStart(2, "0")}</span><div className="source-body"><div className="source-top"><strong>{citation.source_title || citation.passage_id}</strong><span className="source-badge">{(citation.source_type || "dataset").toUpperCase()}</span></div><p>{citation.text}</p></div></li>)}</ol>}
            </div>
          )}
          <div className="run-meta">
            {result.transcript && <span>TRANSCRIPT “{result.transcript}”</span>}
            <span>RETRIEVAL <b>{Math.round(retrievalMs(result.timings_ms))}ms</b></span>
            {typeof result.timings_ms.total === "number" && result.mode === "fast" && <span>TOTAL <b>{Math.round(result.timings_ms.total)}ms</b></span>}
          </div>
        </div>}
      </section>
    </div>
    <footer className="footer"><span>HACKER HOUSE CORE ASSIGNMENT</span><span>ELEVENLABS / QDRANT / MULTILINGUAL-E5</span><span>BUILT IN GOA ↗</span></footer>
  </main>;
}

createRoot(document.getElementById("root")!).render(<App />);