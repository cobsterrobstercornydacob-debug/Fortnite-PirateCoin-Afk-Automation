import time
import random
import threading
import requests
import cv2
from core.config import (
    W_SPACE_INTERVAL,
    SHOP_ACCESS_COOLDOWN,
    is_safe_click_area
)
from core.input_handler import (
    press_w_space,
    press_key,
    safe_click,
    ensure_fortnite_foreground
)
from core.vision import (
    capture_screen,
    match_template,
    load_all_templates
)
from core.state import (
    state,
    add_log,
    broadcast_state
)

# ── Discord webhook ───────────────────────────────────────────────
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1570236308834484355/_DwCttXn7u2fvxSA9jm7hi1woQsBIIX4C-fn1vE-Haxy3hcL7TDao-oYPNAZ5SianBBy"

def send_discord_notification(total_drops: int):
    if not DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URL == "YOUR_WEBHOOK_URL_HERE":
        return
    payload = {
        "username": "Pirate Farm 🏴‍☠️",
        "embeds": [{
            "title": "🎉 PIRATE SHOP ACCESS FOUND!",
            "description": (
                f"Your farm just hit a **Pirate Shop Access Token**!\n"
                f"**Total drops this session: {total_drops}**\n\n"
                "Go activate it before it expires! ⏰"
            ),
            "color": 0xF4C430,
            "footer": {"text": "Nyr0 Pirate Coin Automation"}
        }]
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
    except Exception:
        pass
# ─────────────────────────────────────────────────────────────────


def w_space_worker():
    while not state.stop_event.is_set():
        if state.running and state.w_space and state.status not in ("MATCHMAKING", "IDLE"):
            press_w_space()
            if random.random() < 0.35:
                add_log("Action: Jump-Walk (W + Space) active", "action")
        state.stop_event.wait(W_SPACE_INTERVAL)

def worker_loop():
    templates = load_all_templates()
    state.status = "IN MATCH"
    state.match_start_time = time.time()
    state.last_afk_time = time.time()
    last_skip_time = 0.0
    broadcast_state()
    add_log("Macro engine active. Watching for team elimination and Play Again...", "action")

    while not state.stop_event.is_set():
        try:
            now = time.time()
            if state.anti_afk and (now - state.last_afk_time >= state.afk_interval):
                if ensure_fortnite_foreground():
                    k = random.choice(["w", "a", "s", "d"])
                    press_key(k)
                    state.last_afk_time = now

            frame, ox, oy, fw, fh = capture_screen(1)
            if frame is None:
                state.stop_event.wait(state.check_interval)
                continue

            gf = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame

            if now - state.last_access_time >= SHOP_ACCESS_COOLDOWN:
                roi_shop = (0, int(fh * 0.70), int(fw * 0.15), int(fw * 0.85))
                for name, tpl in templates.get("shop_access", []):
                    pos, score = match_template(gf, tpl, threshold=min(state.confidence, 0.68), roi=roi_shop, fw=fw)
                    if pos:
                        state.access_found += 1
                        state.last_access_time = now
                        add_log(f"PIRATE SHOP ACCESS DETECTED! (Total Drops: {state.access_found})", "success")
                        broadcast_state()
                        # ── fire Discord notification on its own thread so it never blocks the loop ──
                        threading.Thread(
                            target=send_discord_notification,
                            args=(state.access_found,),
                            daemon=True
                        ).start()
                        break

            roi_back = (int(fh * 0.60), int(fh * 0.95), int(fw * 0.10), int(fw * 0.50))
            for name, tpl in templates.get("back", []):
                pos, score = match_template(gf, tpl, threshold=0.75, roi=roi_back, fw=fw)
                if pos:
                    add_log("Report dialog detected. Dismissing...", "warn")
                    press_key("esc")
                    safe_click(ox + pos[0], oy + pos[1])
                    time.sleep(1.2)
                    break

            clicked_play = False
            roi_play_again = (int(fh * 0.20), int(fh * 0.85), int(fw * 0.45), fw)
            for name, tpl in templates.get("play_again", []):
                pos, score = match_template(gf, tpl, threshold=state.confidence, roi=roi_play_again, fw=fw)
                if pos:
                    if not is_safe_click_area(pos[0], pos[1], fw, fh):
                        continue
                    state.status = "CLICKING PLAY AGAIN"
                    broadcast_state()
                    add_log(f"Target '{name}' found (Score: {score:.2f}). Starting next match...", "success")
                    safe_click(ox + pos[0], oy + pos[1])
                    clicked_play = True
                    state.matches += 1
                    state.match_start_time = time.time()
                    add_log(f"Match #{state.matches} queued!", "success")
                    state.status = "MATCHMAKING"
                    broadcast_state()
                    for _ in range(25):
                        if state.stop_event.is_set():
                            break
                        time.sleep(1.0)
                    state.status = "IN MATCH"
                    broadcast_state()
                    break

            if clicked_play:
                state.stop_event.wait(state.check_interval)
                broadcast_state()
                continue

            clicked_lobby = False
            roi_lobby = (int(fh * 0.55), fh, 0, int(fw * 0.50))
            for name, tpl in templates.get("lobby_play", []):
                pos, score = match_template(gf, tpl, threshold=state.confidence, roi=roi_lobby, fw=fw)
                if pos:
                    if not is_safe_click_area(pos[0], pos[1], fw, fh):
                        continue
                    add_log(f"Lobby Play button ({name}) detected. Starting match...", "success")
                    safe_click(ox + pos[0], oy + pos[1])
                    clicked_lobby = True
                    state.matches += 1
                    state.match_start_time = time.time()
                    add_log(f"Match #{state.matches} queued from lobby!", "success")
                    state.status = "MATCHMAKING"
                    broadcast_state()
                    for _ in range(20):
                        if state.stop_event.is_set():
                            break
                        time.sleep(1.0)
                    state.status = "IN MATCH"
                    broadcast_state()
                    break

            if clicked_lobby:
                state.stop_event.wait(state.check_interval)
                broadcast_state()
                continue

            found_action = False
            roi_continue = (int(fh * 0.55), int(fh * 0.95), int(fw * 0.45), fw)
            for name, tpl in templates.get("continue", []):
                pos, score = match_template(gf, tpl, threshold=state.confidence, roi=roi_continue, fw=fw)
                if pos and is_safe_click_area(pos[0], pos[1], fw, fh):
                    add_log(f"Continue button ({name}) detected. Clicking...", "info")
                    safe_click(ox + pos[0], oy + pos[1])
                    found_action = True
                    time.sleep(1.0)
                    break

            if found_action:
                state.stop_event.wait(state.check_interval)
                broadcast_state()
                continue

            if now - last_skip_time > 3.0:
                roi_skip = (int(fh * 0.55), int(fh * 0.95), int(fw * 0.45), fw)
                for name, tpl in templates.get("skip", []):
                    pos, score = match_template(gf, tpl, threshold=state.confidence, roi=roi_skip, fw=fw)
                    if pos and is_safe_click_area(pos[0], pos[1], fw, fh):
                        add_log(f"Skip prompt ({name}) detected. Clicking...", "info")
                        safe_click(ox + pos[0], oy + pos[1])
                        last_skip_time = now
                        found_action = True
                        time.sleep(1.0)
                        break

            if found_action:
                state.stop_event.wait(state.check_interval)
                broadcast_state()
                continue

            for name, tpl in templates.get("nvidia", []):
                pos, score = match_template(gf, tpl, threshold=state.confidence, fw=fw)
                if pos:
                    state.status = "ELIMINATED"
                    add_log(f"Team elimination confirmed via screen cue ({name})", "warn")
                    broadcast_state()
                    break

            if state.status == "ELIMINATED":
                roi_ret = (int(fh * 0.20), int(fh * 0.85), int(fw * 0.45), fw)
                for name, tpl in templates.get("return_lobby", []):
                    pos, score = match_template(gf, tpl, threshold=state.confidence, roi=roi_ret, fw=fw)
                    if pos and is_safe_click_area(pos[0], pos[1], fw, fh):
                        add_log(f"Returning to lobby ({name})...", "info")
                        safe_click(ox + pos[0], oy + pos[1])
                        time.sleep(3.0)
                        break

        except Exception as e:
            add_log(f"Engine iteration notice: {str(e)}", "warn")

        broadcast_state()
        state.stop_event.wait(state.check_interval)

    state.status = "IDLE"
    broadcast_state()
    add_log("Macro stopped.", "info")
