# P5A-K6PLUS

A modified BIOS for the **ASUS P5A** (ALi Aladdin V, Award 4.51PG) that sets up AMD K6-2+/K6-III+
CPUs during POST, the way [K6INIT](https://github.com/oerg866/k6init) does under DOS. The setup
works with any operating system and needs no driver in `CONFIG.SYS`.

Base image: **ASUS P5A ACPI BIOS Revision 1011 Beta 005** (256 KB).

```
K6PLUS: WC=E0000000/128M WC=DC000000/64M WA=BIOS WO L2 DPE CD-DMA
```
<sub>POST line on the test system: GeForce2 Ultra (AGP), 2× Voodoo2 SLI, 512 MB, K6-III+/600.</sub>

## Features

K6PLUS is a 4 KB option ROM, an assembly re-implementation of the `K6INIT /auto` logic plus a
few extras:

| Feature | How | Default |
|---|---|---|
| Write combining for the PCI/AGP frame buffer | UWCCR (C0000085h), slot 0 | on |
| Write combining for 3dfx Voodoo Graphics / Rush / Voodoo2 (incl. SLI) | UWCCR, slot 1 | on |
| Write allocate up to the end of RAM (with 15–16 MB hole) | WHCR (C0000082h) | only if the BIOS has not set it |
| Write ordering mode 1 (all except UC/WC) | EFER bits 2–3 | on |
| Data prefetch | EFER bit 1 | on |
| On-die L2 cache on (K6-III/+) | EFER bit 4 | on |
| CD/DVD-ROM DMA on the ALi M5229 IDE controller (like [ALi5DMA](https://github.com/TeleTubby666/ALi5DMA)) | reg. 53h bit 0 | on |
| ALi Aladdin V frame buffer tweak (M1541/M5243 reg. 84h–86h) | PCI config | **off** (experimental build only) |
| Write combining for A0000–BFFFF | UWCCR | off (breaks UMBs in that range) |
| Multiplier (K6-2+/III+ only) | EPMR / BVC | off (unchanged) |

- **Voodoo cards:** write combining covers the smallest aligned block that holds all 3dfx cards.
  K6PLUS sets it only if a slot is free, the block lies above RAM and no other PCI device decodes
  memory inside it. Otherwise the POST line shows `WC3D=conflict`.
- **Other CPUs:** Intel, Cyrix and K5 are detected and left alone. CD-ROM DMA is still enabled
  when an M5229 is present. On an old K6/K6-2 without the CXT core, only write allocate is set.

### Changes to the system BIOS

- The Symbios SCSI ROM loader (module 0800) now loads K6PLUS, with or without a Symbios card.
- The setup item `SYMBIOS SCSI BIOS` is now **`K6PLUS CPU Tweaks : Enabled / Disabled`**.
- A K6-III+ is shown as `AMD-K6(tm)-III+` instead of `AMD-K6(tm)-III`.
- The CPU clock is rounded correctly and *Save & Exit* defaults to `Y`. Both use the table and
  patch from the ROM.by BIOS patch 4.23. There is no extra POST message.
- The original BIOS date and the full 8×8 font are unchanged.

**Hold SHIFT during POST to skip K6PLUS completely.** Setting `K6PLUS CPU Tweaks` to `Disabled`
also turns it off.

## Downloads

See [Releases](../../releases):

- **Release:** default configuration, tested on real hardware.
- **Experimental:** the release configuration plus the Aladdin V frame buffer tweak, limited to
  16 MB, the maximum the chipset officially supports. Write combining keeps its full size. Not
  tested on real hardware yet.

Each zip has the BIOS image, the configured `K6PLUS.ROM` and MD5 sums.

## Flashing

1. Keep a copy of your original BIOS, and ideally a second flash chip or a programmer.
2. Boot plain DOS from a floppy, without memory managers.
3. Flash with ASUS `AFLASH.EXE`, including the boot block. awdflash 7.x/8.x does not detect the
   P5A's flash chip.
4. **Before rebooting**, read the BIOS back with AFLASH and compare it with the image:
   `FC /B READBACK.BIN P5A_K6PLUS.BIN`.

Check with `K6INIT /status` under DOS: the values must match the K6PLUS line from POST.

### With K6INIT, RawPower etc.

- K6INIT is only needed for what K6PLUS leaves alone, for example the multiplier
  (`K6INIT.EXE /multi:2.0`) or the chipset tweak (`/chipset`). Don't run it with `/auto`, or it
  will set everything a second time.
- Remove `ALi5DMA.EXE` from `CONFIG.SYS`. K6PLUS already enables CD-ROM DMA. UIDE works without
  `/UX`.
- Under Windows 98, tools such as RawPower, Write Allocate Monitor or the ALi AGP Control Center
  may rewrite the same registers. Check their settings if values differ.

## Building

Needs Python 3, `nasm`, DOSBox and two DOS tools that are not included in this repository. Put
them in `tools/dos/`:

| File | Version | MD5 |
|---|---|---|
| `LHA.EXE` | LHA 2.55 | `39215f032c4b78c86c55b04a9fdf9756` |
| `CBROM.EXE` | Award CBROM 2.07 | `9b77a69c11faea582bd401b066debafb` |

```sh
pip install unicorn                 # only for the tests
python3 k6plus/test/run_tests.py    # emulated POST on several board configurations

./build.sh 1011005.BIN              # release configuration
./build.sh 1011005.BIN --chipset    # experimental configuration
```

`build/P5A.BIN` is the result. With the original image (MD5 `0f424cd23733bec1079b30fd7852c52c`),
the build is byte-identical to the release images. Use the DOSBox binary from the `DOSBOX`
environment variable if it is not in `PATH`.

`k6plus/k6cfg.py` sets the configuration stored inside the ROM and fixes its checksum. Run
`python3 k6plus/k6cfg.py -h` for all options.

```sh
python3 k6plus/k6cfg.py K6PLUS.ROM                  # show the configuration
python3 k6plus/k6cfg.py K6PLUS.ROM --no-wc-3dfx     # no Voodoo write combining
python3 k6plus/k6cfg.py K6PLUS.ROM --multi 5.5      # set the multiplier during POST
```

To swap only the option ROM in an existing image, use CBROM 2.07. CBROM32 fails on this image.

```
CBROM P5A.BIN /OTHER 0800:0000 RELEASE
CBROM P5A.BIN /OTHER 0800:0000 K6PLUS.ROM
```

### Layout

| Path | Content |
|---|---|
| `k6plus/k6plus.asm` | the option ROM |
| `k6plus/k6cfg.py` | configuration tool |
| `k6plus/test/` | Unicorn-based POST emulation with simulated PCI boards |
| `bios/build_stn.py` | patches the system BIOS module (`stn.bin`) and puts it back into the image |
| `bios/cpuname.asm` | K6-III+ name routine |
| `tools/` | LH5 decoder/encoder and CRC helper |

### Why module 0800?

The ASUS system BIOS loads only modules with fixed IDs. ISA option ROMs added with `CBROM /isa`
are ignored, and so is the bootblock hook of the ROM.by patch. The Symbios PCI ROM loader copies
module 0800 to shadow RAM and calls it without checking for a PCI ROM header. The patched BIOS
skips its PCI vendor check, so the module is always loaded.

## Tested on

ASUS P5A with BIOS 1011.005, AMD K6-III+ 600 MHz (100 × 6), 512 MB, ELSA Gladiac Ultra,
2× miro HiSCORE² 3D (SLI), miroVIDEO DC30, 3Com NIC, TEAC CD-540E/CD-W540E. Runs under DOS 7 and
Windows 98.

Reports from other P5A revisions and BIOS versions are welcome. Please open an issue with your
POST line and `K6INIT /status` output.

## Credits and license

- K6INIT © Eric Voirin (oerg866): <https://github.com/oerg866/k6init>. K6PLUS follows its logic
  and tables.
- The clock rounding table and *Save & Exit* default come from the ROM.by BIOS patch 4.23.
- The ASUS/Award BIOS code in the release images remains the property of its owners. It is
  provided here only as a patched image for owners of this board.

The code in this repository is licensed under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/), like K6INIT. See
`LICENSE`.

**No warranty.** Flashing a BIOS can make the board unbootable. You do this at your own risk.
