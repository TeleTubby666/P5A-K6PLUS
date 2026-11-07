; =============================================================================
;  K6PLUS.ROM - AMD K6-2/K6-2+/K6-III/K6-III+ init option ROM for Award BIOS
;  Target: ASUS P5A (ALi Aladdin V), Award Modular BIOS v4.51PG
;
;  Re-implementation in assembly of the "/auto" logic of K6INIT
;  (C) 2021-2026 Eric Voirin (oerg866), https://github.com/oerg866/k6init
;  Licensed CC BY-NC-SA 4.0 like the original.
;
;  ASUS P5A: inserted as module 0800 (replaces the Symbios SCSI ROM), loaded
;  by the patched system BIOS:  CBROM <bios.bin> /other 0800:0000 K6PLUS.ROM
;  Hold SHIFT during POST to skip everything this ROM does.
;
;  Build:  nasm -f bin -o k6plus.rom k6plus.asm
;          python3 k6cfg.py k6plus.rom [options]   (sets config + checksum!)
; =============================================================================

        cpu     586
        bits    16
        org     0

ROM_BLOCKS      equ 8                   ; 8 x 512 bytes = 4 KB

; ---- MSRs -------------------------------------------------------------------
MSR_EFER        equ 0C0000080h
MSR_WHCR        equ 0C0000082h
MSR_UWCCR       equ 0C0000085h
MSR_EPMR        equ 0C0000086h

; ---- config flag bits (cfg_flags) -------------------------------------------
F_WO            equ 0001h               ; set write order mode (cfg_wo)
F_DPE           equ 0002h               ; enable data prefetch
F_L2            equ 0004h               ; force on-die L2 on (K6-III / +)
F_WC_PCI        equ 0008h               ; write combine for PCI/AGP frame buffer
F_WC_VGA        equ 0010h               ; write combine for A0000-BFFFF (unsafe w/ UMBs!)
F_CHIPSET       equ 0020h               ; ALi Aladdin V frame buffer write tweak (experimental)
F_NONPF         equ 0040h               ; accept non-prefetchable BARs as frame buffer
F_QUIET         equ 0080h               ; no screen output
F_WC_3DFX       equ 0100h               ; write combine for 3dfx Voodoo 1/Rush/Voodoo2 add-on cards
F_CDDMA         equ 0200h               ; ALi M5229: CD-ROM DMA enable (reg 53h bit 0)

; ---- CPU capability bits ([bp+V_CAPS]) ---------------------------------------
C_NEWWHCR       equ 01h                 ; K6-2 CXT and later WHCR layout
C_EFER          equ 02h                 ; EFER: write order + data prefetch (CXT+)
C_L2            equ 04h                 ; on-die L2 (K6-III, K6-2+/III+)
C_MULT          equ 08h                 ; EPMR multiplier (K6-2+/III+)

; ---- locals on stack (bp-relative) ------------------------------------------
V_CAPS          equ 0                   ; byte
V_NMTRR         equ 1                   ; byte
V_MTRR0         equ 2                   ; dword  (UWCCR lo)
V_MTRR1         equ 6                   ; dword  (UWCCR hi)
V_FBOFF         equ 10                  ; dword  first non-VGA WC region
V_FBKB          equ 14                  ; dword  its size in KB
V_TMP           equ 18                  ; dword
V_LO            equ 22                  ; dword  3dfx: lowest address / block base
V_HI            equ 26                  ; dword  3dfx: end (exclusive) / block end
V_SIZE          equ 30

; In the test build MSR accesses are replaced by INT F0/F1 so the emulator
; can intercept them.
%ifdef EMUTEST
  %macro RDMSR_ 0
        int     0F0h
  %endmacro
  %macro WRMSR_ 0
        int     0F1h
  %endmacro
%else
  %macro RDMSR_ 0
        rdmsr
  %endmacro
  %macro WRMSR_ 0
        wrmsr
  %endmacro
%endif

