#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# =============================================================================
#  paperless-mrc im Paperless-ngx-LXC installieren oder aktualisieren
#  (Layout der community-scripts: /opt/paperless, uv, systemd-Dienste)
#
#  Aufruf als root im Paperless-Container:
#    bash install.sh
#  Erneuter Aufruf = Update (git pull + Neuinstallation).
#  KEEP_ORIGINAL=1 bash install.sh: zusätzlich Original bis zur Prüfung aufbewahren (KEEP_ORIGINAL=0: aus).
# =============================================================================
set -Eeuo pipefail

PAPERLESS_DIR="${PAPERLESS_DIR:-/opt/paperless}"
INSTALL_DIR="${INSTALL_DIR:-/opt/paperless-mrc}"
REPO_URL="${REPO_URL:-https://github.com/Philoneous/paperless-mrc.git}"
OCR_LANGUAGE="${OCR_LANGUAGE:-deu+eng}"   # nur eingetragen, wenn in paperless.conf noch nichts steht
CONF="$PAPERLESS_DIR/paperless.conf"
SCRIPT="$INSTALL_DIR/venv/bin/paperless-mrc"

msg() { printf '[..] %s\n' "$*"; }
ok()  { printf '[OK] %s\n' "$*"; }
die() { printf '[FEHLER] %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Bitte als root ausführen."
[[ -f "$CONF" ]] || die "$CONF nicht gefunden (PAPERLESS_DIR setzen)."
command -v uv >/dev/null || die "uv nicht gefunden – ist das die uv-basierte Paperless-Installation?"

# ---- Systempakete -------------------------------------------------------------
msg "Systempakete installieren"
langs=()
for l in ${OCR_LANGUAGE//+/ }; do langs+=("tesseract-ocr-$l"); done
apt-get update -qq
apt-get install -y -qq --no-install-recommends git libopenjp2-tools poppler-utils tesseract-ocr "${langs[@]}" >/dev/null
if command -v jbig2 >/dev/null; then ok "jbig2enc gefunden – Maske wird mit JBIG2 komprimiert"
else printf '[!!] jbig2enc (jbig2) fehlt – Maske wird mit CCITT komprimiert (etwas größer)\n'; fi

# ---- Code und Python-Umgebung ------------------------------------------------------
if [[ -d "$INSTALL_DIR/src/.git" ]]; then
  msg "Aktualisiere $INSTALL_DIR/src"
  git -C "$INSTALL_DIR/src" pull -q --ff-only
else
  msg "Lade $REPO_URL"
  mkdir -p "$INSTALL_DIR"
  git clone -q "$REPO_URL" "$INSTALL_DIR/src"
fi
[[ -x "$INSTALL_DIR/venv/bin/python" ]] || uv venv -q --python 3.13 "$INSTALL_DIR/venv"
uv pip install -q --python "$INSTALL_DIR/venv/bin/python" --reinstall-package paperless-mrc "$INSTALL_DIR/src"
"$INSTALL_DIR/venv/bin/recode_pdf" --version >/dev/null 2>&1 || die "recode_pdf startet nicht."
ok "paperless-mrc $(git -C "$INSTALL_DIR/src" rev-parse --short HEAD) installiert"

# ---- paperless.conf ---------------------------------------------------------------------
current=$(grep -E '^\s*PAPERLESS_PRE_CONSUME_SCRIPT=' "$CONF" | tail -n1 | cut -d= -f2- || true)
if [[ -n "$current" && "$current" != "$SCRIPT" ]]; then
  die "In $CONF ist bereits ein anderes Pre-Consume-Skript eingetragen: $current"
fi
if [[ -z "$current" ]] || ! grep -qE '^\s*PAPERLESS_OCR_LANGUAGE=' "$CONF"; then
  cp -a "$CONF" "$CONF.bak-$(date +%Y%m%d%H%M%S)"
  [[ -z "$current" ]] && printf '\n# paperless-mrc\nPAPERLESS_PRE_CONSUME_SCRIPT=%s\n' "$SCRIPT" >> "$CONF"
  grep -qE '^\s*PAPERLESS_OCR_LANGUAGE=' "$CONF" || printf 'PAPERLESS_OCR_LANGUAGE=%s\n' "$OCR_LANGUAGE" >> "$CONF"
  ok "$CONF ergänzt (Sicherung daneben abgelegt)"
fi

# ---- Optional: Original bis zur Prüfung aufbewahren -------------------------------------------
# KEEP_ORIGINAL=1: einschalten (Post-Consume-Skript, Ordner, stündlicher Aufräum-Timer)
# KEEP_ORIGINAL=0: ausschalten (neue Scans ohne Original; der Timer erledigt vorhandene Originale weiter)
set_conf() {  # KEY VALUE: Zeile ersetzen oder anhängen
  if grep -qE "^\s*$1=" "$CONF"; then sed -i -E "s|^\s*$1=.*|$1=$2|" "$CONF"; else printf '%s=%s\n' "$1" "$2" >> "$CONF"; fi
}
POST="$INSTALL_DIR/venv/bin/paperless-mrc-post"
case "${KEEP_ORIGINAL:-}" in
  1|true|yes)
    msg "Original bis zur Prüfung aufbewahren einrichten"
    post_current=$(grep -E '^\s*PAPERLESS_POST_CONSUME_SCRIPT=' "$CONF" | tail -n1 | cut -d= -f2- || true)
    [[ -z "$post_current" || "$post_current" == "$POST" ]] \
      || die "In $CONF ist bereits ein anderes Post-Consume-Skript eingetragen: $post_current"
    run_user="$(systemctl show -p User --value paperless-consumer 2>/dev/null || true)"
    run_user="${run_user:-root}"
    install -d -m 700 -o "$run_user" "$INSTALL_DIR/originals"
    cp -a "$CONF" "$CONF.bak-$(date +%Y%m%d%H%M%S)"
    set_conf PAPERLESS_POST_CONSUME_SCRIPT "$POST"
    set_conf MRC_KEEP_ORIGINAL true
    cat > /etc/systemd/system/paperless-mrc-cleanup.service <<UNIT
[Unit]
Description=paperless-mrc: aufbewahrte Originale anhängen und nach Frist löschen
After=network-online.target paperless-webserver.service

[Service]
Type=oneshot
User=$run_user
Environment=MRC_PAPERLESS_CONF=$CONF
ExecStart=$INSTALL_DIR/venv/bin/paperless-mrc-cleanup
UNIT
    cat > /etc/systemd/system/paperless-mrc-cleanup.timer <<'UNIT'
[Unit]
Description=paperless-mrc: aufbewahrte Originale stündlich prüfen

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
UNIT
    systemctl daemon-reload
    systemctl enable --now paperless-mrc-cleanup.timer >/dev/null
    ok "Original wird bis zur Prüfung aufbewahrt (Frist: MRC_KEEP_ORIGINAL_DAYS, Standard 30 Tage)"
    if ! grep -qE '^\s*MRC_API_TOKEN=.+' "$CONF"; then
      printf '[!!] Noch nötig: In Paperless unter „Mein Profil“ ein API-Token erzeugen und in %s eintragen:\n' "$CONF"
      printf '     MRC_API_TOKEN=<token>   (danach: systemctl restart paperless-task-queue paperless-consumer)\n'
    fi
    ;;
  0|false|no)
    set_conf MRC_KEEP_ORIGINAL false
    ok "Original-Aufbewahrung ausgeschaltet; vorhandene Originale erledigt der Timer weiter"
    ;;
esac

# ---- Dienste neu starten ------------------------------------------------------------------
msg "Paperless-Dienste neu starten"
systemctl restart paperless-task-queue paperless-consumer
ok "Fertig. Neue Scans werden ab jetzt komprimiert; Ausgaben im Log mit 'paperless-mrc:'"
