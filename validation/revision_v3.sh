#!/bin/bash
# Monitor del programa v3 en el servidor.
#
# Pensado para el cron de OpenClaw: lo que imprime se anuncia por Telegram.
#
#   - Si el programa sigue vivo: imprime una linea de progreso como mucho
#     cada 4 horas (para no spamear).
#   - Si ha terminado y aun no se ha avisado: imprime el informe completo y
#     marca el aviso para no repetirlo.
#   - Si ha terminado y ya se aviso: no imprime nada.

set -u
HOST="alejandro@100.85.66.123"
WORK="/tmp/v3"
ESTADO="$HOME/.openclaw/workspace/tmpfig/.v3_avisado"

if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" true 2>/dev/null; then
    echo "ALERTA: el servidor openblade no responde por Tailscale."
    exit 0
fi

DATOS=$(ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" "WORK=$WORK bash -s" <<'REMOTE'
set -u
LOG="$WORK/programa.log"
RES="$WORK/resultados.json"

N=$(pgrep -cf programa_v3 2>/dev/null || echo 0)
S=$(pgrep -c foamRun 2>/dev/null || echo 0)

FIN=0
grep -q "PROGRAMA v3 COMPLETADO" "$LOG" 2>/dev/null && FIN=1
# si no hay proceso y el log existe pero no esta el sello, murio
MUERTO=0
if [ "$N" = "0" ] && [ "$FIN" = "0" ] && [ -f "$LOG" ]; then MUERTO=1; fi

echo "FIN=$FIN"
echo "VIVO=$N"
echo "SOLVERS=$S"
echo "MUERTO=$MUERTO"
echo "INICIO=$(head -1 "$LOG" 2>/dev/null | cut -c2-17)"
echo "ULTIMA=$(tail -1 "$LOG" 2>/dev/null | cut -c2-17)"
echo "CASOS=$(grep -c '^\[.*\]   ' "$LOG" 2>/dev/null || echo 0)"
echo "COLA<<EOF"
tail -20 "$LOG" 2>/dev/null
echo "EOF"
echo "RESUMEN<<EOF"
python3 - "$RES" <<'PY'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception as e:
    print("(sin resultados)"); raise SystemExit
ok=[r for r in d if r.get("ok")]
fal=[r for r in d if not r.get("ok")]
print(f"casos guardados: {len(d)}  ok: {len(ok)}  fallos: {len(fal)}")
for r in ok:
    if r.get("err_cd") is not None:
        print(f"  {r['tag']:22s} Cl={r.get('cl',0):+7.4f} Cd={r.get('cd',0):9.5f} err={r['err_cd']:+7.1f}%")
    else:
        print(f"  {r['tag']:22s} Cl={r.get('cl',0):+7.4f} Cd={r.get('cd',0):9.5f}")
for r in fal:
    print(f"  FALLO {r['tag']}: {str(r.get('error',''))[:80]}")
PY
echo "EOF"
REMOTE
)

FIN=$(echo "$DATOS" | grep -o "^FIN=[0-9]" | cut -d= -f2)
VIVO=$(echo "$DATOS" | grep -o "^VIVO=[0-9]*" | cut -d= -f2)
MUERTO=$(echo "$DATOS" | grep -o "^MUERTO=[0-9]" | cut -d= -f2)
CASOS=$(echo "$DATOS" | grep -o "^CASOS=[0-9]*" | cut -d= -f2)
COLA=$(echo "$DATOS" | sed -n '/^COLA<<EOF/,/^EOF/p' | sed '1d;$d')
RESUMEN=$(echo "$DATOS" | sed -n '/^RESUMEN<<EOF/,/^EOF/p' | sed '1d;$d')

if [ "${FIN:-0}" = "1" ]; then
    if [ -f "$ESTADO" ]; then
        exit 0     # ya avisado
    fi
    touch "$ESTADO"
    echo "PROGRAMA v3 TERMINADO en el servidor openblade."
    echo
    echo "$RESUMEN"
    echo
    echo "--- ultimas lineas del log ---"
    echo "$COLA"
    exit 0
fi

if [ "${MUERTO:-0}" = "1" ]; then
    echo "ALERTA: el programa v3 se detuvo sin terminar."
    echo "casos hechos: ${CASOS:-?}"
    echo
    echo "--- ultimas lineas ---"
    echo "$COLA"
    echo
    echo "Relanzar con el mismo comando: reanuda los casos ya hechos."
    exit 0
fi

# sigue vivo: aviso de progreso cada 4h como mucho
AHORA=$(date +%s)
ULTIMO=0
[ -f "$ESTADO.prog" ] && ULTIMO=$(cat "$ESTADO.prog" 2>/dev/null || echo 0)
if [ $((AHORA - ULTIMO)) -ge 14400 ]; then
    echo "$AHORA" > "$ESTADO.prog"
    echo "v3 en curso: ${VIVO:-?} proceso(s), ${CASOS:-?} casos cerrados."
    echo
    echo "$RESUMEN" | head -12
fi
exit 0
