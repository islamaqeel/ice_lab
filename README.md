# ICE LIBRARY

A tiny website where anyone can upload a file (documents/images) or save a URL.

## Run locally (Windows / PowerShell)

Create a virtual environment and install dependencies:

```powershell
cd c:\programming\curserr
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start the server:

```powershell
python app.py
```

Open:

- `http://127.0.0.1:5000`

## Notes

- Upload limit: **50MB**
- Uploaded files are stored in `.data/uploads/` (or `ICE_LIBRARY_UPLOAD_DIR`)
- Metadata is stored in `.data/ice_library.db` (or `ICE_LIBRARY_DB_PATH`)

## Deploy to Render

This repo includes `render.yaml` (Blueprint).

- **Create new Render service**: choose "Blueprint" and select your GitHub repo.
- **Persistent storage**: the blueprint creates a disk mounted at `/var/data`.
- **Admin**: set `ICE_LIBRARY_ADMIN_USER` + `ICE_LIBRARY_ADMIN_PASS` in Render Environment.
- **Start command**: uses Waitress (works on Render + Windows).

After deploy, open your Render URL.