; =============================================================================
;  ROM header
; =============================================================================
        db      55h, 0AAh, ROM_BLOCKS
        jmp     init                    ; offset 3

        times   20h-($-$$) db 0

; =============================================================================
;  Configuration block - patched by k6cfg.py (offsets are fixed!)
; =============================================================================
cfg_sig         db 'K6CF'               ; 20h
cfg_ver         db 1                    ; 24h
cfg_flags       dw F_WO|F_DPE|F_L2|F_WC_PCI|F_WC_3DFX|F_CDDMA ; 25h
cfg_wo          db 1                    ; 27h  0=all 1=all except UC/WC 2=none
cfg_wa          db 1                    ; 28h  0=leave 1=only if BIOS left it off 2=force
cfg_multi       db 0FFh                 ; 29h  BVC IBF code 0..7, FFh = don't touch
cfg_mtxt        db '   '                ; 2Ah  multiplier as text, e.g. '5.5'
                db 0                    ; 2Dh  reserved

; =============================================================================
;  Entry
; =============================================================================
init:
        pushfd
        pushad
        push    ds
        push    es
        cld
        sub     sp, V_SIZE
        mov     bp, sp

        ; ---- SHIFT held? -> skip ------------------------------------------
        mov     ax, 40h
        mov     ds, ax
        test    byte [17h], 03h
        push    cs
        pop     ds
        jz      .noskip
        mov     si, s_skip
        call    puts
        jmp     exit
.noskip:
        ; ---- clear locals ---------------------------------------------------
        xor     eax, eax
        mov     [bp+V_CAPS], al
        mov     [bp+V_NMTRR], al
        mov     [bp+V_MTRR0], eax
        mov     [bp+V_MTRR1], eax
        mov     [bp+V_FBOFF], eax
        mov     [bp+V_FBKB], eax

        call    detect_cpu
        jnc     .cpu_ok
        ; not a supported AMD CPU: only the chipset part, silent if nothing to do
        test    word [cfg_flags], F_CDDMA
        jz      exit
        call    find_m5229
        jc      exit
        mov     si, s_banner
        call    puts
        call    setup_cddma
        jmp     .done
.cpu_ok:
        mov     si, s_banner
        call    puts

        cli
        wbinvd

        ; ---- 1. memory type ranges (write combining) ---------------------
        test    byte [bp+V_CAPS], C_EFER        ; UWCCR exists on CXT and later
        jz      .no_wc
        call    setup_mtrr
.no_wc:
        ; ---- 2. chipset frame buffer tweak --------------------------------
        test    word [cfg_flags], F_CHIPSET
        jz      .no_cs
        call    chipset_tweak
.no_cs:
        ; ---- 3. write allocate --------------------------------------------
        call    setup_wa

        ; ---- 4. EFER: write order, L2, data prefetch ----------------------
        test    byte [bp+V_CAPS], C_EFER
        jz      .no_efer
        call    setup_efer
.no_efer:
        wbinvd

        ; ---- 5. multiplier --------------------------------------------------
        test    byte [bp+V_CAPS], C_MULT
        jz      .no_mul
        cmp     byte [cfg_multi], 7
        ja      .no_mul
        call    setup_multi
.no_mul:
        ; ---- 6. CD/DVD DMA (ALi M5229) --------------------------------------
        test    word [cfg_flags], F_CDDMA
        jz      .done
        call    setup_cddma
.done:
        mov     si, s_crlf
        call    puts
exit:
        add     sp, V_SIZE
        pop     es
        pop     ds
        popad
        popfd
        retf

