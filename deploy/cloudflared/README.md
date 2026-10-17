# GoldScalper — Cloudflare Tunnel setup

Expose the bot privately at `https://scalper.7pivot.site` without opening router
ports. Two equivalent paths are documented in `config.example.yml`; the
token-based path is recommended because it matches the existing 9router tunnel.

## Recommended: token-based tunnel

1. **Zero Trust dashboard** → Networks → Tunnels → **Create a tunnel**
   - Type: `cloudflared`
   - Name: `goldscalper`
2. **Public Hostname** tab → Add a public hostname:
   - Subdomain: `scalper`  Domain: `7pivot.site`
   - Service Type: `HTTP`  URL: `host.docker.internal:9090` (atau `bot:9090` jika tunnel satu network)
   - *(Pada Home-Server, route `scalper.7pivot.site` telah terhubung via container `9router_tunnel` ke `host.docker.internal:9090`)*.
3. Start stack di Home-Server:
   ```bash
   docker compose up -d
   ```
4. Verify:
   ```bash
   curl https://scalper.7pivot.site/health
   ```

## Recommended add-on: Cloudflare Access (auth)

To keep the dashboard private, add an Access application:

- Zero Trust → Access → Applications → **Add self-hosted**
  - Domain: `scalper.7pivot.site`
  - Policy: **Allow** → include your email (one-time PIN) or a service token
- Result: any device (including your Android phone) gets an OTP gate before the
  PWA loads. PWA "Add to Home Screen" still works behind Access.

## Alternative: Tailscale (private admin fallback)

Install Tailscale on the home-server and the phone. Reach the bot over the
tailnet IP `http://<server-tailnet-ip>:9090` with no public exposure. Useful as
an out-of-band admin path if Cloudflare is down.

## Notes

- `noTLSVerify: true` in the named-tunnel template is only needed because the
  origin (`bot:9090`) speaks plain HTTP inside the Docker network.
- Never commit `TUNNEL_TOKEN` or the credentials JSON. They are gitignored.
