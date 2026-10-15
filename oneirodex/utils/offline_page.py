"""Self-contained, member-data-free offline document."""

from __future__ import annotations

from html import escape


def render_offline_page(retry_script_url: str) -> str:
    """Build the PWA fallback without a template engine or network CSS."""
    script = escape(retry_script_url, quote=True)
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0b0d10">
  <title>Offline — Oneirodex</title>
  <style>
    :root {{
      color-scheme: dark;
      --od-bg: #0b0d10;
      --od-surface: #141820;
      --od-text: #f2f4f8;
      --od-text-muted: #c4ccd8;
      --od-accent: #2fd67b;
      --od-accent-contrast: #0b0d10;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      min-height: 100vh;
      margin: 0;
      padding: clamp(2rem, 8vh, 6rem) 1rem;
      background: var(--od-bg);
      color: var(--od-text);
      font: 1rem/1.5 system-ui, sans-serif;
    }}
    .od-offline {{
      display: flex;
      max-width: 44rem;
      margin: 0 auto;
      flex-direction: column;
      gap: 1rem;
      padding: 1.5rem;
      border: 1px solid rgb(255 255 255 / 14%);
      border-radius: 1rem;
      background: var(--od-surface);
    }}
    .od-offline__title {{ margin: 0; font-size: clamp(1.5rem, 5vw, 2rem); }}
    .od-offline__lede, .od-offline__note {{ margin: 0; }}
    .od-offline__checks {{ display: grid; gap: .5rem; margin: 0; padding-left: 1.25rem; color: var(--od-text-muted); }}
    .od-offline__action {{
      min-height: 2.75rem;
      padding: .65rem 1rem;
      border: 0;
      border-radius: .5rem;
      background: var(--od-accent);
      color: var(--od-accent-contrast);
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    .od-offline__action:focus-visible {{ outline: 3px solid var(--od-text); outline-offset: 3px; }}
    .od-offline__note {{ color: var(--od-text-muted); font-size: .875rem; }}
  </style>
</head>
<body>
  <main class="od-offline">
    <h1 class="od-offline__title">No route to your library</h1>
    <p class="od-offline__lede">This device cannot reach the Oneirodex server right now. Nothing is lost — the library lives on the server, and the app reconnects on its own once the server is reachable again.</p>
    <ul class="od-offline__checks">
      <li>Is this device on the same network as the server?</li>
      <li>Is the server awake? A NAS that has spun down takes a moment.</li>
      <li>If you reach it by hostname, is DNS answering?</li>
    </ul>
    <p><button type="button" class="od-offline__action" id="od-offline-retry">Try again</button></p>
    <p class="od-offline__note">Installed copies keep no games and no covers on this device by design — see the PWA notes in the user guide.</p>
  </main>
  <script src="{script}" defer></script>
</body>
</html>'''