; =============================================================================
;  detect_cpu: CF=1 if unsupported. Sets [bp+V_CAPS].
; =============================================================================
detect_cpu:
        ; CPUID available? (toggle EFLAGS.ID)
        pushfd
        pop     eax
        mov     ecx, eax
        xor     eax, 200000h
        push    eax
        popfd
        pushfd
        pop     eax
        push    ecx
        popfd
        xor     eax, ecx
        jz      .bad

        xor     eax, eax
        cpuid
        cmp     ebx, 'Auth'
        jne     .bad
        cmp     edx, 'enti'
        jne     .bad
        cmp     ecx, 'cAMD'
        jne     .bad

        mov     eax, 1
        cpuid
        mov     bl, ah
        and     bl, 0Fh                 ; family
        cmp     bl, 5
        jne     .bad
        mov     bl, al
        shr     bl, 4                   ; model
        and     al, 0Fh                 ; stepping
        xor     ah, ah                  ; caps

        cmp     bl, 6
        jb      .bad                    ; K5: not handled here
        cmp     bl, 8
        jb      .done                   ; K6 (model 6/7): old WHCR only
        ja      .gt8
        cmp     al, 8                   ; model 8: K6-2, CXT if stepping >= 8
        jb      .done
        mov     ah, C_NEWWHCR|C_EFER
        jmp     .done
.gt8:   cmp     bl, 9
        jne     .not9
        mov     ah, C_NEWWHCR|C_EFER|C_L2               ; K6-III
        jmp     .done
.not9:  cmp     bl, 0Dh
        jne     .bad
        mov     ah, C_NEWWHCR|C_EFER|C_L2|C_MULT        ; K6-2+ / K6-III+
.done:  mov     [bp+V_CAPS], ah
        clc
        ret
.bad:   stc
        ret

; =============================================================================
;  setup_mtrr: build UWCCR from VGA region and PCI/AGP frame buffers
; =============================================================================
setup_mtrr:
        test    word [cfg_flags], F_WC_VGA
        jz      .novga
        mov     eax, 0A0000h
        mov     ecx, 128
        call    add_mtrr
.novga:
        test    word [cfg_flags], F_WC_PCI
        jz      .nopci
        call    scan_pci_fb
.nopci:
        test    word [cfg_flags], F_WC_3DFX
        jz      .no3d
        call    setup_3dfx
.no3d:
        cmp     byte [bp+V_NMTRR], 0
        je      .none
        mov     ecx, MSR_UWCCR
        mov     eax, [bp+V_MTRR0]
        mov     edx, [bp+V_MTRR1]
        WRMSR_
        ret
.none:
        mov     si, s_nofb
        call    puts
        ret

; -----------------------------------------------------------------------------
;  add_mtrr: EAX = offset, ECX = size in KB. Adds a WC region if a slot is free.
; -----------------------------------------------------------------------------
add_mtrr:
        cmp     byte [bp+V_NMTRR], 2
        jae     .ret
        test    eax, 1FFFFh             ; must be 128 KB aligned
        jnz     .ret
        cmp     ecx, 128
        jb      .ret
        ; already present? (only slot 0 can be in use here)
        cmp     byte [bp+V_NMTRR], 0
        je      .new
        mov     ebx, [bp+V_MTRR0]
        and     ebx, 0FFFE0000h
        cmp     ebx, eax
        je      .ret
.new:
        push    eax
        push    ecx
        ; find smallest 128K<<i >= size
        xor     bx, bx                  ; i
        mov     edx, 128
.lp:    cmp     edx, ecx
        jae     .found
        cmp     bx, 15
        jae     .found
        shl     edx, 1
        inc     bx
        jmp     .lp
.found: mov     cl, bl
        mov     edx, 7FFFh
        shl     edx, cl
        and     edx, 7FFFh              ; mask
        shl     edx, 2
        and     eax, 0FFFE0000h
        or      eax, edx
        or      al, 2                   ; WC
        push    di
        movzx   di, byte [bp+V_NMTRR]
        shl     di, 2
        mov     [bp+di+V_MTRR0], eax
        pop     di
        inc     byte [bp+V_NMTRR]
        pop     ecx
        pop     eax
        ; remember first non-VGA region for the chipset tweak
        cmp     eax, 0A0000h
        je      .msg
        cmp     dword [bp+V_FBKB], 0
        jne     .msg
        mov     [bp+V_FBOFF], eax
        mov     [bp+V_FBKB], ecx
