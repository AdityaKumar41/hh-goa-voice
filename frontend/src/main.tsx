import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const languages = ["auto", "en", "as", "bn", "gu", "hi", "kn", "ml", "mr", "ne", "or", "pa", "sa", "ta", "te", "ur"];
const stages = ["transcript", "retrieval", "generation", "verified"];

type Citation = { passage_id: string; text: string; language: string; score: number; source_type?: string; source_title?: string };
type Result = { trace_id: string; transcript: string; detected_language: string; answer: string; confidence: number; grounded: boolean; refused: boolean; refusal_reason?: string; citations: Citation[]; timings_ms: Record<string, number> };

function App() {
  const [text, setText] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [language, setLanguage] = useState("auto");
  const [recording, setRecording] = useState(false);
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState("ready");
  const [streamedAnswer, setStreamedAnswer] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [health, setHealth] = useState<any>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  useEffect(() => { fetch("/api/health").then(response => response.json()).then(setHealth).catch(() => setHealth(null)); }, []);

  async function submit(audioBase64?: string) {
    setError(""); setResult(null); setStreamedAnswer(""); setStage("starting"); setLoading(true);
    try {
      const response = await fetch("/api/query/stream", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: text || undefined, language: language === "auto" ? undefined : language, audio_base64: audioBase64, source_url: sourceUrl || undefined }) });
      if (!response.ok) { const payload = await response.json().catch(() => ({})); throw new Error(payload.detail || `Request failed (${response.status})`); }
      if (!response.body) throw new Error("The streaming response was unavailable.");
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
      while (true) {
        const chunk = await reader.read(); if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true }); const frames = buffer.split("\n\n"); buffer = frames.pop() || "";
        for (const frame of frames) {
          const type = frame.match(/^event: (.+)$/m)?.[1]; const data = frame.match(/^data: (.+)$/m)?.[1]; if (!type || !data) continue;
          const payload = JSON.parse(data);
          if (type === "answer.token") setStreamedAnswer(current => current + (payload.token || ""));
          if (type === "transcript.ready") { setStage("transcript"); if (payload.transcript) setText(payload.transcript); }
          if (type === "retrieval.started") setStage("retrieval");
          if (type === "generation.started") setStage("generation");
          if (type === "answer.completed") setStage("verified");
          if (type === "run.result") { const safe = { ...payload, answer: payload.answer || "I could not produce a grounded answer.", citations: payload.citations || [] } as Result; setText(safe.transcript); setResult(safe); setStreamedAnswer(safe.answer); setStage(safe.refused ? "refused" : "verified"); }
          if (type === "run.failed") throw new Error(payload.detail || "The research run failed.");
        }
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : "The research run failed."); }
    finally { setLoading(false); }
  }

  function startRecording() {
    navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
      chunks.current = []; const instance = new MediaRecorder(stream); recorder.current = instance;
      instance.ondataavailable = event => chunks.current.push(event.data);
      instance.onstop = () => { stream.getTracks().forEach(track => track.stop()); const reader = new FileReader(); reader.onloadend = () => submit(String(reader.result)); reader.readAsDataURL(new Blob(chunks.current, { type: "audio/webm" })); };
      instance.start(); setRecording(true);
    }).catch(cause => setError(cause instanceof Error ? cause.message : "Microphone permission was denied."));
  }
  function stopRecording() { setRecording(false); recorder.current?.stop(); }
  const indexReady = health?.dependencies?.qdrant === "configured";
  const statusLabel = result?.refused ? "Needs better evidence" : result ? "Grounded response" : "Ready for research";
  const visibleAnswer = loading ? streamedAnswer : result?.answer || "";

  return <main className="app-shell">
    <header className="nav-bar"><a className="brand" href="/" aria-label="Hacker House Research Lab"><img src="/assets/Hacker house.png" alt="Hacker House" /><span>RESEARCH LAB</span></a><div className="nav-status"><span className="status-light" />{indexReady ? "CORPUS ONLINE" : "REPRESENTATIVE INDEX"}<span className="nav-divider" /> MSMARCO-XI</div><div className="nav-meta">GOA / 2026</div></header>
    <div className="workspace">
      <aside className="side-rail"><div className="rail-number">01</div><div className="rail-copy"><span>VOICE RESEARCH</span><strong>Ask clearly.<br />Verify everything.</strong></div><div className="rail-bottom"><span>14 LANGUAGES</span><span>READ-ONLY TOOLS</span><span>CITED OUTPUT</span></div></aside>
      <section className="main-column">
        <div className="intro-row"><div><p className="kicker">HACKER HOUSE CORE / RESEARCH ASSISTANT</p><h1>Find the signal.</h1><p className="lede">Speak or type a question. The lab searches its indexed research, shows the evidence, and tells you when it cannot verify a claim.</p></div><div className="mode-card"><span>MODE</span><strong>GROUNDED<br />RESEARCH</strong><small>{indexReady ? "Live Qdrant index" : "Curated fallback · ingest required"}</small></div></div>
        <div className="query-card"><div className="card-top"><span>NEW QUERY</span><span>{language === "auto" ? "AUTO DETECTION" : language.toUpperCase()}</span></div><textarea value={text} onChange={event => setText(event.target.value)} placeholder="What would you like to research?" aria-label="Research question" maxLength={4000} /><div className="query-tools"><span>{text.length}/4000</span><label className="language-control">LANGUAGE <select value={language} onChange={event => setLanguage(event.target.value)}>{languages.map(item => <option key={item} value={item}>{item === "auto" ? "Auto detect" : item.toUpperCase()}</option>)}</select></label></div><div className="query-footer"><input value={sourceUrl} onChange={event => setSourceUrl(event.target.value)} placeholder="Optional public URL for read-only web research" aria-label="Optional public URL" /><button className={recording ? "record-button active" : "record-button"} onClick={recording ? stopRecording : startRecording}>{recording ? "STOP" : "RECORD"}</button><button className="submit-button" disabled={!text.trim() || loading} onClick={() => submit()}>{loading ? "RESEARCHING…" : "RUN RESEARCH"}<span>↗</span></button></div>{recording && <div className="recording-state"><span className="recording-dot" /> Listening. Stop when you have finished speaking.</div>}</div>
        <div className="run-strip"><span className="section-index">02</span><span className="run-title">RESEARCH RUN</span><span className="run-id">{result ? result.trace_id.slice(0, 10) : "NO ACTIVE RUN"}</span></div>
        <div className="pipeline-steps">{stages.map((item, index) => <div className={stage === item || (stage === "verified" && index < 3) ? "pipeline-step active" : "pipeline-step"} key={item}><span>{String(index + 1).padStart(2, "0")}</span>{item}</div>)}</div>
        {error && <div className="error-state"><strong>RUN INTERRUPTED</strong><span>{error}</span></div>}
        {!result && !error && !loading && <div className="empty-state"><span className="empty-mark">↘</span><div><strong>Your research answer will appear here.</strong><p>Sources, transcript, confidence, and timings stay attached to every run.</p></div></div>}
        {loading && <div className="live-answer"><div className="answer-label"><span className="live-pulse" /> LIVE ANSWER <small>{stage.toUpperCase()}</small></div><p>{visibleAnswer || "Preparing the evidence trail…"}<span className="typing-cursor" /></p></div>}
        {result && <div className="result-block">
          <article className={result.refused ? "answer-panel refused" : "answer-panel"}>
            <div className="answer-heading"><span className="answer-state"><i />{statusLabel}</span><span>{result.detected_language} · {Math.round(result.confidence * 100)}%</span></div>
            <h2>{visibleAnswer}</h2>
            {result.refused && <div className="refusal-note">{result.refusal_reason || "The retrieved evidence was not sufficient to support an answer."}</div>}
          </article>
          {result.citations.length > 0 && <div className="sources-block">
            <div className="sources-heading"><span>SOURCES</span><strong>{result.citations.length}</strong></div>
            <ol className="source-list">
              {result.citations.map((citation, index) => <li className="source-item" key={citation.passage_id}>
                <span className="source-index">{String(index + 1).padStart(2, "0")}</span>
                <div className="source-body">
                  <div className="source-top"><strong>{citation.source_title || citation.passage_id}</strong><span className="source-badge">{(citation.source_type || "dataset").toUpperCase()}</span></div>
                  <p>{citation.text}</p>
                </div>
              </li>)}
            </ol>
          </div>}
          <div className="run-meta">
            {result.transcript && <span>TRANSCRIPT “{result.transcript}”</span>}
            {Object.entries(result.timings_ms).map(([key, value]) => <span key={key}>{key.replaceAll("_", " ")} <b>{Number(value).toFixed(0)}ms</b></span>)}
          </div>
        </div>}
      </section>
    </div>
    <footer className="footer"><span>HACKER HOUSE CORE ASSIGNMENT</span><span>ELEVENLABS / QDRANT / DEEPSEEK V4 FLASH</span><span>BUILT IN GOA ↗</span></footer>
  </main>;
}

createRoot(document.getElementById("root")!).render(<App />);
