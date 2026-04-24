# Cloudflare Tunnel — Remote/Mobile Access for Dashboard V2

`cloudflared` lets you reach the local dashboard from your phone (anywhere
in the world) over a free, encrypted, randomly-named `*.trycloudflare.com`
URL — no port forwarding, no firewall changes.

## 1. Install

```powershell
winget install --id Cloudflare.cloudflared -e
```

Restart the terminal so `cloudflared` is on PATH.

## 2. Quick & dirty — anonymous tunnel (no account)

While the dashboard is running on port 5002:

```powershell
cloudflared tunnel --url http://localhost:5002
```

Cloudflared prints a URL like `https://xyz-abc-def.trycloudflare.com`.
Open it on your phone. Tap "Add to Home Screen" and the PWA installs as
an icon — runs full-screen, offline-capable.

This URL changes every restart. For a stable URL use a named tunnel:

## 3. Named tunnel (stable URL — needs a free Cloudflare account)

```powershell
cloudflared tunnel login                # opens browser → pick your domain
cloudflared tunnel create bitvavo-bot
cloudflared tunnel route dns bitvavo-bot bot.<your-domain>
```

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: bitvavo-bot
credentials-file: C:\Users\<you>\.cloudflared\<UUID>.json
ingress:
  - hostname: bot.<your-domain>
    service: http://localhost:5002
  - service: http_status:404
```

Run as a Windows service so it auto-starts:

```powershell
cloudflared service install
```

Now `https://bot.<your-domain>` always points to the dashboard. Add HTTP
basic-auth via Cloudflare Access if you want a login wall — recommended
for public access.

## 4. Security checklist

The dashboard is read-only (no order endpoints), but it does expose your
PnL, balance, and trade history. If you put it on a public URL:

- [ ] Enable Cloudflare Access (Zero Trust → Access → one-time PIN to email)
- [ ] Or set BASIC_AUTH_USER / BASIC_AUTH_PASS env vars (TODO middleware)
- [ ] Don't commit `~/.cloudflared/<UUID>.json` to git