.msg:   mov     si, s_wc
        call    puts
        call    puthex32
        mov     al, '/'
        call    putc
        mov     eax, ecx
        shr     eax, 10
        jnz     .mb
        mov     eax, ecx
        call    putdec
        mov     al, 'K'
        call    putc
        ret
.mb:    call    putdec
        mov     al, 'M'
        call    putc
.ret:   ret

; -----------------------------------------------------------------------------
;  scan_pci_fb: find display controllers (class 0300) on bus 0-7,
;  add prefetchable memory BARs >= 1 MB as WC regions.
; -----------------------------------------------------------------------------
scan_pci_fb:
        mov     esi, 80000000h          ; bus 0 dev 0 fn 0
.dev:
        mov     ebx, esi
        call    pci_rd
        cmp     ax, 0FFFFh
        je      .next
        lea     ebx, [esi+08h]
        call    pci_rd
        shr     eax, 16
        cmp     ax, 0300h
        jne     .next
        lea     ebx, [esi+0Ch]
        call    pci_rd
        shr     eax, 16
        test    al, 7Fh                 ; header type 0 only
        jnz     .next

        mov     edi, 10h                ; BAR register
.bar:
        lea     ebx, [esi+edi]
        call    pci_rd
        test    al, 1                   ; I/O BAR
        jnz     .nextbar
        mov     edx, eax
        and     dl, 6
        cmp     dl, 4                   ; 64-bit BAR: skip upper half too
        jne     .not64
        add     edi, 4
        jmp     .nextbar
.not64:
        test    al, 8                   ; prefetchable?
        jnz     .pf
        test    word [cfg_flags], F_NONPF
        jz      .nextbar
.pf:
        and     eax, 0FFFFFFF0h
        jz      .nextbar
        mov     [bp+V_TMP], eax         ; base address
        call    size_bar                ; EDX = size in bytes
        cmp     edx, 100000h
        jb      .nextbar
        shr     edx, 10
        mov     ecx, edx
        mov     eax, [bp+V_TMP]
        push    esi
        push    edi
        call    add_mtrr
        pop     edi
        pop     esi
.nextbar:
        add     edi, 4
        cmp     edi, 24h
        jbe     .bar
.next:
        add     esi, 800h               ; next device (function 0 only)
        cmp     esi, 80080000h          ; up to bus 7
        jb      .dev
        ret

; -----------------------------------------------------------------------------
;  size_bar: ESI = function address, EDI = BAR register (memory BAR).
;  Returns EDX = size in bytes (0 = invalid / 4 GB). All other regs preserved.
;  Memory decode is switched off meanwhile, except for the host bridge
;  (bus 0 dev 0), whose command register is left alone.
; -----------------------------------------------------------------------------
size_bar:
        push    eax
        push    ebx
        push    ecx
        lea     ebx, [esi+04h]
        call    pci_rd
        push    eax                     ; command/status
        cmp     esi, 80000000h
        je      .nodis
        and     eax, 0FFFFh
        and     al, 0FDh                ; memory space off
        mov     ecx, eax
        call    pci_wr
.nodis: lea     ebx, [esi+edi]
        call    pci_rd
        push    eax                     ; original BAR
        or      ecx, -1
        call    pci_wr
        call    pci_rd
        mov     edx, eax
        pop     ecx
        call    pci_wr                  ; restore BAR
        pop     ecx
        and     ecx, 0FFFFh             ; don't write status (RW1C)
        lea     ebx, [esi+04h]
        call    pci_wr                  ; restore command
        and     edx, 0FFFFFFF0h
        neg     edx                     ; size = ~mask + 1
        pop     ecx
        pop     ebx
        pop     eax
        ret

; -----------------------------------------------------------------------------
;  setup_3dfx: one WC region covering all 3dfx Voodoo 1/Rush/Voodoo2 cards
;  (memory BAR 0), if a slot is free, the block lies above RAM and no other
;  PCI device has memory inside it.
; -----------------------------------------------------------------------------
setup_3dfx:
        cmp     byte [bp+V_NMTRR], 2
        jae     .ret
        or      dword [bp+V_LO], -1
        mov     dword [bp+V_HI], 0
        mov     esi, 80000000h
