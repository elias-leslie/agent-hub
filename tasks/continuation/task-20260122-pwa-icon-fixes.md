# Continuation: PWA Icon Fixes

**Created:** 2026-01-22
**Context:** PWA support added to all projects, but some icons need fixes

## Completed This Session

1. Fixed WebSocket CORS/302 errors:
   - Added `/ws/*` rewrites to SummitFlow and Terminal next.config.ts
   - Updated `getWsUrl()` in all projects to use same-origin (PROD_DOMAIN)
   - Terminal now works (was completely broken before)

2. Added PWA support to all projects:
   - SummitFlow, Terminal, Portfolio-AI, Agent Hub, Monkey Fight
   - Created manifest.json, sw.js, icons for each
   - Added service worker registration to layouts

3. Created distinct icons:
   - SummitFlow: Outrun/synthwave style (sun, mountains, grid)
   - Terminal: Terminal window with green prompt
   - Portfolio-AI: Upward trending chart (blue/purple)
   - Monkey Fight: Brown monkey face with battle scar
   - Agent Hub: Network hub with colorful nodes and "AI" center

4. Created CORS pattern template library:
   - `~/.claude/templates/frontend-api-pattern/`

## Remaining Work

### 1. Brighten SummitFlow Icon

User feedback: "SummitFlow looks pretty good now but it should be brightened up a bit...the colors are a bit subdued"

Location: `~/summitflow/frontend/public/icons/icon.svg`

Suggested changes:
- Increase sun glow opacity (currently 0.25 → try 0.4)
- Make grid lines brighter (#ff0066 → #ff3388)
- Possibly add more contrast to mountains

After editing SVG, regenerate PNGs:
```bash
cd ~/summitflow/frontend/public/icons
rsvg-convert -w 192 -h 192 icon.svg -o icon-192.png
rsvg-convert -w 512 -h 512 icon.svg -o icon-512.png
```

### 2. Fix Agent Hub and Monkey Fight Icons Not Updating

User feedback: "Agent-Hub and Monkey-Fight are still showing the generic H with a green dot"

The new icons ARE in the files (verified visually in this session):
- Agent Hub: Network hub with "AI" center
- Monkey Fight: Monkey face with battle scar

This is a **browser/PWA caching issue**, not a code issue. The user needs to:

1. Clear PWA cache:
   - Open site in Chrome
   - DevTools (F12) → Application → Service Workers → Unregister
   - Application → Storage → Clear site data
   - Hard refresh (Ctrl+Shift+R)

2. Or uninstall and reinstall the PWA:
   - Right-click desktop shortcut → Uninstall
   - Visit site in browser
   - Reinstall from browser prompt

3. Cache versions were already bumped (v3→v4 for Agent Hub, v1→v2 for others)

### 3. Verify All PWAs Work

After user clears cache/reinstalls, verify:
- [ ] SummitFlow icon shows outrun style
- [ ] Terminal icon shows terminal prompt
- [ ] Portfolio-AI icon shows chart
- [ ] Monkey Fight icon shows monkey face
- [ ] Agent Hub icon shows network hub

## Key Patterns Discovered

1. **WebSocket CORS Fix**: Add `/ws/*` rewrite + use same-origin in getWsUrl()
2. **PWA Icon Updates**: Bump SW cache version + user must clear browser cache
3. **SVG to PNG**: Use `rsvg-convert -w SIZE -h SIZE icon.svg -o icon-SIZE.png`

## Files Changed This Session

- `~/.cloudflared/config.yml` - Reverted (no changes needed)
- `~/.claude/templates/frontend-api-pattern/` - Created CORS pattern library
- All projects: Added PWA files (manifest.json, sw.js, icons/)
- All projects: Updated layouts with PWA metadata
- SummitFlow, Terminal: Added /ws/* rewrite to next.config.ts
- All projects: Updated getWsUrl() for same-origin routing

## Resume Command

```
/do_it /home/kasadis/agent-hub/tasks/continuation/task-20260122-pwa-icon-fixes.md
```
