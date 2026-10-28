
import { useCallback, useEffect, useState } from "react";
import "./App.css";

const API = (import.meta.env.VITE_API_URL || "/api").replace(/\/$/, "");
const MAX_UPLOAD_BYTES = 500 * 1024 * 1024;
const ALLOWED_VIDEO_EXTENSIONS = [".mp4", ".mov", ".mkv", ".webm"];
const ASPECT_RATIOS = [
  { value: "9:16", label: "Portrait · 9:16 · 1080 × 1920 px", size: "1080 × 1920 px" },
  { value: "1:1", label: "Square · 1:1 · 1080 × 1080 px", size: "1080 × 1080 px" },
  { value: "16:9", label: "Landscape · 16:9 · 1920 × 1080 px", size: "1920 × 1080 px" },
];
const SUBTITLE_STYLES = [
  { value: "classic", label: "Classic Outline" },
  { value: "bold", label: "Bold Pop" },
  { value: "boxed", label: "Caption Box" },
  { value: "minimal", label: "Minimal Shadow" },
  { value: "neon", label: "Neon Glow" },
  { value: "highlight", label: "Highlight Bar" },
  { value: "cinema", label: "Cinema Serif" },
  { value: "typewriter", label: "Typewriter" },
  { value: "heavy_outline", label: "Heavy Outline" },
  { value: "soft_shadow", label: "Soft Shadow" },
];
const SUBTITLE_POSITIONS = [
  { value: "bottom", label: "Bottom" },
  { value: "center", label: "Center" },
  { value: "top", label: "Top" },
];
const RATIO_CSS = {
  "9:16": "9 / 16",
  "1:1": "1 / 1",
  "16:9": "16 / 9",
};
const DEFAULT_RATIO = ASPECT_RATIOS[0];

function getAspectRatioOption(value) {
  return ASPECT_RATIOS.find((ratio) => ratio.value === value) ||
    DEFAULT_RATIO;
}

function SubtitleToggle({
  checked,
  onChange,
  description = "Add English subtitles to generated clips.",
}) {
  return (
    <label className="subtitle-toggle">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>
        <strong>Add subtitles</strong>
        <small>{description}</small>
      </span>
    </label>
  );
}

const navItems = [
  ["home", "Home", "⌂"],
  ["upload", "Create Shorts", "＋"],
  ["projects", "My Projects", "▤"],
  ["settings", "Creation Defaults", "Aa"],
  ["profile", "Profile & Settings", "⚙"],
  ["help", "Help & FAQ", "?"],
  ["about", "About Us", "i"],
  ["contact", "Contact & Feedback", "✉"],
  ["privacy", "Privacy Policy", "◈"],
  ["terms", "Terms of Service", "§"],
];