.dev:   mov     ebx, esi
        call    pci_rd
        call    is_3dfx
        jne     .next
        mov     edi, 10h
        lea     ebx, [esi+edi]
        call    pci_rd
        test    al, 1
        jnz     .next
        and     eax, 0FFFFFFF0h
        jz      .next
        mov     ecx, eax
        call    size_bar
        or      edx, edx
        jz      .next
        cmp     ecx, [bp+V_LO]
        jae     .lo_ok
        mov     [bp+V_LO], ecx
.lo_ok: add     ecx, edx
        jc      .next
        cmp     ecx, [bp+V_HI]
        jbe     .next
        mov     [bp+V_HI], ecx
.next:  add     esi, 800h
        cmp     esi, 80080000h
        jb      .dev
        cmp     dword [bp+V_HI], 0
        je      .ret                    ; no 3dfx card
        ; smallest 128K<<i block, aligned to its size, covering [LO, HI)
        mov     edx, 20000h
.sz:    mov     eax, edx
        dec     eax
        not     eax
        and     eax, [bp+V_LO]          ; block base
        mov     ebx, eax
        add     ebx, edx                ; block end
        jc      .ret
        cmp     ebx, [bp+V_HI]
        jae     .gotsz
        shl     edx, 1
        cmp     edx, 40000000h          ; give up above 1 GB
        ja      .ret
        jmp     .sz
.gotsz: mov     [bp+V_LO], eax
        mov     [bp+V_HI], ebx
        push    di
        call    get_memsize             ; must lie above RAM
        pop     di
        shl     eax, 10
        cmp     [bp+V_LO], eax
        jb      .conflict
        call    check_conflict
        jc      .conflict
        mov     eax, [bp+V_LO]
        mov     ecx, [bp+V_HI]
        sub     ecx, eax
        shr     ecx, 10
        push    dword [bp+V_FBKB]       ; chipset tweak stays on the graphics card
        call    add_mtrr
        pop     dword [bp+V_FBKB]
.ret:   ret
.conflict:
        mov     si, s_3dconf
        call    puts
        ret

is_3dfx:                                ; EAX = device/vendor, ZF=1 if 3dfx SST-1/2
        cmp     eax, 0001121Ah          ; Voodoo Graphics / Voodoo Rush 3D
        je      .r
        cmp     eax, 0002121Ah          ; Voodoo2
.r:     ret

; -----------------------------------------------------------------------------
;  check_conflict: CF=1 if a memory BAR of any non-3dfx device (bus 0-7, all
;  functions, header type 0) overlaps [V_LO, V_HI).
; -----------------------------------------------------------------------------
check_conflict:
        mov     esi, 80000000h
.dev:   mov     ebx, esi
        call    pci_rd
        cmp     ax, 0FFFFh
        je      .next
        call    is_3dfx
        je      .next
        lea     ebx, [esi+0Ch]
        call    pci_rd
        shr     eax, 16
        test    al, 7Fh
        jnz     .next                   ; bridges: their devices are checked directly
        mov     edi, 10h
.bar:   lea     ebx, [esi+edi]
        call    pci_rd
        test    al, 1
        jnz     .nb
        mov     edx, eax
        and     dl, 6
        cmp     dl, 4
        jne     .n64
        add     edi, 4                  ; 64-bit: skip upper half
.n64:   and     eax, 0FFFFFFF0h
        jz      .nb
        mov     ecx, eax
        call    size_bar
        or      edx, edx
        jnz     .sized
        inc     edx                     ; unknown size: check base only
.sized: cmp     ecx, [bp+V_HI]
        jae     .nb
        add     ecx, edx
        jc      .hit
        cmp     ecx, [bp+V_LO]
        ja      .hit
.nb:    add     edi, 4
        cmp     edi, 24h
        jbe     .bar
