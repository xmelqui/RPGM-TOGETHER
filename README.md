# RPGMT: Reading Lobby for RPG Maker games

One app for everyone. The **host** plays an RPG Maker game; **friends** join and
watch it live (video + the game's sound), press **Read** when they've read a
line, and can click on the picture to **ping** the host's screen. The game only
moves to the next line once **everyone**, host included, has read it.

Works with **any RPG Maker version (2000, 2003, XP, VX, VX Ace, MV, MZ)**: nothing
is installed into the game.

## Sharing it with friends

Send friends `RPGMT.zip` (built by `build_exe.py`, see below). They unzip it and
run `RPGMT.exe`. Nobody needs Python.

- **Windows SmartScreen:** it may say "Windows protected your PC" because the app
  isn't code-signed. Click *More info → Run anyway*.
- **Windows Firewall:** it asks the **host** the first time a lobby opens. Allow
  it (tick *Public* too if you use Hamachi or Radmin, whose networks often count
  as public), or friends can't connect.

## Hosting

1. Run `RPGMT.exe` → **Host**.
2. Start your game and pick its window in **Game window**. A restarted game is
   picked up automatically.
3. Open a line of dialogue, click **Select area...** and drag a box around the
   message window. Include its full height, but not the name box above it.
4. Pick how friends connect:
   - **Local network / VPN** (default): Hamachi, Radmin VPN, ZeroTier, Tailscale
     or the same home network. No outside servers: video and sound go straight
     between your PCs. Share the link RPGMT shows (e.g. `http://26.1.2.3:47800/?code=K7P2QX`).
     The log lists every address it found.
   - **Online link through Cloudflare:** no VPN needed. Share the
     `https://….trycloudflare.com` link. The video still tries to go directly
     between PCs; some strict networks (some universities, mobile data) can't do
     that, and those friends get a slower still-picture view.
5. Click **Create Lobby** and play normally.

While hosting:
- **Reading status:** you play normally and continue whenever you like. The bubble
  over the game (and on the stream) shows who's still reading the current line,
  e.g. *Waiting for Ana, Bob (1/3)*, then *✓ Everyone read*.
- **Hold the game until everyone has read** (optional checkbox): when dialogue
  appears, your confirm keys (Enter/Space/Z…) are held until everyone has pressed
  Read. Your own Enter counts as your Read, and RPGMT presses Enter in the game
  when everyone is done. The game must be the active window for that press, so if
  you clicked into another window, the log asks you to click back on the game.
- **Chat:** the host window's *Chat* tab shows everyone's messages and lets you
  write back. Friends' newest messages also appear in the top-left of your game
  screen for 12 seconds. *Options → Enable chat* turns chat on/off for everyone,
  and *Show chat in-game* controls the on-screen messages.
- **Log:** the host window and `%LOCALAPPDATA%\RPGMT\host.log` record every line,
  read and Enter press, to make it easy to see why something is stuck.
- **Ignoring menus:** item, equipment, save and shop screens put text all over the
  screen, so they're ignored. The *Detection:* line shows what RPGMT currently sees.
  Press **F8** in-game to switch the lobby off for a moment if it gets something wrong.
- **What friends see:** the game window's own picture (Windows Graphics Capture,
  like OBS), so other windows on top of the game don't matter, not even the
  viewer on the same PC. The status bubble and pings are drawn into the stream.
  Text detection reads the same picture. Without Windows Graphics Capture (very
  old Windows 10), RPGMT falls back to reading the screen, and then the game must
  stay uncovered.
- **Sound:** only the game's audio is streamed, never Discord or music players.

## Joining

Run `RPGMT.exe` → **Join**, enter your name and paste the host's link, and click
**Join**. The game fills the window, live with sound, and everything else floats
on top of it:
- **Space, Z or Enter:** you've read the current line, and
  your name in the member list turns green. (The keys are explained on the join
  screen, or in a short intro card when you join through the app.)
- **Members** appear as small pills in the bottom-right corner, turning green
  when someone has read the line.
- **Click the picture** to ping that spot on the host's screen (your name, your
  color). Clicks from several people on the same spot stack into a counter.
- **Click and drag** to draw on the host's screen. The line disappears 3 seconds
  after you let go.
