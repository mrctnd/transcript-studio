import { StrictMode, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  AudioLines,
  Check,
  ChevronDown,
  CircleHelp,
  Clipboard,
  FileAudio,
  FileText,
  FolderOpen,
  Globe2,
  History,
  Link2,
  LoaderCircle,
  Menu,
  Plus,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { active, api, json, labels, timestamp } from "./api";
import type { Health, Job, Segment } from "./api";
import "@fontsource-variable/dm-sans";
import "./styles.css";

const models = [
  ["large-v3", "Highest accuracy · Slower"],
  ["medium", "High accuracy · Balanced"],
  ["small", "Good accuracy · Fast"],
  ["base", "Basic accuracy · Faster"],
  ["tiny", "Lowest accuracy · Fastest"],
];
const languages = [
  ["auto", "Auto-detect"],
  ["tr", "Turkish"],
  ["en", "English"],
  ["de", "German"],
  ["fr", "French"],
  ["es", "Spanish"],
  ["it", "Italian"],
  ["ru", "Russian"],
  ["ar", "Arabic"],
  ["ja", "Japanese"],
  ["zh", "Chinese"],
  ["ko", "Korean"],
  ["pt", "Portuguese"],
];
const formats = [
  ["md", "Markdown"],
  ["txt", "Plain text"],
  ["srt", "SubRip subtitles"],
  ["vtt", "WebVTT subtitles"],
  ["json", "Structured data"],
];
const waveform = [
  5, 9, 17, 11, 22, 30, 20, 37, 46, 28, 54, 67, 45, 76, 62, 91, 58, 109, 78,
  128, 98, 65, 111, 82, 49, 74, 63, 41, 58, 40, 31, 48, 25, 17, 32, 19, 12, 18,
  8, 5,
];

function Waveform() {
  return (
    <div className="waveform" aria-hidden="true">
      {waveform.map((height, index) => (
        <span key={index} style={{ height, opacity: 0.22 + height / 170 }} />
      ))}
    </div>
  );
}

function SourceForm({
  submit,
  maxBytes,
}: {
  submit: (job: Job) => void;
  maxBytes?: number;
}) {
  const [mode, setMode] = useState<"url" | "file">("url");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File>();
  const [model, setModel] = useState("large-v3");
  const [language, setLanguage] = useState("auto");
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setError("");
    if (mode === "file" && !file) {
      setError("Choose a video or audio file.");
      return;
    }
    if (mode === "file" && file && maxBytes && file.size > maxBytes) {
      setError(
        "The file exceeds the " +
          Math.floor(maxBytes / 1024 / 1024) +
          " MB limit.",
      );
      return;
    }
    const fields = { model, language, initial_prompt: prompt.trim() };
    setBusy(true);
    try {
      if (mode === "url") {
        if (!/^https?:\/\//i.test(url.trim()))
          throw new Error("Enter an HTTP or HTTPS URL.");
        submit(
          await api<Job>("/jobs", json("POST", { ...fields, url: url.trim() })),
        );
      } else if (file) {
        const data = new FormData();
        data.append("file", file);
        Object.entries(fields).forEach(([name, value]) =>
          data.append(name, value),
        );
        submit(await api<Job>("/jobs/upload", { method: "POST", body: data }));
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start transcription.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={create} className="card source-card">
      <div className="card-header">
        <span className="icon-block">
          <Link2 size={20} />
        </span>
        <div>
          <h2>Add a source</h2>
          <p>Use a link or select a file from your device.</p>
        </div>
      </div>
      <div className="mode-switch" role="group" aria-label="Source type">
        <button
          type="button"
          aria-pressed={mode === "url"}
          disabled={busy}
          onClick={() => {
            setMode("url");
            setError("");
          }}
        >
          <Link2 size={16} /> Link
        </button>
        <button
          type="button"
          aria-pressed={mode === "file"}
          disabled={busy}
          onClick={() => {
            setMode("file");
            setError("");
          }}
        >
          <Upload size={16} /> Upload file
        </button>
      </div>
      {mode === "url" ? (
        <label className="field">
          Video URL
          <span className="input-with-icon">
            <Link2 size={17} />
            <input
              type="url"
              required
              value={url}
              placeholder="https://www.youtube.com/watch?v=…"
              onChange={(event) => setUrl(event.target.value)}
              disabled={busy}
            />
          </span>
          <small>
            YouTube, Instagram and other supported public video links.
          </small>
        </label>
      ) : (
        <div className="field">
          <span>Video or audio file</span>
          <input
            ref={picker}
            type="file"
            hidden
            accept="video/*,audio/*,.mkv,.webm,.m4a,.ogg,.flac,.opus,.aac,.wma,.wmv,.avi,.mpeg,.mpg,.m4v,.ts"
            onChange={(event) => {
              setFile(event.target.files?.[0]);
              setError("");
            }}
          />
          <button
            type="button"
            className={"file-drop" + (dragging ? " dragging" : "")}
            disabled={busy}
            onClick={() => picker.current?.click()}
            onDragOver={(event) => {
              event.preventDefault();
              if (!busy) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              if (!busy && event.dataTransfer.files.length) {
                setFile(event.dataTransfer.files[0]);
                setError("");
              }
            }}
          >
            <FileAudio size={21} />
            <span>{file ? file.name : "Choose a file or drag it here"}</span>
          </button>
          <small>
            {file
              ? new Intl.NumberFormat("en-US", {
                  maximumFractionDigits: 1,
                }).format(file.size / 1024 / 1024) + " MB"
              : "MP4, MOV, WebM, MP3, WAV and other common formats."}
          </small>
        </div>
      )}
      <div className="options-grid">
        <label className="field">
          Whisper model
          <span className="select-wrap">
            <select
              value={model}
              disabled={busy}
              onChange={(event) => setModel(event.target.value)}
            >
              {models.map(([value, hint]) => (
                <option key={value} value={value}>
                  {value} · {hint}
                </option>
              ))}
            </select>
            <ChevronDown size={16} />
          </span>
          <small>{models.find(([value]) => value === model)?.[1]}</small>
        </label>
        <label className="field">
          Spoken language
          <span className="select-wrap">
            <Globe2 size={16} />
            <select
              className="has-leading"
              value={language}
              disabled={busy}
              onChange={(event) => setLanguage(event.target.value)}
            >
              {languages.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <ChevronDown size={16} />
          </span>
        </label>
      </div>
      <details className="advanced">
        <summary>
          <SlidersHorizontal size={16} /> Vocabulary hints{" "}
          <span>Optional</span>
          <ChevronDown size={16} className="advanced-arrow" />
        </summary>
        <label className="field">
          Names and terminology
          <textarea
            disabled={busy}
            rows={2}
            value={prompt}
            maxLength={1000}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="e.g. company names, people, technical terms…"
          />
          <small>
            Add words or names whose spelling the model should recognize.
          </small>
        </label>
      </details>
      {error && (
        <p className="feedback error" role="alert">
          {error}
        </p>
      )}
      <div className="form-footer">
        <p>
          <CircleHelp size={16} /> A model may need to download on first use.
        </p>
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Starting…" : "Start transcription"}
          {busy ? (
            <LoaderCircle size={17} className="spin" />
          ) : (
            <ArrowRight size={18} />
          )}
        </button>
      </div>
    </form>
  );
}

function Editor({
  job,
  draft,
  changeDraft,
  saveDraft,
}: {
  job: Job;
  draft?: Segment[];
  changeDraft: (segments: Segment[]) => void;
  saveDraft: (updated: Job, saved: Segment[]) => void;
}) {
  const segments = draft ?? job.segments;
  const [search, setSearch] = useState("");
  const [format, setFormat] = useState("md");
  const [timestamps, setTimestamps] = useState(true);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ text: string; error?: boolean }>();
  const dirty = Boolean(draft);
  const wordCount =
    segments
      .map((segment) => segment.text.trim())
      .filter(Boolean)
      .join(" ")
      .match(/\S+/g)?.length ?? 0;
  const locale = job.language === "tr" ? "tr" : undefined;
  const normalized = search.trim().toLocaleLowerCase(locale);
  const visible = segments.filter((segment) =>
    segment.text.toLocaleLowerCase(locale).includes(normalized),
  );
  const subtitleFormat = format === "srt" || format === "vtt";

  async function save() {
    setBusy(true);
    setFeedback(undefined);
    try {
      const updated = await api<Job>(
        "/jobs/" + job.id,
        json("PATCH", {
          segments: segments.map(({ id, start, end, text }) => ({
            id,
            start,
            end,
            text,
          })),
        }),
      );
      saveDraft(updated, segments);
      setFeedback({ text: "Changes saved." });
    } catch (cause) {
      setFeedback({
        text: cause instanceof Error ? cause.message : "Could not save changes.",
        error: true,
      });
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(
        segments
          .map(
            (segment) =>
              (timestamps ? "[" + timestamp(segment.start) + "] " : "") +
              segment.text,
          )
          .join("\n"),
      );
      setFeedback({ text: "Transcript copied." });
    } catch {
      setFeedback({ text: "Clipboard access is unavailable.", error: true });
    }
  }

  async function download() {
    setFeedback(undefined);
    try {
      const response = await fetch(
        "/api/jobs/" +
          job.id +
          "/export?" +
          new URLSearchParams({
            format,
            timestamps: String(subtitleFormat || timestamps),
          }),
      );
      if (!response.ok)
        throw new Error("Could not prepare the file (" + response.status + ").");
      const blob = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = blob;
      link.download =
        (job.title.replace(/[\\/:*?"<>|]/g, "_") || "transcript") + "." + format;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(blob), 1000);
    } catch (cause) {
      setFeedback({
        text: cause instanceof Error ? cause.message : "Could not download the file.",
        error: true,
      });
    }
  }

  return (
    <div className="result-grid">
      <section
        className="card transcript-card"
        aria-label="Transcript editor"
      >
        <div className="card-header">
          <span className="icon-block">
            <FileText size={20} />
          </span>
          <div>
            <h2>Transcript</h2>
            <p>
              {wordCount.toLocaleString("en-US")} {wordCount === 1 ? "word" : "words"} ·{" "}
              {segments.length.toLocaleString("en-US")} {segments.length === 1 ? "segment" : "segments"}
            </p>
          </div>
          <button
            type="button"
            className="secondary copy-button"
            onClick={copy}
          >
            <Clipboard size={16} /> Copy
          </button>
        </div>
        <label className="input-with-icon transcript-search">
          <Search size={17} />
          <input
            aria-label="Search transcript"
            placeholder="Search transcript…"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <div className="segments">
          {visible.map((segment) => (
            <div className="segment" key={segment.id}>
              <span
                className="time"
                title={
                  timestamp(segment.start) + " – " + timestamp(segment.end)
                }
              >
                {timestamp(segment.start)}
              </span>
              <textarea
                aria-label={timestamp(segment.start) + " segment text"}
                rows={Math.max(2, Math.ceil(segment.text.length / 75))}
                disabled={busy}
                value={segment.text}
                onChange={(event) =>
                  changeDraft(
                    segments.map((item) =>
                      item.id === segment.id
                        ? { ...item, text: event.target.value }
                        : item,
                    ),
                  )
                }
              />
            </div>
          ))}
          {!visible.length && (
            <p className="empty-search">
              {search.trim()
                ? "No segments match your search."
                : "No speech segments were detected."}
            </p>
          )}
        </div>
        <div className="editor-footer">
          <span>{dirty ? "Unsaved changes" : ""}</span>
          <button
            className="primary"
            disabled={!dirty || busy}
            type="button"
            onClick={save}
          >
            {busy ? "Saving…" : "Save changes"}
            <Check size={16} />
          </button>
        </div>
        {feedback && (
          <p
            className={"feedback" + (feedback.error ? " error" : "")}
            role={feedback.error ? "alert" : "status"}
          >
            {feedback.text}
          </p>
        )}
      </section>
      <section className="card export-card">
        <div className="card-header">
          <span className="icon-block">
            <ArrowDownToLine size={20} />
          </span>
          <div>
            <h2>Export</h2>
            <p>Choose an output format.</p>
          </div>
        </div>
        <label className="field">
          File format
          <span className="select-wrap">
            <select
              value={format}
              onChange={(event) => setFormat(event.target.value)}
            >
              {formats.map(([value, name]) => (
                <option key={value} value={value}>
                  {name} (.{value})
                </option>
              ))}
            </select>
            <ChevronDown size={16} />
          </span>
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={subtitleFormat || timestamps}
            disabled={subtitleFormat}
            onChange={(event) => setTimestamps(event.target.checked)}
          />{" "}
          Include timestamps
        </label>
        {subtitleFormat && (
          <small>Subtitle formats require timestamps.</small>
        )}
        {dirty && <small>Save your changes before downloading.</small>}
        <button
          className="primary"
          type="button"
          disabled={dirty}
          onClick={download}
        >
          <ArrowDownToLine size={17} /> Download
        </button>
      </section>
    </div>
  );
}

function App() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Segment[]>>({});
  const [selected, setSelected] = useState<string>();
  const [health, setHealth] = useState<Health>();
  const [offline, setOffline] = useState(false);
  const [sidebar, setSidebar] = useState(false);
  const [actionError, setActionError] = useState("");
  const [acting, setActing] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const job = jobs.find((item) => item.id === selected);
  const revision = useRef(0);
  const main = useRef<HTMLElement>(null);
  const navigation = useRef<HTMLElement>(null);
  const menu = useRef<HTMLButtonElement>(null);

  const hasDrafts = Object.keys(drafts).length > 0;

  useEffect(() => {
    if (!hasDrafts) return;
    function warnAboutDrafts(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = true;
    }
    window.addEventListener("beforeunload", warnAboutDrafts);
    return () => window.removeEventListener("beforeunload", warnAboutDrafts);
  }, [hasDrafts]);

  useEffect(() => {
    if (!sidebar) return;
    const frame = requestAnimationFrame(() =>
      navigation.current?.querySelector("button")?.focus(),
    );
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") closeSidebar();
    }
    document.addEventListener("keydown", handleEscape);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [sidebar]);

  function closeSidebar() {
    setSidebar(false);
    menu.current?.focus();
  }

  useEffect(() => {
    let alive = true;
    let pending = false;
    async function refresh() {
      if (pending) return;
      pending = true;
      const requestRevision = revision.current;
      try {
        const [list, local] = await Promise.allSettled([
          api<Job[]>("/jobs"),
          api<Health>("/health"),
        ]);
        if (!alive) return;
        if (list.status === "fulfilled" && revision.current === requestRevision)
          setJobs(list.value);
        if (local.status === "fulfilled") setHealth(local.value);
        setOffline(list.status === "rejected" || local.status === "rejected");
        setLoaded(true);
      } finally {
        pending = false;
      }
    }
    void refresh();
    const timer = window.setInterval(refresh, 2200);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  function open(id?: string) {
    setSelected(id);
    setSidebar(false);
    setActionError("");
    main.current?.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }

  function update(updated: Job) {
    revision.current += 1;
    setJobs((current) =>
      current.some((item) => item.id === updated.id)
        ? current.map((item) => (item.id === updated.id ? updated : item))
        : [updated, ...current],
    );
  }

  function clearDraft(id: string, saved?: Segment[]) {
    setDrafts((current) => {
      if (!current[id] || (saved && current[id] !== saved)) return current;
      const remaining = { ...current };
      delete remaining[id];
      return remaining;
    });
  }

  function changeDraft(job: Job, segments: Segment[]) {
    if (
      segments.some(
        (segment, index) => segment.text !== job.segments[index]?.text,
      )
    ) {
      setDrafts((current) => ({ ...current, [job.id]: segments }));
    } else {
      clearDraft(job.id);
    }
  }

  async function action(kind: "cancel" | "delete") {
    if (!job || acting) return;
    if (
      kind === "delete" &&
      !window.confirm("Delete this transcript and its history entry?")
    )
      return;
    setActing(true);
    setActionError("");
    try {
      if (kind === "cancel")
        update(
          await api<Job>("/jobs/" + job.id + "/cancel", { method: "POST" }),
        );
      else {
        await api("/jobs/" + job.id, { method: "DELETE" });
        revision.current += 1;
        setJobs((current) => current.filter((item) => item.id !== job.id));
        clearDraft(job.id);
        setSelected((current) => (current === job.id ? undefined : current));
      }
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : "Could not complete the request.",
      );
    } finally {
      setActing(false);
    }
  }

  return (
    <div className="app">
      {sidebar && (
        <button
          type="button"
          className="backdrop"
          aria-label="Close history"
          onClick={closeSidebar}
        />
      )}
      <aside
        ref={navigation}
        id="studio-navigation"
        className={"sidebar" + (sidebar ? " shown" : "")}
        aria-label="Studio navigation"
      >
        <button type="button" className="brand" onClick={() => open()}>
          <span className="brand-icon">
            <AudioLines size={24} />
          </span>
          <span>
            Transcript Studio
          </span>
        </button>
        <button type="button" className="new-button" onClick={() => open()}>
          <Plus size={18} /> New transcript
        </button>
        <div className="history">
          <h2>
            <History size={15} /> History
          </h2>
          {jobs.length ? (
            <nav aria-label="Transcript history">
              {jobs.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-current={item.id === selected ? "page" : undefined}
                  onClick={() => open(item.id)}
                >
                  <FileText size={16} />
                  <span>
                    <strong>{item.title || "Video recording"}</strong>
                    <small>{labels[item.status]}</small>
                  </span>
                  {active(item.status) && <span className="status-dot" />}
                </button>
              ))}
            </nav>
          ) : (
            <div className="empty-history">
              <FolderOpen size={17} />
              <span>{loaded ? "No transcripts yet" : "Loading history…"}</span>
            </div>
          )}
        </div>
        <div className="sidebar-bottom">
          <ShieldCheck size={18} />
          <div>
            <strong>Local workspace</strong>
            <small>No API key required</small>
          </div>
        </div>
      </aside>
      <main ref={main} tabIndex={-1}>
        <header className="topbar">
          <div>
            <button
              ref={menu}
              className="menu-toggle icon-button"
              type="button"
              aria-label={sidebar ? "Close history" : "Open history"}
              aria-expanded={sidebar}
              aria-controls="studio-navigation"
              onClick={() => setSidebar(!sidebar)}
            >
              {sidebar ? <X size={21} /> : <Menu size={21} />}
            </button>
            <span className="breadcrumb">
              Workspace <span>/</span>{" "}
              <strong>{job ? "Transcript details" : "New transcript"}</strong>
            </span>
          </div>
          <span
            className={"connection" + (offline ? " offline" : "")}
            title={health ? health.engine + " · " + health.device : undefined}
          >
            <span className="status-dot" />{" "}
            {offline
              ? "Offline"
              : health?.status === "degraded"
                ? "Engine needs attention"
                : health
                  ? "Local engine ready"
                  : "Checking engine"}
          </span>
        </header>
        <div className="content">
          <section className={"hero" + (job ? " job-hero" : "")}>
            {job ? (
              <>
                <div className="eyebrow">
                  <AudioLines size={16} /> {labels[job.status]}
                </div>
                <h1>{job.title || "Video recording"}</h1>
                <p>
                  <span>{job.model}</span>
                  {job.duration != null && (
                    <span> · {timestamp(job.duration)}</span>
                  )}
                </p>
              </>
            ) : (
              <>
                <h1>
                  Turn audio into <em>editable text.</em>
                </h1>
                <p>
                  Transcribe video and audio with timestamps, then edit and export in your preferred format.
                </p>
                <Waveform />
              </>
            )}
          </section>
          {offline && (
            <p className="feedback error connection-error" role="status">
              The local server is unavailable. Retrying connection…
            </p>
          )}
          {actionError && (
            <p className="feedback error connection-error" role="alert">
              {actionError}
            </p>
          )}
          {!job ? (
            <div className="workspace-grid">
              <SourceForm
                maxBytes={health?.max_file_size}
                submit={(created) => {
                  update(created);
                  open(created.id);
                }}
              />
              <aside className="guide-card" aria-label="Transcription workflow">
                <span className="icon-block">
                  <Activity size={20} />
                </span>
                <h2>How it works</h2>
                <ol>
                  <li>
                    <span>
                      <Link2 size={15} />
                    </span>
                    <div>
                      <strong>Add media</strong>
                      <p>Paste a public URL or upload a file.</p>
                    </div>
                  </li>
                  <li>
                    <span>
                      <AudioLines size={15} />
                    </span>
                    <div>
                      <strong>Transcribe speech</strong>
                      <p>
                        Whisper detects speech and assigns timestamps.
                      </p>
                    </div>
                  </li>
                  <li>
                    <span>
                      <ArrowDownToLine size={15} />
                    </span>
                    <div>
                      <strong>Review and export</strong>
                      <p>Edit the transcript and download it as text or subtitles.</p>
                    </div>
                  </li>
                </ol>
                <p className="guide-note">
                  <ShieldCheck size={17} /> Audio is processed on this device. Recording quality affects accuracy.
                </p>
              </aside>
            </div>
          ) : job.status === "completed" ? (
            <Editor
              key={job.id}
              job={job}
              draft={drafts[job.id]}
              changeDraft={(segments) => changeDraft(job, segments)}
              saveDraft={(updated, saved) => {
                update(updated);
                clearDraft(updated.id, saved);
              }}
            />
          ) : (
            <section className="card process-card">
              <div className="card-header">
                <span className="icon-block">
                  {active(job.status) ? (
                    <LoaderCircle className="spin" size={21} />
                  ) : (
                    <FileText size={21} />
                  )}
                </span>
                <div>
                  <h2>{labels[job.status]}</h2>
                  <p>
                    {job.error ||
                      job.message ||
                      (active(job.status)
                        ? "Processing on this device."
                        : "Add a source to try again.")}
                  </p>
                </div>
              </div>
              {active(job.status) && (
                <div className="progress-wrap">
                  <progress
                    aria-label="Transcription progress"
                    value={Math.max(0, Math.min(100, job.progress))}
                    max={100}
                  />
                  <span>
                    {Math.round(Math.max(0, Math.min(100, job.progress)))}%
                  </span>
                </div>
              )}
              {active(job.status) && (
                <button
                  type="button"
                  className="secondary"
                  disabled={acting}
                  onClick={() => action("cancel")}
                >
                  <X size={16} /> Cancel transcription
                </button>
              )}
            </section>
          )}
          {job && Boolean(job.warnings?.length) && (
            <ul className="warnings">
              {job.warnings.map((warning, index) => (
                <li key={index}>{warning}</li>
              ))}
            </ul>
          )}
          {job && !active(job.status) && (
            <div className="record-actions">
              <button
                type="button"
                className="secondary danger"
                disabled={acting}
                onClick={() => action("delete")}
              >
                <Trash2 size={16} /> Delete transcript
              </button>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
