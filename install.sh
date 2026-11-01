#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# =============================================================================
#  Install or update paperless-mrc in a Paperless-ngx container/VM
#  (layout of the Proxmox VE Helper-Scripts: /opt/paperless, uv, systemd services)
#
#  As root inside the Paperless container:
#    bash -c "$(curl -fsSL https://raw.githubusercontent.com/Philoneous/paperless-mrc/main/install.sh)"
#  Interactive: asks for the most important settings (details on request). On an existing installation it offers
#  to keep the settings and only asks for options added since the last setup. Running it again updates paperless-mrc.
#
#  Without questions (scripts): MRC_YES=1 or `bash install.sh --yes` – keeps existing settings.
#  KEEP_ORIGINAL=1 / KEEP_ORIGINAL=0   switch "keep the original until it has been checked" on / off
#  MRC_LANGUAGE=de                     messages in German (also read from paperless.conf)
# =============================================================================
set -Eeuo pipefail

PAPERLESS_DIR="${PAPERLESS_DIR:-/opt/paperless}"
INSTALL_DIR="${INSTALL_DIR:-/opt/paperless-mrc}"
REPO_URL="${REPO_URL:-https://github.com/Philoneous/paperless-mrc.git}"
CONF="$PAPERLESS_DIR/paperless.conf"
SCRIPT="$INSTALL_DIR/venv/bin/paperless-mrc"
POST="$INSTALL_DIR/venv/bin/paperless-mrc-post"

YES="${MRC_YES:-}"
[[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]] && YES=1
interactive() { [[ -z "$YES" ]] && { [[ -t 0 ]] || { [[ -r /dev/tty ]] && : < /dev/tty; } 2>/dev/null; }; }
ask() {  # PROMPT → answer (from the terminal, also with "curl … | bash")
  local answer
  if [[ -t 0 ]]; then read -r -p "$1 " answer; else read -r -p "$1 " answer < /dev/tty; fi
  printf '%s' "$answer"
}

conf_value() {  # KEY: last active value in paperless.conf (quotes removed), empty if missing
  [[ -f "$CONF" ]] || return 0
  grep -E "^\s*$1=" "$CONF" | tail -n1 | cut -d= -f2- | sed -E 's/^\s*["'\'']?//; s/["'\'']?\s*$//' || true
}

# ---- Language ---------------------------------------------------------------------------
language="${MRC_LANGUAGE:-$(conf_value MRC_LANGUAGE)}"
if [[ -z "$language" ]] && interactive; then
  case "$(ask "Language / Sprache: [1] English  [2] Deutsch  (1):")" in
    2|de|DE|d|D) language=de ;;
    *) language=en ;;
  esac
fi
language="${language:-en}"
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
current="$(conf_value PAPERLESS_PRE_CONSUME_SCRIPT)"
if [[ -n "$current" && "$current" != "$SCRIPT" ]]; then
  die "$(say "A different pre-consume script is already set in $CONF: $current" \
             "In $CONF ist bereits ein anderes Pre-Consume-Skript eingetragen: $current")"
fi

# User that runs the pre-/post-consume scripts: Paperless runs them in the Celery worker (paperless-task-queue)
run_user="$(systemctl show -p User --value paperless-task-queue 2>/dev/null || true)"
run_user="${run_user:-root}"

# ---- System packages, code and Python environment ----------------------------------------
msg "$(say "Installing system packages" "Systempakete installieren")"
apt-get update -qq
apt-get install -y -qq --no-install-recommends git libopenjp2-tools poppler-utils tesseract-ocr >/dev/null

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

# ---- Settings (assistant; writes paperless.conf, keeps a backup) -----------------------------
echo
setup_args=(--conf "$CONF" --state "$INSTALL_DIR/setup.json" --lang "$([[ $DE == 1 ]] && echo de || echo en)")
interactive || setup_args+=(--yes)
"$INSTALL_DIR/venv/bin/paperless-mrc-setup" "${setup_args[@]}" \
  || die "$(say "Setup aborted – paperless.conf unchanged." "Einrichtung abgebrochen – paperless.conf unverändert.")"
