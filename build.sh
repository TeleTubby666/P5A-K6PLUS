#!/bin/bash
# Build the patched ASUS P5A BIOS image.
#
#   ./build.sh <original 1011.005 image> [k6cfg options...]
#
# Needs: python3, nasm, DOSBox (or DOSBox Staging) and two DOS tools that are
# not part of this repository, placed in tools/dos/:
#   LHA.EXE    LHA 2.55 (Haruyasu Yoshizaki)  md5 39215f032c4b78c86c55b04a9fdf9756
#   CBROM.EXE  Award CBROM 2.07               md5 9b77a69c11faea582bd401b066debafb
# The result is build/P5A.BIN. Without k6cfg options the release defaults are used.
set -euo pipefail
cd "$(dirname "$0")"
ORIG="$(realpath "${1:?usage: ./build.sh <original 1011.005 image> [k6cfg options]}")"; shift
DOSBOX="${DOSBOX:-dosbox}"
ORIG_MD5=0f424cd23733bec1079b30fd7852c52c

[ "$(md5sum < "$ORIG" | cut -d' ' -f1)" = "$ORIG_MD5" ] || {
    echo "warning: $ORIG is not the tested original image (md5 $ORIG_MD5)" >&2; }
for f in LHA.EXE CBROM.EXE; do
    [ -f "tools/dos/$f" ] || { echo "missing tools/dos/$f" >&2; exit 1; }
done

rm -rf build && mkdir build
cp tools/dos/LHA.EXE tools/dos/CBROM.EXE build/

rundos() {   # rundos <command>  (runs inside build/, output to build/OUT.TXT)
    local cfg; cfg=$(mktemp --suffix=.conf)
    printf 'call %s > OUT.TXT\r\n' "$1" > build/JOB.BAT
    cat > "$cfg" <<EOF
[sdl]
output=surface
[dosbox]
memsize=32
[cpu]
cycles=max
[mixer]
nosound=true
[autoexec]
mount c "$(pwd)/build"
c:
call JOB.BAT
exit
EOF
    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy timeout 300 \
        "$DOSBOX" -conf "$cfg" -noprimaryconf -nolocalconf >/dev/null 2>&1 || true
    rm -f "$cfg"
    cat build/OUT.TXT; echo
}

echo "== K6PLUS option ROM"
nasm -f bin -o build/K6PLUS.ROM k6plus/k6plus.asm
python3 k6plus/k6cfg.py build/K6PLUS.ROM "$@"

echo "== system BIOS (stn.bin), pass 1: patch"
nasm -f bin -o bios/cpuname.bin bios/cpuname.asm
python3 bios/build_stn.py "$ORIG" build/pass1.bin >/dev/null
cp bios/stn_patched.bin build/STN.BIN

echo "== compress stn.bin with LHA.EXE"
rundos "LHA A STN.LZH STN.BIN"

echo "== system BIOS, pass 2: insert"
LZH=build/STN.LZH python3 bios/build_stn.py "$ORIG" build/P5A.BIN

echo "== replace module 0800 (Symbios SCSI ROM) with K6PLUS.ROM"
rundos "CBROM P5A.BIN /OTHER 0800:0000 RELEASE"
rundos "CBROM P5A.BIN /OTHER 0800:0000 K6PLUS.ROM"
rundos "CBROM P5A.BIN /D"

md5sum build/P5A.BIN