.next:  add     esi, 100h
        cmp     esi, 80080000h
        jb      .dev
        clc
        ret
.hit:   stc
        ret

; -----------------------------------------------------------------------------
;  setup_cddma: ALi M5229 register 53h bit 0 = CD-ROM DMA enable (as ALi5DMA)
; -----------------------------------------------------------------------------
setup_cddma:
        call    find_m5229
        jc      .ret
        mov     cl, 53h
        call    pci_rdb
        test    al, 01h
        jnz     .ok
        or      al, 01h
        call    pci_wrb
        call    pci_rdb
        test    al, 01h
        jnz     .ok
        mov     si, s_cdfail
        call    puts
        ret
.ok:    mov     si, s_cddma
        call    puts
.ret:   ret

find_m5229:                             ; EBX = address of 10B9:5229 on bus 0, CF=1 none
        mov     ebx, 80000000h
.lp:    call    pci_rd
        cmp     eax, 522910B9h
        je      .ok
        add     ebx, 100h
        cmp     ebx, 80010000h
        jb      .lp
        stc
        ret
.ok:    clc
        ret

; ---- byte access: EBX = function address (reg 0), CL = register, AL = data ----
pci_rdb:
        push    edx
        push    eax
        call    pci_badr
        pop     eax
        in      al, dx
        pop     edx
        ret
pci_wrb:
        push    edx
        push    eax
        call    pci_badr
        pop     eax
        out     dx, al
        pop     edx
        ret
pci_badr:                               ; select dword, DX = CFCh + (CL & 3)
        movzx   eax, cl
        and     al, 0FCh
        or      eax, ebx
        mov     dx, 0CF8h
        out     dx, eax
        mov     dl, cl
        and     dl, 3
        add     dl, 0FCh
        ret

; ---- PCI config mechanism #1: EBX = address, EAX = data -----------------------
pci_rd:
        push    dx
        mov     eax, ebx
        and     al, 0FCh
        mov     dx, 0CF8h
        out     dx, eax
        mov     dl, 0FCh
        in      eax, dx
        pop     dx
        ret
pci_wr:                                 ; EBX = address, ECX = data
        push    dx
        push    eax
        mov     eax, ebx
        and     al, 0FCh
        mov     dx, 0CF8h
        out     dx, eax
        mov     dl, 0FCh
        mov     eax, ecx
        out     dx, eax
        pop     eax
        pop     dx
        ret

; -----------------------------------------------------------------------------
;  pci_find: EAX = device/vendor id. Bus 0 only. Returns EBX = address, CF=1 none
; -----------------------------------------------------------------------------
pci_find:
        mov     edx, eax
        mov     ebx, 80000000h
.lp:    call    pci_rd
        cmp     eax, edx
        je      .ok
        add     ebx, 800h
        cmp     ebx, 80010000h
        jb      .lp
        stc
        ret
.ok:    clc
        ret

; =============================================================================
;  chipset_tweak: ALi Aladdin V (M1541 + M5243) frame buffer write cycles
; =============================================================================
chipset_tweak:
        mov     ecx, [bp+V_FBKB]
        jecxz   .ret                    ; no frame buffer found
        mov     eax, 154110B9h
        call    pci_find
        jc      .ret
        ; size code: smallest n with (1<<n) MB >= size. The Aladdin V officially
        ; supports frame buffers up to 16 MB, so the size is capped at 16 MB
        ; (code 4); write combining itself keeps the full size.
        shr     ecx, 10                 ; MB
        cmp     ecx, 16
        jbe     .cap
        mov     cx, 16
.cap:   xor     dx, dx
.sz:    mov     ax, 1
        push    cx
        mov     cl, dl
        shl     ax, cl
        pop     cx
        cmp     ax, cx
        jae     .szok
        inc     dx
        cmp     dx, 7
        jb      .sz