- **Chat** floats under the members: new messages show for about 12 seconds,
  then fade. Press **T** (or move the mouse onto the chat) to see the whole
  history and type. Enter sends, Esc closes. You get the last 50 messages when
  you join.
- **Sound and chat toggles** appear in the game's bottom-left corner when you move
  the mouse there: 🔊 mutes the game (with a volume slider), and 💬 hides or shows
  the chat (the member pills stay). Both are remembered.

The lobby address also works in a normal browser (`http://26.1.2.3:47800`)
for anyone who can't run the app.

## Security

- **Lobby code:** every lobby gets a random 6-character code, and the link RPGMT
  shows already contains it (`http://…:47800/?code=K7P2QX`). Without the code,
  nobody can join, chat, ping or watch, even if they can reach your PC. A new
  lobby gets a new code. Share the link only with people you want in.
- **No secret joining from websites:** the lobby only accepts connections from its
  own page. Other websites (and "DNS rebinding" tricks) are refused.
- **Limits:** up to 16 friends and 48 open connections, a size limit on messages,
  rate limits on chat, pings, drawing and video reconnects, and names that can't
  impersonate the host. Connections that don't join within 10 seconds are closed,
  and an address that enters 10 wrong codes is blocked for 10 minutes.
  Invisible and right-to-left characters are stripped from names and chat, and
  chat is always shown as plain text.
- **Your PC:** friends can't send keys or files to your PC. The only key RPGMT
  presses is Enter in the game, in "hold" mode. The stream shows only the game
  window. `cloudflared.exe` (online mode only) is checked for Cloudflare's
  digital signature before it runs.
- **Good to know:** like any direct video connection (Discord, games), friends
  can see the IP address you connect with: your VPN address in LAN/VPN mode, or
  your public IP in online mode. Close the lobby when you're done.

## Troubleshooting

Run `RPGMT.exe --selftest`. It checks text reading, video and audio encoding, game
sound capture, the viewer window and the network addresses, then opens a report.
Also available: `RPGMT.exe --host`, and `RPGMT.exe --join <address> <name>`.

## Developing

```
run.bat                              (runs from source, creates .venv on first run)
.venv\Scripts\python build_exe.py    (builds dist\RPGMT\RPGMT.exe)
```

| File | Role |
| --- | --- |
| `rpgmt/launcher.py` | First screen (Host / Join) and command-line options |
| `rpgmt/app.py` | Host window and glue between the parts |
| `rpgmt/detector.py` | Reads the screen with OCR, tells dialogue from menus |
| `rpgmt/ocr.py` | Screen capture and Windows OCR with line positions |
| `rpgmt/gate.py` | Keyboard/mouse hook that holds the host's input, plus Enter injection |
| `rpgmt/overlay.py` | Status bubble and viewers' pings drawn over the game |
| `rpgmt/stream.py` | Live video + sound to each viewer (WebRTC) |
| `rpgmt/audio.py` | Captures only the game process's sound (Windows 10 2004+) |
| `rpgmt/lobby.py` | Lobby state, web server and stream setup |
| `rpgmt/netinfo.py` | Finds the host's LAN / VPN addresses |
| `rpgmt/tunnel.py` | Optional Cloudflare quick tunnel |
| `rpgmt/viewer.py` | Friends' viewer window (WebView2) |
| `rpgmt/web/index.html` | The viewer page (also works in a browser) |
| `rpgmt/selftest.py` | `--selftest` report |

## Known limits

- **Not perfect by design:** OCR only has to notice that dialogue is there. Unusual
  screens (title screens, custom menus with little text) can still be mistaken
  for dialogue. Use F8.
- **Clean up text** (on by default) keeps only white letters before OCR. Turn it off
  for games with dark or colored dialogue text.
- **OCR language:** Windows can only read languages whose OCR pack is installed
  (Settings → Time & language → Language). Japanese games need the Japanese pack.
- **Gamepads** aren't held back, only keyboard and mouse.
- **Exclusive fullscreen** (old games with Alt+Enter) hides the overlays. Use
  windowed mode.
- **Upload speed:** each viewer uses roughly 2–4 Mbps of the host's upload.
