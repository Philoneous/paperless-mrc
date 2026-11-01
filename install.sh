#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# =============================================================================
#  Install or update paperless-mrc in a Paperless-ngx container/VM
#  (layout of the Proxmox VE Helper-Scripts: /opt/paperless, uv, systemd services)
#
#  As root inside the Paperless container:
#    bash install.sh
#  Running it again updates paperless-mrc.
#  KEEP_ORIGINAL=1 bash install.sh   also keep the original until it has been checked (KEEP_ORIGINAL=0: off)
#  Messages in German: MRC_LANGUAGE=de (as environment variable or in paperless.conf)
# =============================================================================
set -Eeuo pipefail

PAPERLESS_DIR="${PAPERLESS_DIR:-/opt/paperless}"
INSTALL_DIR="${INSTALL_DIR:-/opt/paperless-mrc}"
REPO_URL="${REPO_URL:-https://github.com/Philoneous/paperless-mrc.git}"
DEFAULT_OCR_LANGUAGE="deu+eng"   # only written to paperless.conf if nothing is set there yet
CONF="$PAPERLESS_DIR/paperless.conf"
SCRIPT="$INSTALL_DIR/venv/bin/paperless-mrc"
POST="$INSTALL_DIR/venv/bin/paperless-mrc-post"

conf_value() {  # KEY: last active value in paperless.conf (quotes removed), empty if missing
  [[ -f "$CONF" ]] || return 0
  grep -E "^\s*$1=" "$CONF" | tail -n1 | cut -d= -f2- | sed -E 's/^\s*["'\'']?//; s/["'\'']?\s*$//' || true
}
language="${MRC_LANGUAGE:-$(conf_value MRC_LANGUAGE)}"
[[ "${language,,}" == de* ]] && DE=1 || DE=0
say() { if [[ $DE == 1 ]]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }  # say "English" "Deutsch"