.szok:
        mov     eax, [bp+V_FBOFF]
        shr     eax, 20
        shl     ax, 4
        or      al, dl                  ; reg 84h/85h value (bit3 all-PCI = 0)
        mov     [bp+V_TMP], ax
        mov     cl, 05h                 ; reg 86h: FB enable + PCI write burst
        test    word [cfg_flags], F_WC_VGA
        jz      .novga
        or      cl, 02h                 ; VGA frame buffer too
.novga: mov     [bp+V_TMP+2], cl

        call    .write                  ; M1541 (EBX from pci_find)
        mov     eax, 524310B9h
        call    pci_find
        jc      .done
        call    .write                  ; M5243 AGP bridge
.done:  mov     si, s_chipset
        call    puts
.ret:   ret

.write: ; RMW dword 84h: replace bytes 84h-86h, keep 87h
        add     bl, 84h
        call    pci_rd
        and     eax, 0FF000000h
        mov     ecx, [bp+V_TMP]
        and     ecx, 00FFFFFFh
        or      ecx, eax
        call    pci_wr
        ret

; =============================================================================
;  setup_wa: write allocate up to top of memory (+ 15-16M hole)
; =============================================================================
setup_wa:
        mov     al, [cfg_wa]
        or      al, al
        jz      .ret
        cmp     al, 1
        jne     .force
        mov     ecx, MSR_WHCR
        RDMSR_
        or      eax, eax
        jz      .force
        mov     si, s_wabios
        call    puts
.ret:   ret
.force:
        call    get_memsize             ; EAX = KB, DI = hole flag
        jmp     wa_have

; -----------------------------------------------------------------------------
;  get_memsize: EAX = total memory in KB, DI = 1 if 15-16M hole. INT 15h E801/88h
; -----------------------------------------------------------------------------
get_memsize:
        push    bx
        push    cx
        push    dx
        xor     cx, cx
        xor     dx, dx
        xor     bx, bx
        mov     ax, 0E801h
        clc
        int     15h
        jc      .e88
        cmp     ah, 86h
        je      .e88
        jcxz    .axbx
        mov     ax, cx
        mov     bx, dx
.axbx:  ; AX = KB between 1M and 16M, BX = 64K blocks above 16M
        xor     di, di                  ; DI = hole flag
        cmp     ax, 14336               ; exactly 14 MB -> 15-16M hole
        jne     .nohole
        or      bx, bx
        jz      .nohole
        inc     di
.nohole:
        or      bx, bx
        jz      .low
        movzx   eax, bx
        shl     eax, 6                  ; KB
        add     eax, 16384
        jmp     .gm
.low:   movzx   eax, ax
        add     eax, 1024
        jmp     .gm
.e88:   mov     ah, 88h
        int     15h
        movzx   eax, ax
        add     eax, 1024
        xor     di, di
.gm:    pop     dx
        pop     cx
        pop     bx
        ret

wa_have:        ; (setup_wa continued) EAX = total memory in KB, DI = hole
        mov     ebx, eax
        test    byte [bp+V_CAPS], C_NEWWHCR
        jz      .old
        shl     eax, 10
        and     eax, 0FFC00000h
        mov     cx, di
        shl     ecx, 16
        and     ecx, 10000h
        or      eax, ecx
        jmp     .wr
.old:   shr     eax, 12                 ; 4 MB blocks
        cmp     eax, 127
        jbe     .oldok
        mov     eax, 127
.oldok: shl     eax, 1
        mov     cx, di
        and     ecx, 1
        or      eax, ecx
.wr:    xor     edx, edx
        mov     ecx, MSR_WHCR
        WRMSR_
        mov     si, s_wa
        call    puts
        mov     eax, ebx
        shr     eax, 10
        and     al, 0FCh                ; 4 MB granularity
        call    putdec
        mov     al, 'M'
        call    putc
        or      di, di
        jz      .r2
        mov     si, s_hole
        call    puts
.r2:    ret