echo

# ---- OCR language packs (languages chosen above) --------------------------------------------
langs=()
for l in $(conf_value PAPERLESS_OCR_LANGUAGE | tr '+' ' '); do langs+=("tesseract-ocr-${l//_/-}"); done
if [[ ${#langs[@]} -gt 0 ]]; then
  msg "$(say "Installing OCR language packs: ${langs[*]}" "OCR-Sprachpakete installieren: ${langs[*]}")"
  apt-get install -y -qq --no-install-recommends "${langs[@]}" >/dev/null \
    || warn "$(say "Some language packs could not be installed – check the language codes" \
                   "Nicht alle Sprachpakete installierbar – bitte die Sprachkürzel prüfen")"
fi
if command -v jbig2 >/dev/null; then
  ok "$(say "jbig2enc found – the text layer is compressed with JBIG2" \
            "jbig2enc gefunden – die Textebene wird mit JBIG2 komprimiert")"
else
  warn "$(say "jbig2enc (jbig2) not installed – the text layer is compressed with CCITT (somewhat larger)" \
              "jbig2enc (jbig2) fehlt – die Textebene wird mit CCITT komprimiert (etwas größer)")"
fi

# ---- Pre-consume script -------------------------------------------------------------------
set_conf() {  # KEY VALUE: replace the active line or append one
  if grep -qE "^\s*$1=" "$CONF"; then sed -i -E "s|^\s*$1=.*|$1=$2|" "$CONF"; else printf '%s=%s\n' "$1" "$2" >> "$CONF"; fi
}
if [[ -z "$current" ]]; then
  cp -a "$CONF" "$CONF.bak-$(date +%Y%m%d%H%M%S)"
  set_conf PAPERLESS_PRE_CONSUME_SCRIPT "$SCRIPT"
  ok "$(say "Pre-consume script set in $CONF" "Pre-Consume-Skript in $CONF eingetragen")"
fi

# ---- Optional: keep the original until it has been checked ----------------------------------
if [[ "$(conf_value MRC_KEEP_ORIGINAL)" =~ ^(true|1|t|y|yes)$ ]]; then
  post_current="$(conf_value PAPERLESS_POST_CONSUME_SCRIPT)"
  [[ -z "$post_current" || "$post_current" == "$POST" ]] \
    || die "$(say "A different post-consume script is already set in $CONF: $post_current" \
                  "In $CONF ist bereits ein anderes Post-Consume-Skript eingetragen: $post_current")"
  install -d -m 700 -o "$run_user" "$INSTALL_DIR/originals"
  [[ "$post_current" == "$POST" ]] || set_conf PAPERLESS_POST_CONSUME_SCRIPT "$POST"
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
  ok "$(say "The original is kept until it has been checked (hourly cleanup timer active)" \
            "Das Original wird bis zur Prüfung aufbewahrt (stündlicher Aufräum-Timer aktiv)")"
  if [[ "$run_user" != root ]] && ! runuser -u "$run_user" -- test -r "$CONF"; then
    warn "$(say "$run_user cannot read $CONF – the cleanup timer will not find the API token" \
                "$run_user kann $CONF nicht lesen – der Aufräum-Timer findet das API-Token nicht")"
  fi
  if [[ -z "$(conf_value MRC_API_TOKEN)" ]]; then
    warn "$(say "Still needed: create an API token in Paperless under “My Profile” and add it to $CONF" \
                "Noch nötig: In Paperless unter „Mein Profil“ ein API-Token erzeugen und in $CONF eintragen")"
    printf '     MRC_API_TOKEN=<token>\n'
  fi
fi

# ---- Restart services ------------------------------------------------------------------
msg "$(say "Restarting Paperless services" "Paperless-Dienste neu starten")"
systemctl restart paperless-task-queue paperless-consumer
ok "$(say "Done. New scans are compressed from now on; messages in the Paperless log start with 'paperless-mrc:'" \
          "Fertig. Neue Scans werden ab jetzt komprimiert; Meldungen im Paperless-Log beginnen mit 'paperless-mrc:'")"
