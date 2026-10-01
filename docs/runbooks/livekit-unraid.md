# LiveKit on Unraid / Compose (Wave 16)

Optional household voice. Oneirodex mints short-lived JWTs; the browser talks to the LiveKit SFU.

## Compose profile

The SFU does **not** run in LiveKit's `--dev` mode and has no built-in key pair.
It reads `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` from `.env` (Compose passes them
to the container as `LIVEKIT_KEYS`), and the Oneirodex app reads the same two
values to mint tokens, so they match by construction.

```bash
# 1. Generate your own pair once (alphanumerics only; the secret must be >= 32 chars)
python -c "import secrets; print('LIVEKIT_API_KEY=odx' + secrets.token_hex(6)); print('LIVEKIT_API_SECRET=' + secrets.token_hex(32))"
#    (alternative: docker run --rm livekit/livekit-server generate-keys)

# 2. In .env (repo root): paste both lines, and set
#      ENABLE_LIVEKIT=true
#      LIVEKIT_URL=ws://127.0.0.1:7880    # LAN hostname for real browsers, or wss://livekit.lan behind TLS

# 3. Start the SFU, then reload the app so it picks up the keys
docker compose --profile livekit up -d livekit
docker compose up -d app
```

If either value is empty, the `livekit` container exits with
`one of key-file or keys must be provided` instead of running open. That is the
intended failure mode. If it exits with `Could not parse keys`, the value contains a
colon, `$`, `#` or a quote; regenerate with the command above. A secret made only of
digits is read as a number by LiveKit's YAML parser and dropped, so use hex as shown.

### Upgrading a stack that used `--dev`

Earlier Compose files ran `livekit-server --dev`, which accepts the public pair
`devkey` / `secret` from anyone who can reach port 7880, so anyone on the LAN could
mint room tokens. After `git pull`:

1. Generate a new pair (step 1 above) and replace `LIVEKIT_API_KEY` /
   `LIVEKIT_API_SECRET` in `.env`. A stack that keeps `devkey` / `secret` still
   starts, but LiveKit logs `secret is too short` and the tokens stay forgeable.
2. Recreate both containers so they agree on the new values:
   `docker compose --profile livekit up -d --force-recreate livekit app`
3. Check `docker compose logs livekit`: it must not say `starting in development mode`
   or `secret is too short`. Active voice sessions drop when the containers restart; members rejoin and get new tokens.

One behaviour change rides along with leaving `--dev`: dev mode silently pinned WebRTC
media to the single UDP port 7882, while normal mode uses UDP 50000-60000, which
Compose does not publish. The service therefore sets `--udp-port 7882` explicitly, and
the ports below are unchanged. If you copied the `livekit` service into your own
stack file, copy that flag too or voice connects and then carries no audio.

## Unraid notes

1. Publish TCP **7880** (HTTP/WS signaling), TCP **7881** (ICE over TCP, fallback) and UDP **7882** (media) on the LAN. These are `LIVEKIT_HOST_PORT`, `LIVEKIT_RTC_PORT` and `LIVEKIT_UDP_PORT`; the container ports are fixed. Port 7880 has to stay reachable by browsers, so it is bound on every interface, and the API secret is what stops anyone from minting a token. Keep it off the public internet.
2. Set `LIVEKIT_URL` to a hostname the **browser** can reach (not `localhost` inside the app container unless members browse from the same host).
3. Behind CGNAT or strict NAT, enable LiveKit embedded TURN or add Coturn; see [social-and-voice.md](../user/social-and-voice.md).
4. TLS: terminate with SWAG/NPM/`wss://` — browsers block insecure WS on HTTPS sites.

## Smoke test

1. Admin → Plugins → `rtc.livekit` should show **configured** when env is set.
2. Member → Activity → Voice lobby → **Get voice token** (must return room + url).
3. Optional: connect with [LiveKit Meet](https://meet.livekit.io/) custom URL + pasted token.

## Parental policy

Child accounts can join audio rooms. `POST /api/rtc/token` with `video` or `screenshare` true returns **403** for role `child`.

## Party rooms (opaque)

Prefer `household:party:<game_uuid>` — never put game titles in the SFU room name.