async function apiRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API}${path}`, options);
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(
        "Cannot reach the ClipCut backend. Start the app with start-clipcut.bat and keep both server windows open."
      );
    }
    throw error;
  }

  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }

  if (!response.ok) {
    const detail = data.error || data.detail || data.message;

    if (typeof detail === "string") {
      const error = new Error(detail);
      error.data = data;
      throw error;
    }

    for (const value of Object.values(data.fields || data)) {
      const messages = Array.isArray(value) ? value : [value];
      const message = messages.find(
        (item) => typeof item === "string"
      );

      if (message) {
        const error = new Error(message);
        error.data = data;
        throw error;
      }
    }

    const error = new Error(`Request failed (${response.status})`);
    error.data = data;
    throw error;
  }

  return data;
}

function getVideoUrl(clip) {
  if (!clip) return "";

  const value =
    clip.video_url ||
    clip.video_file ||
    clip.video ||
    "";

  if (!value) return "";

  if (value.startsWith("http://") || value.startsWith("https://")) {
    const url = new URL(value, window.location.origin);
    if (
      url.hostname === "localhost" ||
      url.hostname === "127.0.0.1"
    ) {
      return `${url.pathname}${url.search}${url.hash}`;
    }
    return value;
  }

  return `${window.location.origin}${value.startsWith("/") ? "" : "/"}${value}`;
}

function getClipStart(clip) {
  return Number(clip?.start_time ?? clip?.start ?? 0);
}

function getClipEnd(clip) {
  return Number(clip?.end_time ?? clip?.end ?? 0);
}

function formatTime(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = Math.floor(value / 60);
  const remainingSeconds = value % 60;

  return `${String(minutes).padStart(2, "0")}:${String(
    remainingSeconds
  ).padStart(2, "0")}`;
}

function pageTitle(page) {
  const titles = {
    home: "Dashboard",
    upload: "Create Shorts",
    processing: "Processing Video",
    results: "Your Shorts",
    editor: "Clip Editor",
    export: "Export Video",
    projects: "My Projects",
    settings: "Creation Defaults",
    profile: "Profile & Settings",
    help: "Help & FAQ",
    about: "About ClipCut AI",
    contact: "Contact & Feedback",
    privacy: "Privacy Policy",
    terms: "Terms of Service",
    login: "Sign In",
    signup: "Create Account",
    notfound: "Page Not Found",
  };

  return titles[page] || "ClipCut AI";
}

export default function App() {
  const [page, setPage] = useState("home");
  const [jobs, setJobs] = useState([]);
  const [activeJob, setActiveJob] = useState(null);
  const [activeClip, setActiveClip] = useState(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [aspectRatio, setAspectRatio] = useState(
    () => localStorage.getItem("clipcut-aspect-ratio") || "9:16"
  );
  const [subtitleStyle, setSubtitleStyle] = useState(
    () => localStorage.getItem("clipcut-subtitle-style") || "classic"
  );
  const [includeSubtitles, setIncludeSubtitles] = useState(
    () => localStorage.getItem("clipcut-include-subtitles") !== "false"
  );
  const [subtitlePosition, setSubtitlePosition] = useState(
    () =>
      localStorage.getItem("clipcut-subtitle-position") || "bottom"
  );

  const [captionSize, setCaptionSize] = useState(() => {
    const saved = Number(
      localStorage.getItem("clipcut-caption-size")
    );

    return saved >= 12 && saved <= 36 ? saved : 20;
  });

  const [captionColor, setCaptionColor] = useState(
    () =>
      localStorage.getItem("clipcut-caption-color") ||
      "#ffffff"
  );

  useEffect(() => {
    localStorage.setItem(
      "clipcut-caption-size",
      String(captionSize)
    );
  }, [captionSize]);

  useEffect(() => {
    localStorage.setItem(
      "clipcut-caption-color",
      captionColor
    );
  }, [captionColor]);

  useEffect(() => {
    localStorage.setItem("clipcut-aspect-ratio", aspectRatio);
  }, [aspectRatio]);

  useEffect(() => {
    localStorage.setItem("clipcut-subtitle-style", subtitleStyle);
  }, [subtitleStyle]);

  useEffect(() => {
    localStorage.setItem(
      "clipcut-include-subtitles",
      String(includeSubtitles)
    );
  }, [includeSubtitles]);

  useEffect(() => {
    localStorage.setItem(
      "clipcut-subtitle-position",
      subtitlePosition
    );
  }, [subtitlePosition]);

  const loadJobs = useCallback(async () => {
    try {
      const data = await apiRequest("/jobs/");
      const list = Array.isArray(data)
        ? data
        : data.results || data.jobs || [];

      setJobs(list);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    // This fetch synchronizes the saved project list on mount.
    // oxlint-disable-next-line react/set-state-in-effect
    loadJobs();
  }, [loadJobs]);

  function navigate(nextPage) {
    setError("");
    setNotice("");
    setPage(nextPage);
  }

  async function refreshJob(jobId) {
    const data = await apiRequest(`/jobs/${jobId}/`);
    const job = data.job || data;

    setActiveJob(job);
    setJobs((previous) => {
      const exists = previous.some(
        (item) => item.id === job.id
      );

      if (!exists) return [job, ...previous];

      return previous.map((item) =>
        item.id === job.id ? job : item
      );
    });

    if (activeClip) {
      const updatedClip = (job.clips || []).find(
        (item) => item.id === activeClip.id
      );

      if (updatedClip) {
        setActiveClip(updatedClip);
      }
    }

    return job;
  }

  async function createProject(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");

    try {
      if (!file && !sourceUrl.trim()) {
        throw new Error(
          "Choose a video file or enter a source URL."
        );
      }

      if (file && file.size > MAX_UPLOAD_BYTES) {
        throw new Error("The maximum upload size is 500 MB.");
      }

      if (
        file &&
        !ALLOWED_VIDEO_EXTENSIONS.some((extension) =>
          file.name.toLowerCase().endsWith(extension)
        )
      ) {
        throw new Error(
          "Unsupported video file. Choose MP4, MOV, MKV, or WebM."
        );
      }

      const formData = new FormData();
      formData.append(
        "title",
        title.trim() || file?.name || "Untitled project"
      );
      formData.append("language", "auto");
      formData.append("aspect_ratio", aspectRatio);
      formData.append("subtitle_style", subtitleStyle);
      formData.append("include_subtitles", String(includeSubtitles));
      formData.append("subtitle_position", subtitlePosition);
      formData.append("subtitle_font_size", String(captionSize));
      formData.append("subtitle_color", captionColor.toUpperCase());

      if (file) {
        formData.append("source_file", file);
      }

      if (sourceUrl.trim()) {
        formData.append("source_url", sourceUrl.trim());
      }

      const data = await apiRequest("/jobs/", {
        method: "POST",
        body: formData,
      });

      const job = data.job || data;

      setActiveJob(job);
      setJobs((previous) => [
        job,
        ...previous.filter((item) => item.id !== job.id),
      ]);

      setFile(null);
      setTitle("");
      setSourceUrl("");

      await startProcessing(job.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function startProcessing(jobId) {
    setBusy(true);
    setError("");
    setNotice("");
    setPage("processing");

    try {
      const data = await apiRequest(
        `/jobs/${jobId}/process/`,
        { method: "POST" }
      );

      const job = data.job || data;

      setActiveJob(job);
      setJobs((previous) =>
        previous.map((item) =>
          item.id === job.id ? job : item
        )
      );

      await refreshJob(jobId);
      setPage("results");
    } catch (err) {
      let message = err.message;
      const failedJob = err.data?.job;

      if (failedJob) {
        setActiveJob(failedJob);
        setJobs((previous) =>
          previous.map((item) =>
            item.id === failedJob.id ? failedJob : item
          )
        );
      } else {
        try {
          await refreshJob(jobId);
        } catch (refreshError) {
          message = `${message} Could not refresh the project: ${refreshError.message}`;
        }
      }

      setError(message);
      setPage("results");
    } finally {
      setBusy(false);
    }
  }

  async function openJob(job) {
    setBusy(true);
    setError("");

    try {
      const data = await apiRequest(`/jobs/${job.id}/`);
      const fullJob = data.job || data;

      setActiveJob(fullJob);
      setActiveClip(null);
      setPage("results");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function deleteJob(jobId) {
    const confirmed = window.confirm(
      "Delete this project? This action cannot be undone."
    );

    if (!confirmed) return;

    setError("");

    try {
      await apiRequest(`/jobs/${jobId}/delete/`, {
        method: "DELETE",
      });

      setJobs((previous) =>
        previous.filter((job) => job.id !== jobId)
      );

      if (activeJob?.id === jobId) {
        setActiveJob(null);
        setActiveClip(null);
      }

      setNotice("Project deleted.");
    } catch (err) {
      setError(err.message);
    }
  }

  function openClip(clip, job = activeJob) {
    setActiveJob(job);
    setActiveClip(clip);
    setAspectRatio(job?.aspect_ratio || "9:16");
    setSubtitleStyle(job?.subtitle_style || "classic");
    setIncludeSubtitles(job?.include_subtitles !== false);
    setSubtitlePosition(job?.subtitle_position || "bottom");
    setCaptionSize(job?.subtitle_font_size || 20);
    setCaptionColor(job?.subtitle_color || "#FFFFFF");
    setPage("editor");
  }

  const clips = activeJob?.clips || [];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button
          className="brand"
          onClick={() => navigate("home")}
        >
          <span className="brand-icon">✂</span>
          <span>
            ClipCut <b>AI</b>
          </span>
        </button>

        <div className="sidebar-label">WORKSPACE</div>

        <nav className="side-nav">
          {navItems.map(([key, label, icon]) => (
            <button
              key={key}
              className={`nav-item ${
                page === key ? "active" : ""
              }`}
              onClick={() => navigate(key)}
            >
              <span className="nav-icon">{icon}</span>
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="sidebar-tip">
            <span className="tip-icon">✦</span>
            <h4>Make every second count</h4>
            <p>
              Turn your long videos into short, engaging clips.
            </p>
            <button
              className="primary-btn full-btn"
              onClick={() => navigate("upload")}
            >
              Create Shorts
            </button>
          </div>

          <div className="sidebar-footer">
            ClipCut AI · Local MVP
          </div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div>
            <p className="breadcrumb">WORKSPACE / CLIPCUT AI</p>
            <h2>{pageTitle(page)}</h2>
          </div>

          <button
            className="primary-btn top-create"
            onClick={() => navigate("upload")}
          >
            + New Project
          </button>
        </header>

        {(error || notice) && (
          <div
            className={`app-message ${
              error ? "error-message" : "success-message"
            }`}
          >
            <span>{error || notice}</span>
            <button
              onClick={() => {
                setError("");
                setNotice("");
              }}
              aria-label="Dismiss message"
            >
              ×
            </button>
          </div>
        )}

        {page === "home" && (
          <HomePage
            jobs={jobs}
            onCreate={() => navigate("upload")}
            onProjects={() => navigate("projects")}
            onOpenJob={openJob}
            busy={busy}
          />
        )}

        {page === "upload" && (
          <UploadPage
            file={file}
            setFile={setFile}
            title={title}
            setTitle={setTitle}
            sourceUrl={sourceUrl}
            setSourceUrl={setSourceUrl}
            aspectRatio={aspectRatio}
            setAspectRatio={setAspectRatio}
            subtitleStyle={subtitleStyle}
            setSubtitleStyle={setSubtitleStyle}
            includeSubtitles={includeSubtitles}
            setIncludeSubtitles={setIncludeSubtitles}
            subtitlePosition={subtitlePosition}
            setSubtitlePosition={setSubtitlePosition}
            captionSize={captionSize}
            setCaptionSize={setCaptionSize}
            captionColor={captionColor}
            setCaptionColor={setCaptionColor}
            busy={busy}
            onSubmit={createProject}
          />
        )}

        {page === "processing" && (
          <ProcessingPage
            job={activeJob}
            busy={busy}
            onProjects={() => navigate("projects")}
          />
        )}

        {page === "results" && (
          <ResultsPage
            job={activeJob}
            clips={clips}
            busy={busy}
            onOpenClip={(clip) => openClip(clip)}
            onProcess={() =>
              activeJob && startProcessing(activeJob.id)
            }
            onProjects={() => navigate("projects")}
          />
        )}

        {page === "editor" && (
          <EditorPage
            job={activeJob}
            clip={activeClip}
            captionSize={captionSize}
            setCaptionSize={setCaptionSize}
            captionColor={captionColor}
            setCaptionColor={setCaptionColor}
            aspectRatio={aspectRatio}
            setAspectRatio={setAspectRatio}
            subtitleStyle={subtitleStyle}
            setSubtitleStyle={setSubtitleStyle}
            includeSubtitles={includeSubtitles}
            setIncludeSubtitles={setIncludeSubtitles}
            subtitlePosition={subtitlePosition}
            setSubtitlePosition={setSubtitlePosition}
            onBack={() => navigate("results")}
            onRendered={() =>
              activeJob && refreshJob(activeJob.id)
            }
            onExport={() => navigate("export")}
          />
        )}

        {page === "export" && (
          <ExportPage
            job={activeJob}
            clip={activeClip}
            onBack={() => navigate("editor")}
          />
        )}

        {page === "projects" && (
          <ProjectsPage
            jobs={jobs}
            onRefresh={loadJobs}
            onCreate={() => navigate("upload")}
            onOpen={openJob}
            onDelete={deleteJob}
            busy={busy}
          />
        )}

        {page === "settings" && (
          <SettingsPage
            captionSize={captionSize}
            setCaptionSize={setCaptionSize}
            captionColor={captionColor}
            setCaptionColor={setCaptionColor}
            aspectRatio={aspectRatio}
            setAspectRatio={setAspectRatio}
            subtitleStyle={subtitleStyle}
            setSubtitleStyle={setSubtitleStyle}
            includeSubtitles={includeSubtitles}
            setIncludeSubtitles={setIncludeSubtitles}
            subtitlePosition={subtitlePosition}
            setSubtitlePosition={setSubtitlePosition}
          />
        )}

        {page === "profile" && (
          <ProfilePage
            onLogout={() => navigate("home")}
          />
        )}

        {page === "help" && (
          <HelpPage onCreate={() => navigate("upload")} />
        )}

        {page === "about" && (
          <AboutPage onCreate={() => navigate("upload")} />
        )}

        {page === "contact" && <ContactPage />}

        {(page === "privacy" || page === "terms") && (
          <LegalPage type={page} />
        )}

        {(page === "login" || page === "signup") && (
          <AuthPage
            mode={page}
            onSwitch={navigate}
            onSuccess={() => navigate("home")}
          />
        )}

        {page === "notfound" && (
          <NotFoundPage onHome={() => navigate("home")} />
        )}
      </main>
    </div>
  );
}

/* ---------------- HOME PAGE ---------------- */

function HomePage({
  jobs,
  onCreate,
  onProjects,
  onOpenJob,
  busy,
}) {
  const totalClips = jobs.reduce(
    (total, job) => total + (job.clips?.length || 0),
    0
  );

  return (
    <div className="page-content">
      <section className="hero">
        <div className="hero-copy">
          <span className="pill">AI VIDEO WORKSPACE</span>
          <h1>
            Your videos.
            <br />
            <span className="gradient-text">
              A thousand possibilities.
            </span>
          </h1>
          <p>
            Turn long videos into engaging Shorts with AI-assisted
            highlights and English subtitles translated from speech.
          </p>

          <div className="hero-actions">
            <button
              className="primary-btn large-btn"
              onClick={onCreate}
            >
              ✦ Create Shorts
            </button>

            <button
              className="secondary-btn"
              onClick={onProjects}
            >
              View Projects
            </button>
          </div>
        </div>

        <div className="hero-preview">
          <div className="preview-window">
            <div className="preview-top">
              <span className="status-dot" />
              YOUR VIDEO WORKFLOW
            </div>

            <div className="video-mock">
              <div className="mock-play">▶</div>
              <div className="mock-caption">
                Turn moments into stories.
              </div>
            </div>

            <div className="mock-timeline">
              <span />
              <span />
              <span />
              <span />
              <span />
              <span />
            </div>

            <div className="mock-footer">
              <span>AI HIGHLIGHTS</span>
              <span>9:16 PORTRAIT</span>
            </div>
          </div>
        </div>
      </section>

      <SectionHeading
        title="Your workspace"
        subtitle="A quick look at your video projects."
      />

      <div className="stats-grid">
        <StatCard
          label="Total Projects"
          value={jobs.length}
          icon="▤"
        />
        <StatCard
          label="Clips Generated"
          value={totalClips}
          icon="▶"
        />
        <StatCard
          label="Subtitle Languages"
          value="2+"
          icon="Aa"
        />
      </div>

      <div className="section-row">
        <SectionHeading
          title="Recent projects"
          subtitle="Continue where you left off."
        />

        <button className="text-button" onClick={onProjects}>
          View all →
        </button>
      </div>

      {jobs.length === 0 ? (
        <EmptyState
          title="Your workspace is ready"
          description="Upload a video or paste a public YouTube link to start creating Shorts."
          action="Create your first project"
          onClick={onCreate}
        />
      ) : (
        <div className="project-grid">
          {jobs.slice(0, 4).map((job) => (
            <ProjectCard
              key={job.id}
              job={job}
              onOpen={() => onOpenJob(job)}
            />
          ))}
        </div>
      )}

      {busy && <p className="muted">Loading project…</p>}
    </div>
  );
}

/* ---------------- UPLOAD PAGE ---------------- */

function UploadPage({
  file,
  setFile,
  title,
  setTitle,
  sourceUrl,
  setSourceUrl,
  aspectRatio,
  setAspectRatio,
  subtitleStyle,
  setSubtitleStyle,
  includeSubtitles,
  setIncludeSubtitles,
  subtitlePosition,
  setSubtitlePosition,
  captionSize,
  setCaptionSize,
  captionColor,
  setCaptionColor,
  busy,
  onSubmit,
}) {
  return (
    <div className="page-content narrow-page">
      <SectionHeading
        title="Create a new project"
        subtitle="Upload a video or paste a public YouTube link to generate short clips."
      />

      <form className="panel upload-form" onSubmit={onSubmit}>
        <label className="field-label">Project name</label>
        <input
          className="text-input"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="e.g. Podcast Episode 01"
        />

        <label className="field-label">
          Upload video or paste a public YouTube link
        </label>
        <label className="drop-zone">
          <input
            type="file"
            accept="video/*,.mp4,.mov,.mkv,.webm"
            onChange={(event) =>
              setFile(event.target.files?.[0] || null)
            }
            hidden
          />

          <span className="upload-icon">↑</span>
          <strong>
            {file ? file.name : "Choose a video to upload"}
          </strong>
          <span className="muted">
            MP4, MOV, MKV, or WebM · up to 500 MB
          </span>
          {file && (
            <span className="file-size">
              {(file.size / (1024 * 1024)).toFixed(1)} MB
            </span>
          )}
        </label>

        <div className="or-divider">
          <span>OR</span>
        </div>

        <label className="field-label">
          Public YouTube URL (optional)
        </label>
        <input
          className="text-input"
          type="url"
          value={sourceUrl}
          onChange={(event) => setSourceUrl(event.target.value)}
          placeholder="https://www.youtube.com/watch?v=..."
        />

        <p className="help-text">
          Public YouTube videos are downloaded for processing.
          Playlists, private or age-restricted videos, and other
          websites are not supported. Only use videos you have
          permission to process.
        </p>

        <div className="english-subtitle-note">
          <strong>Optional English subtitles</strong>
          <span>
            When enabled, speech is detected automatically and translated
            into English when needed.
          </span>
          <span>
            ClipCut selects the strongest speech moments for clips around
            30–45 seconds.
          </span>
        </div>

        <div className="settings-divider">
          <span>OUTPUT & CAPTION STYLE</span>
        </div>

        <label className="field-label">Video ratio</label>
        <select
          className="text-input"
          value={aspectRatio}
          onChange={(event) => setAspectRatio(event.target.value)}
        >
          {ASPECT_RATIOS.map((ratio) => (
            <option key={ratio.value} value={ratio.value}>
              {ratio.label}
            </option>
          ))}
        </select>
        <p className="ratio-size-note" aria-live="polite">
          Output size: <strong>{getAspectRatioOption(aspectRatio).size}</strong>
        </p>
        <p className="help-text">
          Portrait is ideal for Shorts and Reels; square and landscape
          work well for feeds and standard video.
        </p>

        <SubtitleToggle
          checked={includeSubtitles}
          onChange={setIncludeSubtitles}
        />

        {includeSubtitles && (
          <>
            <label className="field-label">Subtitle style</label>
            <select
              className="text-input"
              value={subtitleStyle}
              onChange={(event) => setSubtitleStyle(event.target.value)}
            >
              {SUBTITLE_STYLES.map((style) => (
                <option key={style.value} value={style.value}>
                  {style.label}
                </option>
              ))}
            </select>

            <label className="field-label">Subtitle position</label>
            <select
              className="text-input"
              value={subtitlePosition}
              onChange={(event) => setSubtitlePosition(event.target.value)}
            >
              {SUBTITLE_POSITIONS.map((position) => (
                <option key={position.value} value={position.value}>
                  {position.label}
                </option>
              ))}
            </select>

            <label className="field-label">
              Subtitle size: {captionSize}px
            </label>
            <input
              className="range-input"
              type="range"
              min="12"
              max="36"
              step="1"
              value={captionSize}
              onChange={(event) =>
                setCaptionSize(Number(event.target.value))
              }
            />

            <label className="field-label">Subtitle color</label>
            <div className="color-picker-row">
              <input
                type="color"
                value={captionColor}
                onChange={(event) => setCaptionColor(event.target.value)}
              />
              <span>{captionColor.toUpperCase()}</span>
            </div>

            <div
              className={`caption-preview upload-caption-preview caption-preview-${subtitleStyle}`}
              style={{
                aspectRatio: RATIO_CSS[aspectRatio],
                color: captionColor,
                fontSize: `${Math.min(captionSize, 28)}px`,
              }}
            >
              <span className="caption-preview-text">
                Preview subtitles · {aspectRatio} ·{" "}
                {getAspectRatioOption(aspectRatio).size}
              </span>
            </div>
          </>
        )}

        <button
          className="primary-btn full-btn"
          type="submit"
          disabled={busy}
        >
          {busy ? "Please wait..." : "✦ Generate Shorts"}
        </button>
      </form>
    </div>
  );
}

/* ---------------- PROCESSING PAGE ---------------- */

function ProcessingPage({ job, busy, onProjects }) {
  return (
    <div className="page-content narrow-page">
      <div className="panel processing-panel">
        <div className="processing-orb">✦</div>
        <span className="pill">AI WORKFLOW</span>
        <h1>
          {busy ? "Creating your Shorts…" : "Processing requested"}
        </h1>
        <p className="muted">
          {job?.title || "Your video project"}
        </p>

        <div className="progress-track">
          <span className={busy ? "progress-animated" : ""} />
        </div>

        <p className="help-text">
          Whisper transcribes speech and FFmpeg renders video clips.
          Processing can take a while, especially on CPU-only systems.
        </p>

        <button className="secondary-btn" onClick={onProjects}>
          View Projects
        </button>
      </div>
    </div>
  );
}

/* ---------------- RESULTS PAGE ---------------- */

function ResultsPage({
  job,
  clips,
  busy,
  onOpenClip,
  onProcess,
  onProjects,
}) {
  if (!job) {
    return (
      <div className="page-content">
        <EmptyState
          title="No project selected"
          description="Open a project or upload a new video."
          action="View Projects"
          onClick={onProjects}
        />
      </div>
    );
  }

  return (
    <div className="page-content">
      <div className="section-row">
        <div>
          <h1 className="page-heading">{job.title}</h1>
          <p className="muted">
            {clips.length} clips generated
          </p>
        </div>

        <div className="button-row">
          <span className={`status-badge ${job.status || "created"}`}>
            {job.status || "created"}
          </span>
          <button
            className="primary-btn"
            onClick={onProcess}
            disabled={busy || (!job.source_file && !job.source_url)}
            title={
              !job.source_file && !job.source_url
                ? "Add a source video or public YouTube URL first"
                : "Generate clips from this video again"
            }
          >
            {busy ? "Processing…" : "Generate Again"}
          </button>
        </div>
      </div>

      {job.error_message && (
        <p className="error-text">{job.error_message}</p>
      )}

      {clips.length > 0 &&
        clips.every((clip) => !clip.transcript?.trim()) && (
          <p className="help-text">
            No speech was detected. These clips use evenly spaced
            sections of the video and do not include subtitles.
          </p>
        )}

      {clips.length === 0 ? (
        <EmptyState
          title="No clips yet"
          description={
            job.source_file
              ? "This project has no generated clips yet. Generate Shorts to process the uploaded video."
              : job.source_url
                ? "Generate Shorts to download and process this public YouTube video."
                : "Add a video source to generate Shorts."
          }
          action="View Projects"
          onClick={onProjects}
        />
      ) : (
        <div className="clip-grid">
          {clips.map((clip, index) => (
            <ClipCard
              key={clip.id}
              clip={clip}
              index={index}
              aspectRatio={job.aspect_ratio || "9:16"}
              onEdit={() => onOpenClip(clip)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------- EDITOR PAGE ---------------- */

function EditorPage({
  job,
  clip,
  captionSize,
  setCaptionSize,
  captionColor,
  setCaptionColor,
  aspectRatio,
  setAspectRatio,
  subtitleStyle,
  setSubtitleStyle,
  includeSubtitles,
  setIncludeSubtitles,
  subtitlePosition,
  setSubtitlePosition,
  onBack,
  onRendered,
  onExport,
}) {
  const [rendering, setRendering] = useState(false);
  const [renderMessage, setRenderMessage] = useState("");
  const [renderError, setRenderError] = useState("");

  if (!clip) {
    return (
      <div className="page-content">
        <EmptyState
          title="No clip selected"
          description="Choose a clip from your generated results."
          action="Back to Results"
          onClick={onBack}
        />
      </div>
    );
  }

  const videoUrl = getVideoUrl(clip);

  async function renderUpdatedClip() {
    if (!clip?.id) {
      setRenderError("No clip selected.");
      return;
    }

    setRendering(true);
    setRenderMessage("");
    setRenderError("");

    try {
      const data = await apiRequest(
        `/clips/${clip.id}/render/`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            font_size: captionSize,
            text_color: captionColor,
            aspect_ratio: aspectRatio,
            subtitle_style: subtitleStyle,
            subtitle_position: subtitlePosition,
            include_subtitles: includeSubtitles,
          }),
        }
      );

      if (data.clip) {
        // Update the preview immediately with the returned clip.
        const returnedClip = data.clip;
        setRenderMessage(
          "Clip re-rendered. Refreshing project information…"
        );

        await onRendered?.(returnedClip);
      } else {
        await onRendered?.();
      }

      setRenderMessage(
        "Clip re-rendered successfully. If the preview does not update, return to results and reopen the clip."
      );
    } catch (err) {
      setRenderError(err.message);
    } finally {
      setRendering(false);
    }
  }

  return (
    <div className="page-content">
      <div className="section-row">
        <div>
          <h1 className="page-heading">Edit your clip</h1>
          <p className="muted">
            {job?.title || "ClipCut AI project"}
          </p>
        </div>

        <button className="secondary-btn" onClick={onBack}>
          ← Back to Results
        </button>
      </div>

      <div className="editor-layout">
        <section className="panel editor-preview-panel">
          <div className="panel-heading">
            <div>
              <h3>{clip.title || "Untitled clip"}</h3>
              <p className="muted">
                {formatTime(getClipStart(clip))} –{" "}
                {formatTime(getClipEnd(clip))}
              </p>
            </div>
            <span className="pill">
              {ASPECT_RATIOS.find(
                (ratio) => ratio.value === aspectRatio
              )?.label || "Portrait · 9:16"}
            </span>
          </div>

          {videoUrl ? (
            <video
              className="editor-video"
              key={videoUrl}
              src={videoUrl}
              controls
              playsInline
              style={{ aspectRatio: RATIO_CSS[aspectRatio] }}
            />
          ) : (
            <div className="video-placeholder">
              <span className="mock-play">▶</span>
              <p>Video preview unavailable</p>
            </div>
          )}

          {clip.transcript && (
            <div className="transcript-box">
              <h4>Transcript</h4>
              <p>{clip.transcript}</p>
            </div>
          )}

          <button
            className="primary-btn full-btn"
            onClick={onExport}
          >
            Continue to Export →
          </button>
        </section>

        <aside className="panel editor-controls">
          <h3>Output Settings</h3>
          <p className="muted">
            Choose whether to include subtitles and adjust your output.
          </p>

          <label className="field-label">Video ratio</label>
          <select
            className="text-input"
            value={aspectRatio}
            onChange={(event) => setAspectRatio(event.target.value)}
          >
            {ASPECT_RATIOS.map((ratio) => (
              <option key={ratio.value} value={ratio.value}>
                {ratio.label}
              </option>
            ))}
          </select>
          <p className="ratio-size-note" aria-live="polite">
            Output size:{" "}
            <strong>{getAspectRatioOption(aspectRatio).size}</strong>
          </p>

          <SubtitleToggle
            checked={includeSubtitles}
            onChange={setIncludeSubtitles}
          />

          {includeSubtitles ? (
            <>
              <label className="field-label">Subtitle style</label>
              <select
                className="text-input"
                value={subtitleStyle}
                onChange={(event) => setSubtitleStyle(event.target.value)}
              >
                {SUBTITLE_STYLES.map((style) => (
                  <option key={style.value} value={style.value}>
                    {style.label}
                  </option>
                ))}
              </select>

              <label className="field-label">Subtitle position</label>
              <select
                className="text-input"
                value={subtitlePosition}
                onChange={(event) =>
                  setSubtitlePosition(event.target.value)
                }
              >
                {SUBTITLE_POSITIONS.map((position) => (
                  <option key={position.value} value={position.value}>
                    {position.label}
                  </option>
                ))}
              </select>

              <label className="field-label">
                Font size: {captionSize}px
              </label>
              <input
                className="range-input"
                type="range"
                min="12"
                max="36"
                step="1"
                value={captionSize}
                onChange={(event) =>
                  setCaptionSize(Number(event.target.value))
                }
              />

              <div className="range-labels">
                <span>Small</span>
                <span>Large</span>
              </div>

              <label className="field-label">Subtitle color</label>
              <div className="color-picker-row">
                <input
                  type="color"
                  value={captionColor}
                  onChange={(event) =>
                    setCaptionColor(event.target.value)
                  }
                />
                <span>{captionColor.toUpperCase()}</span>
              </div>

              <div
                className={`caption-preview caption-preview-${subtitleStyle}`}
                style={{
                  color: captionColor,
                  fontSize: `${Math.min(captionSize, 28)}px`,
                }}
              >
                <span className="caption-preview-text">
                  Your subtitles appear here
                </span>
              </div>
            </>
          ) : (
            <p className="help-text">
              Subtitles will be omitted from the rendered MP4. The video
              will retain its selected ratio and audio.
            </p>
          )}

          <button
            className="primary-btn full-btn"
            onClick={renderUpdatedClip}
            disabled={rendering}
          >
            {rendering
              ? "Rendering video..."
              : "Apply & Re-render MP4"}
          </button>

          {renderMessage && (
            <p className="success-text">{renderMessage}</p>
          )}

          {renderError && (
            <p className="error-text">{renderError}</p>
          )}

          <p className="help-text">
            Rendering may take time because the server transcribes
            the original video again. This changes the exported
            video, not just the preview.
          </p>
        </aside>
      </div>
    </div>
  );
}

/* ---------------- EXPORT PAGE ---------------- */

function ExportPage({ job, clip, onBack }) {
  if (!clip) {
    return (
      <div className="page-content">
        <EmptyState
          title="No clip selected"
          description="Select a clip before exporting."
          action="Back to Editor"
          onClick={onBack}
        />
      </div>
    );
  }

  const videoUrl = getVideoUrl(clip);

  return (
    <div className="page-content narrow-page">
      <SectionHeading
        title="Export your Short"
        subtitle="Your generated MP4 is ready to download."
      />

      <div className="panel export-panel">
        <div className="export-icon">↓</div>
        <h2>{clip.title || "Your ClipCut video"}</h2>
        <p className="muted">
          Project: {job?.title || "Untitled project"}
        </p>

        <div className="export-details">
          <div>
            <span>Format</span>
            <strong>MP4</strong>
          </div>
          <div>
            <span>Aspect ratio</span>
            <strong>
              {job?.aspect_ratio || DEFAULT_RATIO.value} ·{" "}
              {getAspectRatioOption(job?.aspect_ratio).size}
            </strong>
          </div>
          <div>
            <span>Duration</span>
            <strong>
              {formatTime(
                clip.duration ||
                  getClipEnd(clip) - getClipStart(clip)
              )}
            </strong>
          </div>
        </div>

        {videoUrl ? (
          <a
            className="primary-btn full-btn download-link"
            href={videoUrl}
            download={`${clip.title || "clipcut-short"}.mp4`}
            target="_blank"
            rel="noreferrer"
          >
            ↓ Download MP4
          </a>
        ) : (
          <p className="error-text">
            Video file URL is unavailable.
          </p>
        )}

        <button
          className="secondary-btn full-btn"
          onClick={onBack}
        >
          ← Back to Editor
        </button>
      </div>
    </div>
  );
}

/* ---------------- PROJECTS PAGE ---------------- */

function ProjectsPage({
  jobs,
  onRefresh,
  onCreate,
  onOpen,
  onDelete,
  busy,
}) {
  return (
    <div className="page-content">
      <div className="section-row">
        <SectionHeading
          title="My Projects"
          subtitle="Manage your saved video projects."
        />

        <div className="inline-actions">
          <button
            className="secondary-btn"
            onClick={onRefresh}
            disabled={busy}
          >
            ↻ Refresh
          </button>
          <button className="primary-btn" onClick={onCreate}>
            + New Project
          </button>
        </div>
      </div>

      {jobs.length === 0 ? (
        <EmptyState
          title="No projects yet"
          description="Create a project by uploading a video or pasting a public YouTube link."
          action="Create Project"
          onClick={onCreate}
        />
      ) : (
        <div className="project-grid">
          {jobs.map((job) => (
            <ProjectCard
              key={job.id}
              job={job}
              onOpen={() => onOpen(job)}
              onDelete={() => onDelete(job.id)}
              showDelete
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------- SUBTITLE SETTINGS ---------------- */

function SettingsPage({
  captionSize,
  setCaptionSize,
  captionColor,
  setCaptionColor,
  aspectRatio,
  setAspectRatio,
  subtitleStyle,
  setSubtitleStyle,
  includeSubtitles,
  setIncludeSubtitles,
  subtitlePosition,
  setSubtitlePosition,
}) {
  return (
    <div className="page-content narrow-page">
      <SectionHeading
        title="Creation Defaults"
        subtitle="Set the default ratio and caption appearance for new projects."
      />

      <div className="panel upload-form">
        <label className="field-label">Default video ratio</label>
        <select
          className="text-input"
          value={aspectRatio}
          onChange={(event) => setAspectRatio(event.target.value)}
        >
          {ASPECT_RATIOS.map((ratio) => (
            <option key={ratio.value} value={ratio.value}>
              {ratio.label}
            </option>
          ))}
        </select>

        <SubtitleToggle
          checked={includeSubtitles}
          onChange={setIncludeSubtitles}
          description="Use subtitles by default for new projects."
        />

        {includeSubtitles && (
          <>
            <label className="field-label">Default subtitle style</label>
            <select
              className="text-input"
              value={subtitleStyle}
              onChange={(event) => setSubtitleStyle(event.target.value)}
            >
              {SUBTITLE_STYLES.map((style) => (
                <option key={style.value} value={style.value}>
                  {style.label}
                </option>
              ))}
            </select>

            <label className="field-label">
              Default subtitle position
            </label>
            <select
              className="text-input"
              value={subtitlePosition}
              onChange={(event) =>
                setSubtitlePosition(event.target.value)
              }
            >
              {SUBTITLE_POSITIONS.map((position) => (
                <option key={position.value} value={position.value}>
                  {position.label}
                </option>
              ))}
            </select>

            <label className="field-label">
              Default font size: {captionSize}px
            </label>
            <input
              className="range-input"
              type="range"
              min="12"
              max="36"
              value={captionSize}
              onChange={(event) =>
                setCaptionSize(Number(event.target.value))
              }
            />

            <label className="field-label">Default text color</label>
            <div className="color-picker-row">
              <input
                type="color"
                value={captionColor}
                onChange={(event) =>
                  setCaptionColor(event.target.value)
                }
              />
              <span>{captionColor.toUpperCase()}</span>
            </div>

            <div
              className={`caption-preview settings-caption-preview caption-preview-${subtitleStyle}`}
              style={{
                color: captionColor,
                fontSize: `${Math.min(captionSize, 28)}px`,
              }}
            >
              <span className="caption-preview-text">
                Preview your subtitles
              </span>
            </div>
          </>
        )}

        <p className="help-text">
          Defaults are saved in this browser and preselected for new
          projects. Existing projects keep their own saved settings.
        </p>
      </div>
    </div>
  );
}

/* ---------------- PROFILE PAGE ---------------- */

function ProfilePage({ onLogout }) {
  const [name, setName] = useState(
    () => localStorage.getItem("clipcut-name") || ""
  );
  const [email, setEmail] = useState(
    () => localStorage.getItem("clipcut-email") || ""
  );
  const [message, setMessage] = useState("");

  function saveProfile(event) {
    event.preventDefault();

    localStorage.setItem("clipcut-name", name);
    localStorage.setItem("clipcut-email", email);

    setMessage("Preferences saved in this browser.");
  }

  return (
    <div className="page-content narrow-page">
      <SectionHeading
        title="Profile & Settings"
        subtitle="Manage your local application preferences."
      />

      <form className="panel upload-form" onSubmit={saveProfile}>
        <div className="profile-avatar">
          {(name.trim()[0] || "U").toUpperCase()}
        </div>

        <label className="field-label">Display name</label>
        <input
          className="text-input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Your name"
        />

        <label className="field-label">Email address</label>
        <input
          className="text-input"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@example.com"
        />

        <p className="help-text">
          This profile is browser-local. It is not a secure account
          and the email address is not verified.
        </p>

        <button className="primary-btn full-btn" type="submit">
          Save Preferences
        </button>

        {message && <p className="success-text">{message}</p>}

        <button
          type="button"
          className="secondary-btn"
          onClick={onLogout}
        >
          Return to Home
        </button>
      </form>
    </div>
  );
}

/* ---------------- HELP PAGE ---------------- */

function HelpPage({ onCreate }) {
  const [search, setSearch] = useState("");

  const faqs = [
    {
      q: "How do I create Shorts?",
      a: "Upload a video or paste a public YouTube link, choose the video ratio and caption style, then select Generate Shorts. Speech is automatically translated into English subtitles.",
    },
    {
      q: "Can videos in other languages get English subtitles?",
      a: "Yes. ClipCut detects the spoken language and translates the speech into English subtitles automatically.",
    },
    {
      q: "Why is processing slow?",
      a: "Whisper runs locally. Longer videos and CPU-only computers can take considerable time.",
    },
    {
      q: "Can I paste a YouTube link?",
      a: "Public HTTPS YouTube video links are downloaded and processed automatically. Playlists, private or age-restricted videos, and other websites are not supported. Only use videos you have permission to process.",
    },
    {
      q: "Why did subtitle rendering fail?",
      a: "Check FFmpeg installation, its subtitles filter, subtitle file paths, and available fonts.",
    },
    {
      q: "Where are my clips saved?",
      a: "Generated clips are stored in the Django MEDIA_ROOT directory.",
    },
  ];

  const filtered = faqs.filter((item) =>
    `${item.q} ${item.a}`
      .toLowerCase()
      .includes(search.toLowerCase())
  );

  return (
    <div className="page-content narrow-page">
      <SectionHeading
        title="Help & FAQ"
        subtitle="Find answers to common questions."
      />

      <input
        className="text-input faq-search"
        placeholder="Search questions..."
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />

      <div className="faq-list">
        {filtered.map((item) => (
          <details className="panel faq-item" key={item.q}>
            <summary>{item.q}</summary>
            <p>{item.a}</p>
          </details>
        ))}

        {!filtered.length && (
          <div className="panel empty-state">
            No matching questions found.
          </div>
        )}
      </div>

      <div className="panel help-cta">
        <h3>Ready to create something?</h3>
        <p className="muted">
          Start a new project and turn an authorized video into Shorts.
        </p>
        <button className="primary-btn" onClick={onCreate}>
          Create Shorts
        </button>
      </div>
    </div>
  );
}

/* ---------------- ABOUT PAGE ---------------- */

function AboutPage({ onCreate }) {
  return (
    <div className="page-content">
      <section className="hero">
        <div className="hero-copy">
          <span className="pill">ABOUT CLIPCUT AI</span>
          <h1>
            Long videos.
            <br />
            <span className="gradient-text">
              Shorter workflows.
            </span>
          </h1>
          <p>
            ClipCut AI transforms long videos into clips with speech
            translation, highlight selection, and English subtitles.
          </p>
          <button
            className="primary-btn large-btn"
            onClick={onCreate}
          >
            Try ClipCut AI →
          </button>
        </div>

        <div className="hero-preview">
          <div className="preview-window">
            <div className="preview-top">
              YOUR LOCAL VIDEO WORKFLOW
            </div>
            <div className="feature-grid about-steps">
              <FeatureCard number="01" title="Transcribe">
                Convert speech into timestamped text.
              </FeatureCard>
              <FeatureCard number="02" title="Select">
                Find promising speech segments.
              </FeatureCard>
              <FeatureCard number="03" title="Export">
                Render vertical MP4 clips.
              </FeatureCard>
            </div>
          </div>
        </div>
      </section>

      <SectionHeading
        title="Built with free tools"
        subtitle="A local-first technology stack."
      />

      <div className="feature-grid">
        <FeatureCard number="01" title="React">
          The interactive website and video workspace.
        </FeatureCard>
        <FeatureCard number="02" title="Django REST Framework">
          API endpoints and project metadata.
        </FeatureCard>
        <FeatureCard number="03" title="Whisper + FFmpeg">
          Local transcription, clip creation, and subtitle rendering.
        </FeatureCard>
      </div>
    </div>
  );
}

/* ---------------- CONTACT PAGE ---------------- */

function ContactPage() {
  const [category, setCategory] = useState("Bug Report");
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [notice, setNotice] = useState("");

  function submitFeedback(event) {
    event.preventDefault();

    const previous = JSON.parse(
      localStorage.getItem("clipcut-feedback") || "[]"
    );

    previous.push({
      category,
      email,
      message,
      createdAt: new Date().toISOString(),
    });

    localStorage.setItem(
      "clipcut-feedback",
      JSON.stringify(previous)
    );

    setNotice(
      "Feedback saved in this browser. It has not been sent to a server."
    );
    setMessage("");
  }

  return (
    <div className="page-content narrow-page">
      <SectionHeading
        title="Contact & Feedback"
        subtitle="Share a bug report or suggest a feature."
      />

      <form className="panel upload-form" onSubmit={submitFeedback}>
        <label className="field-label">Feedback category</label>
        <select
          className="text-input"
          value={category}
          onChange={(event) => setCategory(event.target.value)}
        >
          <option>Bug Report</option>
          <option>Feature Request</option>
          <option>Subtitle Issue</option>
          <option>General Feedback</option>
        </select>

        <label className="field-label">Email (optional)</label>
        <input
          className="text-input"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@example.com"
        />

        <label className="field-label">Message</label>
        <textarea
          className="text-input feedback-textarea"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          minLength={5}
          required
          placeholder="Tell us what happened..."
        />

        <button className="primary-btn full-btn" type="submit">
          Save Feedback
        </button>

        {notice && <p className="success-text">{notice}</p>}
      </form>
    </div>
  );
}

/* ---------------- LEGAL PAGES ---------------- */

function LegalPage({ type }) {
  const content = {
    privacy: {
      title: "Privacy Policy",
      intro: "How ClipCut AI handles project data.",
      sections: [
        [
          "Video files",
          "Uploaded videos are stored in the configured media directory. Anyone with access to the computer or server may be able to access them.",
        ],
        [
          "Processing",
          "Whisper and FFmpeg can process videos locally. External services you configure may transmit data outside the computer.",
        ],
        [
          "Project information",
          "Project names, URLs, timestamps, transcripts, and file paths may be stored in the database and media directory.",
        ],
        [
          "Deletion",
          "Use project deletion controls and manage backups responsibly. This MVP has no automatic retention policy.",
        ],
        [
          "Security",
          "Before public deployment, implement authentication, authorization, secure storage, upload validation, and production protections.",
        ],
      ],
    },
    terms: {
      title: "Terms of Service",
      intro: "Terms for using this experimental local video tool.",
      sections: [
        [
          "Your content",
          "You are responsible for ensuring you own or have permission to process every uploaded video.",
        ],
        [
          "YouTube content",
          "A URL alone does not grant permission to download, reproduce, or edit a video. Follow the platform's terms and applicable law.",
        ],
        [
          "AI results",
          "Highlight selection and speech recognition may be inaccurate. Review generated clips and captions before publishing.",
        ],
        [
          "Local limitations",
          "Processing speed and output quality depend on your computer and installed dependencies.",
        ],
        [
          "Acceptable use",
          "Do not use the application to infringe copyright, violate privacy, or create unlawful content.",
        ],
      ],
    },
  };

  const data = content[type];

  return (
    <div className="page-content narrow-page">
      <div className="panel legal-document">
        <span className="pill">CLIPCUT AI</span>
        <h1>{data.title}</h1>
        <p className="muted">{data.intro}</p>
        <p className="help-text">
          This is a draft for the MVP. Review it before public deployment.
        </p>

        {data.sections.map(([heading, text]) => (
          <section key={heading}>
            <h3>{heading}</h3>
            <p>{text}</p>
          </section>
        ))}
      </div>
    </div>
  );
}

/* ---------------- LOGIN / SIGNUP PROTOTYPE ---------------- */

function AuthPage({ mode, onSwitch }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");

  function submit(event) {
    event.preventDefault();
    setNotice(
      "Authentication is not connected yet. Connect this form to Django authentication before using real accounts."
    );
  }

  return (
    <div className="page-content narrow-page">
      <div className="panel auth-panel">
        <div className="brand auth-brand">
          <span className="brand-icon">✂</span>
          <span>
            ClipCut <b>AI</b>
          </span>
        </div>

        <h1>
          {mode === "login"
            ? "Welcome back"
            : "Create your account"}
        </h1>

        <p className="muted">
          {mode === "login"
            ? "Sign in to continue your video workflow."
            : "Start organizing your video projects."}
        </p>

        <form className="upload-form" onSubmit={submit}>
          <label className="field-label">Email</label>
          <input
            className="text-input"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />

          <label className="field-label">Password</label>
          <input
            className="text-input"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            minLength={8}
            required
          />

          <button className="primary-btn full-btn" type="submit">
            {mode === "login" ? "Sign In" : "Create Account"}
          </button>
        </form>

        {notice && <p className="help-text">{notice}</p>}

        <p className="auth-switch">
          {mode === "login"
            ? "New here? "
            : "Already have an account? "}

          <button
            className="text-button"
            onClick={() =>
              onSwitch(mode === "login" ? "signup" : "login")
            }
          >
            {mode === "login" ? "Create Account" : "Sign In"}
          </button>
        </p>
      </div>
    </div>
  );
}

/* ---------------- REUSABLE COMPONENTS ---------------- */

function SectionHeading({ title, subtitle }) {
  return (
    <div className="section-heading">
      <h2>{title}</h2>
      {subtitle && <p className="muted">{subtitle}</p>}
    </div>
  );
}

function StatCard({ label, value, icon }) {
  return (
    <div className="panel stat-card">
      <div className="stat-top">
        <span>{label}</span>
        <span className="stat-icon">{icon}</span>
      </div>
      <strong>{value}</strong>
    </div>
  );
}

function FeatureCard({ number, title, children }) {
  return (
    <div className="panel feature-card">
      <span className="feature-number">{number}</span>
      <h3>{title}</h3>
      <p className="muted">{children}</p>
    </div>
  );
}

function ProjectCard({
  job,
  onOpen,
  onDelete,
  showDelete = false,
}) {
  const clipCount = job.clips?.length || 0;
  const status = job.status || "created";

  return (
    <div className="panel project-card">
      <button className="project-open" onClick={onOpen}>
        <div className="project-thumbnail">
          <span className="project-play">▶</span>
          <span className="project-count">
            {clipCount} clips
          </span>
        </div>

        <div className="project-info">
          <h3>{job.title || `Project ${job.id}`}</h3>
          <p className="muted">
            {job.created_at
              ? new Date(job.created_at).toLocaleDateString()
              : "Saved project"}
          </p>
          <p className="muted">
            {job.aspect_ratio || DEFAULT_RATIO.value} ·{" "}
            {getAspectRatioOption(job.aspect_ratio).size} ·{" "}
            {SUBTITLE_STYLES.find(
              (style) => style.value === job.subtitle_style
            )?.label || "Classic Outline"}
          </p>
          <span className={`status-badge ${status}`}>
            {status}
          </span>
        </div>
      </button>

      {showDelete && (
        <button
          className="delete-button"
          onClick={onDelete}
          aria-label={`Delete ${job.title || "project"}`}
        >
          Delete
        </button>
      )}
    </div>
  );
}

function ClipCard({ clip, index, aspectRatio, onEdit }) {
  const videoUrl = getVideoUrl(clip);
  const ratioLabel =
    ASPECT_RATIOS.find((ratio) => ratio.value === aspectRatio)?.label ||
    "Portrait · 9:16";
  const ratioCss = RATIO_CSS[aspectRatio] || RATIO_CSS["9:16"];

  return (
    <div className="panel clip-card">
      {videoUrl ? (
        <video
          className="clip-thumbnail"
          src={videoUrl}
          preload="metadata"
          controls
          playsInline
          style={{ aspectRatio: ratioCss }}
        />
      ) : (
        <div
          className="clip-thumbnail clip-placeholder"
          style={{ aspectRatio: ratioCss }}
        >
          <span>▶</span>
        </div>
      )}

      <div className="clip-info">
        <div className="clip-title-row">
          <h3>{clip.title || `Highlight ${index + 1}`}</h3>
          <span className="clip-number">
            #{String(index + 1).padStart(2, "0")}
          </span>
        </div>

        <p className="muted">
          {formatTime(
            clip.duration ||
              getClipEnd(clip) - getClipStart(clip)
          )}{" "}
          · {ratioLabel}
        </p>

        {clip.transcript && (
          <p className="clip-transcript">
            {clip.transcript.slice(0, 120)}
            {clip.transcript.length > 120 ? "…" : ""}
          </p>
        )}

        <button
          className="primary-btn full-btn"
          onClick={onEdit}
        >
          Edit Clip →
        </button>
      </div>
    </div>
  );
}

function EmptyState({
  title,
  description,
  action,
  onClick,
}) {
  return (
    <div className="panel empty-state">
      <div className="empty-icon">✦</div>
      <h3>{title}</h3>
      <p className="muted">{description}</p>
      {action && onClick && (
        <button className="primary-btn" onClick={onClick}>
          {action}
        </button>
      )}
    </div>
  );
}

function NotFoundPage({ onHome }) {
  return (
    <div className="page-content">
      <EmptyState
        title="Page not found"
        description="The page you're looking for doesn't exist."
        action="Back to Home"
        onClick={onHome}
      />
    </div>
  );
}
