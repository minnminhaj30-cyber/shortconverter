# ClipCut AI

ClipCut AI is a local video-editing MVP. It accepts a video file or a public
YouTube video URL, detects spoken language and creates English subtitles with
Whisper, selects short highlight segments, renders clips in the selected
aspect ratio using FFmpeg, and lets you preview, restyle, and download them.

## Requirements

- Windows 10 or later
- Python 3.12 or later
- Node.js 20.19 or later (or 22.12 or later); yt-dlp uses it to extract
  YouTube streams
- FFmpeg available on `PATH`
- An internet connection the first time Whisper downloads its model

This is a local-only application. It has no user authentication, and project
files and generated videos are stored on this computer. Do not expose it to a
public network.

## GitHub Pages preview

The GitHub Actions workflow builds and publishes the frontend to
`https://minnminhaj30-cyber.github.io/shortconverter/` whenever changes are
pushed to `main`. In the repository settings, set **Pages → Build and
deployment → Source** to **GitHub Actions**. The Pages site hosts only the
frontend; API requests and video-processing features require a separately
deployed backend.

## Setup

1. Install FFmpeg and verify that `ffmpeg -version` works in a new terminal.
2. From the project folder, install backend dependencies:

   ```powershell
   py -3 -m venv backend\clipvenv
   backend\clipvenv\Scripts\python.exe -m pip install -r backend\requirements.txt
   ```

   Use an installed Python version supported by your Whisper/PyTorch packages.
   The project has also been run with Python 3.14.

3. Install frontend dependencies:

   ```powershell
   cd frontend\frontend
   npm ci
   cd ..\..
   ```

4. Start both services:

   ```powershell
   .\start-clipcut.bat
   ```

   The launcher applies database migrations, waits for the API, then starts
   the frontend. Open <http://127.0.0.1:5173>.

The first video may take longer while Whisper downloads the default `base`
model. To use a smaller/faster model, set `WHISPER_MODEL=tiny` in the backend
terminal before launching Django. Supported model names include `tiny`,
`base`, `small`, `medium`, and `large`; speed and transcription quality vary.

## Video workflow

1. Choose an MP4, MOV, MKV, or WebM file no larger than 500 MB.
   Alternatively, paste a public HTTPS YouTube video link. YouTube downloads
   are limited to 500 MB.
2. Create the project. Speech is detected automatically and translated into
   English subtitles when it is in another language. Pasting a URL starts the
   download and processing automatically. Choose Portrait (9:16), Square
   (1:1), or Landscape (16:9), and choose whether to include subtitles.
   When enabled, set a subtitle preset, placement, size, and color before
   generating.
3. Wait for downloading, transcription, and clip rendering to finish. The
   backend terminal reports processing errors; the project results page shows
   the saved error.
4. Open a generated clip to preview its transcript, toggle subtitles on or
   off, and adjust subtitle appearance. Applying changes re-renders the MP4.
5. Download the final MP4 from the export page.

Only public YouTube watch, Shorts, and `youtu.be` video links are supported;
playlists, private or age-restricted videos, and other websites are not.
YouTube availability can differ by region. Only process videos you are
authorized to use. Highlight selection is heuristic, so review the clips and
subtitles before publishing them.

ClipCut scores translated speech for strong hook, emphasis, and information
signals, then selects the best non-overlapping moments for clips around
30–45 seconds (targeting 40 seconds). Videos shorter than 30 seconds use the
available duration. If Whisper detects no speech, ClipCut creates up to five
evenly spaced clips without subtitles; these are time-based, not
AI-selected highlights.

Subtitle presets include Classic Outline, Bold Pop, Caption Box, Minimal
Shadow, Neon Glow, Highlight Bar, Cinema Serif, Typewriter, Heavy Outline,
and Soft Shadow. You can also place captions at the top, center, or bottom.
Change a project's video ratio or subtitle settings in the clip editor and
apply **Apply & Re-render MP4** to save the new settings to that project.
Subtitle inclusion is enabled by default and can be changed for each project;
the Creation Defaults page controls the browser's default for new projects.

## Development checks

From `backend\backend`:

```powershell
..\clipvenv\Scripts\python.exe manage.py test
..\clipvenv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

From `frontend\frontend`:

```powershell
npm run lint
npm run build
```

## Troubleshooting

- **502 / cannot reach the API:** keep both server windows open. Django listens
  on port 8000 and Vite proxies `/api` and `/media` to it. Check the backend
  window if the launcher reports that the API did not start.
- **FFmpeg not found:** install FFmpeg, add its `bin` directory to `PATH`, and
  restart the backend window.
- **URL download fails:** confirm the video is public, not age-restricted, and
  that the link is a single YouTube video rather than a playlist. Downloads
  over 500 MB are rejected. Make sure Node.js is installed and available on
  `PATH`, then restart the backend.
- **Model download or processing is slow:** Whisper runs locally and can be
  CPU-intensive. Try `WHISPER_MODEL=tiny` for faster processing.
- **No clips generated:** confirm the video has a valid duration. Videos with
  no detected speech are split into evenly spaced clips without subtitles.

## Local API

- `GET /api/jobs/` and `POST /api/jobs/`
- `GET /api/jobs/<id>/`
- `POST /api/jobs/<id>/process/`
- `DELETE /api/jobs/<id>/delete/`
- `POST /api/clips/<id>/render/`

This MVP deliberately omits accounts and background job queues. Those require
separate deployment and security decisions before the application can be
offered as a multi-user service.