; =============================================================================
;  setup_efer: write order mode, L2 enable, data prefetch
; =============================================================================
setup_efer:
        mov     ecx, MSR_EFER
        RDMSR_
        mov     bx, [cfg_flags]
        test    bx, F_WO
        jz      .nowo
        and     eax, 0F3h
        mov     cl, [cfg_wo]
        and     cl, 3
        cmp     cl, 2
        jbe     .wook
        mov     cl, 1
.wook:  shl     cl, 2
        or      al, cl
        mov     si, s_wo
        call    puts
.nowo:
        mov     [bp+V_TMP], eax         ; EFER value being built
        test    bx, F_L2
        jz      .nol2
        test    byte [bp+V_CAPS], C_L2
        jz      .nol2
        and     byte [bp+V_TMP], 0EFh
        mov     si, s_l2
        call    puts
.nol2:  test    bx, F_DPE
        jz      .nodpe
        or      byte [bp+V_TMP], 02h
        mov     si, s_dpe
        call    puts
.nodpe: mov     eax, [bp+V_TMP]
        mov     ecx, MSR_EFER
        WRMSR_
        ret

; =============================================================================
;  setup_multi: K6-2+/III+ frequency multiplier via EPMR / BVC
; =============================================================================
setup_multi:
        mov     ecx, MSR_EPMR
        mov     eax, 0FFF1h             ; I/O block at FFF0h, enabled
        xor     edx, edx
        WRMSR_
        movzx   eax, byte [cfg_multi]
        and     eax, 7
        shl     eax, 5                  ; internal bus divisor field
        or      eax, 1000h | 0200h      ; stop grant counter, sample IBF
        mov     dx, 0FFF8h              ; BVC register
        out     dx, eax
        mov     ecx, MSR_EPMR
        mov     eax, 0FFF0h             ; I/O block off
        xor     edx, edx
        WRMSR_
        mov     si, s_mul
        call    puts
        mov     si, cfg_mtxt
        mov     cx, 3
.lp:    lodsb
        call    putc
        loop    .lp
        ret

; =============================================================================
;  Console output (INT 10h teletype); all registers preserved
; =============================================================================
putc:
        test    word [cs:cfg_flags], F_QUIET
        jnz     .r
        pushad
        mov     ah, 0Eh
        mov     bx, 0007h
        int     10h
        popad
.r:     ret

puts:   ; CS:SI = zero terminated
        push    si
        push    ax
.lp:    cs lodsb
        or      al, al
        jz      .end
        call    putc
        jmp     .lp
.end:   pop     ax
        pop     si
        ret

puthex32:       ; EAX
        push    eax
        push    cx
        mov     cx, 8
.lp:    rol     eax, 4
        push    eax
        and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     .d
        add     al, 7
.d:     call    putc
        pop     eax
        loop    .lp
        pop     cx
        pop     eax
        ret

putdec:         ; EAX (unsigned)
        pushad
        mov     ebx, 10
        xor     cx, cx
.div:   xor     edx, edx
        div     ebx
        push    dx
        inc     cx
        or      eax, eax
        jnz     .div
.out:   pop     ax
        add     al, '0'
        call    putc
        loop    .out
        popad
        ret

; =============================================================================
;  Strings
; =============================================================================
s_banner        db 13, 10, 'K6PLUS:', 0
s_skip          db 13, 10, 'K6PLUS: skipped (SHIFT)', 13, 10, 0
s_wc            db ' WC=', 0
s_nofb          db ' WC=none', 0
s_chipset       db ' ALi-FB', 0
s_wa            db ' WA=', 0
s_wabios        db ' WA=BIOS', 0
s_hole          db '+hole', 0
s_wo            db ' WO', 0
s_l2            db ' L2', 0
s_dpe           db ' DPE', 0
s_mul           db ' x', 0
s_3dconf        db ' WC3D=conflict', 0
s_cddma         db ' CD-DMA', 0
s_cdfail        db ' CD-DMA:fail', 0
s_crlf          db 13, 10, 0

        times   ROM_BLOCKS*512-1-($-$$) db 0
        db      0                       ; checksum (set by k6cfg.py)
