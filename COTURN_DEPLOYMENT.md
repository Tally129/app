# Self-hosted coturn for NMS Telehealth WebRTC

The Natural Medical Solutions telehealth stack uses **native browser WebRTC** with
FastAPI WebSocket signaling (see `/app/backend/server.py:/api/ws/visit/{id}`). For
peers behind symmetric NATs (corporate networks, mobile carrier-grade NAT, or
strict residential firewalls), a public **TURN** relay is required.

This document describes how to deploy a `coturn` server and wire it into the app
without changing any frontend or backend code (the app reads ICE servers from
the `/api/telehealth/ice` endpoint).

---

## 1. Provision a public host

Recommended: a single small VM (e.g., 2 vCPU / 2 GB RAM, Ubuntu 22.04 LTS) with
a **static public IPv4** and DNS entry such as `turn.natmedsol.com`.

Open these inbound ports on the cloud firewall:

| Port  | Protocol | Purpose                       |
|-------|----------|-------------------------------|
| 3478  | TCP+UDP  | TURN/STUN listener            |
| 5349  | TCP+UDP  | TURN over TLS (`turns:`)      |
| 49152-65535 | UDP | Relay media ports (default range) |

> If you must restrict the relay range, set `min-port`/`max-port` in the
> `turnserver.conf` block below. Smaller ranges → fewer concurrent calls.

## 2. Install coturn

```bash
sudo apt-get update
sudo apt-get install -y coturn certbot
sudo systemctl enable coturn
```

Edit `/etc/default/coturn`:

```bash
TURNSERVER_ENABLED=1
```

## 3. Issue a TLS cert (Let's Encrypt)

```bash
sudo certbot certonly --standalone -d turn.natmedsol.com
# certs land in /etc/letsencrypt/live/turn.natmedsol.com/
sudo chown turnserver:turnserver /etc/letsencrypt/live/turn.natmedsol.com/* -R
```

Set up auto-renewal hook to also restart coturn:

```bash
sudo tee /etc/letsencrypt/renewal-hooks/post/coturn-restart.sh <<'EOF'
#!/bin/bash
systemctl reload coturn
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/post/coturn-restart.sh
```

## 4. Configure `turnserver.conf`

Replace `/etc/turnserver.conf` with:

```conf
# /etc/turnserver.conf
listening-port=3478
tls-listening-port=5349

# Public IP and primary domain
listening-ip=0.0.0.0
external-ip=<YOUR.PUBLIC.IPV4>
realm=turn.natmedsol.com
server-name=turn.natmedsol.com

# Limit relay range (open these on the firewall above)
min-port=49152
max-port=65535

# Long-term credential mechanism w/ shared-secret rotation
use-auth-secret
static-auth-secret=<GENERATE-A-LONG-RANDOM-STRING>

# TLS material
cert=/etc/letsencrypt/live/turn.natmedsol.com/fullchain.pem
pkey=/etc/letsencrypt/live/turn.natmedsol.com/privkey.pem

# Lock down
no-multicast-peers
no-cli
no-loopback-peers
no-tlsv1
no-tlsv1_1

# Logging
log-file=/var/log/coturn/turnserver.log
simple-log
verbose
```

Restart:

```bash
sudo mkdir -p /var/log/coturn
sudo chown turnserver:turnserver /var/log/coturn
sudo systemctl restart coturn
sudo systemctl status coturn
```

## 5. Wire into the EMR backend

Add the following environment variables to `/app/backend/.env` (DO NOT remove
the existing `MONGO_URL` / `DB_NAME` / `JWT_SECRET` / `EMERGENT_LLM_KEY`):

```bash
TURN_HOST=turn.natmedsol.com
TURN_PORT=3478
TURN_TLS_PORT=5349
TURN_REALM=turn.natmedsol.com
TURN_SECRET=<same-string-as-static-auth-secret-above>
TURN_TTL_SECONDS=86400
```

The `/api/telehealth/ice` endpoint (already implemented in `server.py`) returns
`stun:` + `turn:` + `turns:` server URLs to the browser. With a `TURN_SECRET`
present, the endpoint mints **time-limited HMAC credentials** so you never embed
plaintext TURN passwords in the JS bundle.

A reload of the backend (`sudo supervisorctl restart backend`) picks up the new
ICE config — no frontend deploy required.

## 6. Verify

From the browser:

1. Open `/portal/{role}/telehealth` → click *Equipment test* tab → **TURN
   Reachability** should flip from "Not configured" to "OK".
2. Run an instant visit between two devices on different networks (one on LTE,
   one on home Wi-Fi). Check the in-call `Status` panel — `Relay (TURN)` should
   indicate the relay path is in use when direct P2P fails.

You can also test with:

```bash
turnutils_uclient -v -t -u test -w <secret> turn.natmedsol.com
```

## 7. Observability

- `tail -f /var/log/coturn/turnserver.log` shows every allocate/permission.
- `lsof -nPi :3478 | grep ESTABLISHED` shows live relays.
- Cloud metrics: monitor egress bandwidth (audio+video relayed traffic).

## 8. Cost guidance

A 2-vCPU / 2 GB / 4 TB-bandwidth VM (e.g., DigitalOcean / Hetzner) handles
~50 simultaneous one-on-one consults at ~1.5 Mbps per peer. Scale horizontally
by adding additional `turn.X.natmedsol.com` hosts and rotating them via DNS
round-robin or by listing multiple `turn:` URLs in `/api/telehealth/ice`.

---

**Maintained by:** Engineering — see `/app/memory/PRD.md` for stack overview.
**Last updated:** May 2026 (Phase 13).
