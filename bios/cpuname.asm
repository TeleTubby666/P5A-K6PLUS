; E000:F000 - CPU name for the K6-III branch of the original name routine (called from E000:D7B5)
; original: mov si,0D89Bh ('AMD-K6(tm)-III'). Model 0Dh (K6-III+) gets its own string.
        bits    16
        org     0F000h
cpuname:
        mov     si, 0D89Bh
        push    eax
        push    ebx
        push    ecx
        push    edx
        mov     eax, 1
        cpuid
        and     ax, 0FF0h
        cmp     ax, 05D0h
        jne     .done
        mov     si, k63plus
.done:  pop     edx
        pop     ecx
        pop     ebx
        pop     eax
        ret
k63plus db      'AMD-K6(tm)-III+', 0