msg()  { printf '[..] %s\n' "$*"; }
ok()   { printf '[OK] %s\n' "$*"; }
warn() { printf '[!!] %s\n' "$*"; }
die()  { printf '[%s] %s\n' "$(say ERROR FEHLER)" "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "$(say "Please run as root." "Bitte als root ausführen.")"
[[ -f "$CONF" ]] || die "$(say "$CONF not found (set PAPERLESS_DIR)." "$CONF nicht gefunden (PAPERLESS_DIR setzen).")"
command -v uv >/dev/null || die "$(say "uv not found – is this the uv-based Paperless installation?" \
                                     "uv nicht gefunden – ist das die uv-basierte Paperless-Installation?")"

# User that runs the pre-/post-consume scripts: Paperless runs them in the Celery worker (paperless-task-queue)
run_user="$(systemctl show -p User --value paperless-task-queue 2>/dev/null || true)"
run_user="${run_user:-root}"

# ---- System packages -------------------------------------------------------------
msg "$(say "Installing system packages" "Systempakete installieren")"
ocr_language="$(conf_value PAPERLESS_OCR_LANGUAGE)"
ocr_language="${ocr_language:-$DEFAULT_OCR_LANGUAGE}"
langs=()
for l in ${ocr_language//+/ }; do langs+=("tesseract-ocr-${l//_/-}"); done  # chi_sim → tesseract-ocr-chi-sim
apt-get update -qq
apt-get install -y -qq --no-install-recommends git libopenjp2-tools poppler-utils tesseract-ocr "${langs[@]}" >/dev/null
if command -v jbig2 >/dev/null; then
  ok "$(say "jbig2enc found – the text layer is compressed with JBIG2" \
            "jbig2enc gefunden – die Textebene wird mit JBIG2 komprimiert")"
else
  warn "$(say "jbig2enc (jbig2) not installed – the text layer is compressed with CCITT (somewhat larger)" \
              "jbig2enc (jbig2) fehlt – die Textebene wird mit CCITT komprimiert (etwas größer)")"
fi

# ---- Code and Python environment ------------------------------------------------------
if [[ -d "$INSTALL_DIR/src/.git" ]]; then
  msg "$(say "Updating $INSTALL_DIR/src" "Aktualisiere $INSTALL_DIR/src")"
  git -C "$INSTALL_DIR/src" pull -q --ff-only
else
  msg "$(say "Downloading $REPO_URL" "Lade $REPO_URL")"
  mkdir -p "$INSTALL_DIR"
  git clone -q "$REPO_URL" "$INSTALL_DIR/src"
fi
[[ -x "$INSTALL_DIR/venv/bin/python" ]] || uv venv -q --python 3.13 "$INSTALL_DIR/venv"
uv pip install -q --python "$INSTALL_DIR/venv/bin/python" --reinstall-package paperless-mrc "$INSTALL_DIR/src"
"$INSTALL_DIR/venv/bin/recode_pdf" --version >/dev/null 2>&1 \
  || die "$(say "recode_pdf does not start." "recode_pdf startet nicht.")"
ok "$(say "paperless-mrc $(git -C "$INSTALL_DIR/src" rev-parse --short HEAD) installed" \
          "paperless-mrc $(git -C "$INSTALL_DIR/src" rev-parse --short HEAD) installiert")"

# ---- paperless.conf ---------------------------------------------------------------------
set_conf() {  # KEY VALUE: replace the active line or append one
  if grep -qE "^\s*$1=" "$CONF"; then sed -i -E "s|^\s*$1=.*|$1=$2|" "$CONF"; else printf '%s=%s\n' "$1" "$2" >> "$CONF"; fi
}
backup_conf() { cp -a "$CONF" "$CONF.bak-$(date +%Y%m%d%H%M%S)"; }

current="$(conf_value PAPERLESS_PRE_CONSUME_SCRIPT)"
if [[ -n "$current" && "$current" != "$SCRIPT" ]]; then
  die "$(say "A different pre-consume script is already set in $CONF: $current" \
             "In $CONF ist bereits ein anderes Pre-Consume-Skript eingetragen: $current")"
fi
if [[ -z "$current" || -z "$(conf_value PAPERLESS_OCR_LANGUAGE)" ]]; then
  backup_conf
  [[ -n "$current" ]] || printf '\n# paperless-mrc\nPAPERLESS_PRE_CONSUME_SCRIPT=%s\n' "$SCRIPT" >> "$CONF"
  [[ -n "$(conf_value PAPERLESS_OCR_LANGUAGE)" ]] || printf 'PAPERLESS_OCR_LANGUAGE=%s\n' "$DEFAULT_OCR_LANGUAGE" >> "$CONF"
  ok "$(say "$CONF updated (backup placed next to it)" "$CONF ergänzt (Sicherung daneben abgelegt)")"
fi

# ---- Optional: keep the original until it has been checked ----------------------------------
# KEEP_ORIGINAL=1: switch on (post-consume script, folder, hourly cleanup timer)
# KEEP_ORIGINAL=0: switch off (new documents without original; the timer still handles existing originals)
case "${KEEP_ORIGINAL:-}" in
  1|true|yes)
    msg "$(say "Setting up: keep the original until it has been checked" \
               "Einrichten: Original bis zur Prüfung aufbewahren")"
    post_current="$(conf_value PAPERLESS_POST_CONSUME_SCRIPT)"
    [[ -z "$post_current" || "$post_current" == "$POST" ]] \
      || die "$(say "A different post-consume script is already set in $CONF: $post_current" \
                    "In $CONF ist bereits ein anderes Post-Consume-Skript eingetragen: $post_current")"
    install -d -m 700 -o "$run_user" "$INSTALL_DIR/originals"
    backup_conf
    set_conf PAPERLESS_POST_CONSUME_SCRIPT "$POST"
    set_conf MRC_KEEP_ORIGINAL true
    cat > /etc/systemd/system/paperless-mrc-cleanup.service <<UNIT
[Unit]
Description=paperless-mrc: attach kept originals and delete them when due
After=network-online.target paperless-webserver.service

[Service]
Type=oneshot
User=$run_user
Environment=MRC_PAPERLESS_CONF=$CONF
ExecStart=$INSTALL_DIR/venv/bin/paperless-mrc-cleanup
UNIT
    cat > /etc/systemd/system/paperless-mrc-cleanup.timer <<'UNIT'
[Unit]
Description=paperless-mrc: check kept originals every hour

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
UNIT
    systemctl daemon-reload
    systemctl enable --now paperless-mrc-cleanup.timer >/dev/null
    ok "$(say "The original is kept until it has been checked (period: MRC_KEEP_ORIGINAL_DAYS, default 30 days)" \
              "Das Original wird bis zur Prüfung aufbewahrt (Frist: MRC_KEEP_ORIGINAL_DAYS, Standard 30 Tage)")"
    if [[ "$run_user" != root ]] && ! runuser -u "$run_user" -- test -r "$CONF"; then
      warn "$(say "$run_user cannot read $CONF – the cleanup timer will not find the API token" \
                  "$run_user kann $CONF nicht lesen – der Aufräum-Timer findet das API-Token nicht")"
    fi
    if [[ -z "$(conf_value MRC_API_TOKEN)" ]]; then
      warn "$(say "Still needed: create an API token in Paperless under “My Profile” and add it to $CONF:" \
                  "Noch nötig: In Paperless unter „Mein Profil“ ein API-Token erzeugen und in $CONF eintragen:")"
      printf '     MRC_API_TOKEN=<token>   (%s: systemctl restart paperless-task-queue paperless-consumer)\n' \
        "$(say then danach)"
    fi
    ;;
  0|false|no)
    set_conf MRC_KEEP_ORIGINAL false
    ok "$(say "Keeping the original switched off; the timer still handles originals that are already kept" \
              "Original-Aufbewahrung ausgeschaltet; vorhandene Originale erledigt der Timer weiter")"
    ;;
esac

# ---- Restart services ------------------------------------------------------------------
msg "$(say "Restarting Paperless services" "Paperless-Dienste neu starten")"
systemctl restart paperless-task-queue paperless-consumer
ok "$(say "Done. New scans are compressed from now on; messages in the Paperless log start with 'paperless-mrc:'" \
          "Fertig. Neue Scans werden ab jetzt komprimiert; Meldungen im Paperless-Log beginnen mit 'paperless-mrc:'")"
