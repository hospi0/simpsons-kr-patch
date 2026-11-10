/* 두 구역
 *  LOW  = DOL text0 안 0 구간 0x80004888~0x80004D54 (v0.8 자막 케이브 자리, dolhook --reset 으로 비움)
 *         적재기·바이블 훅·공유 변수. 부팅 때 «확실히» 실린다.
 *  HIGH = 0x8048AC00~0x8048CB00 (스택 끝과 아레나 사이 8KB, 런타임 0 확인) — 본체.
 *         DOL 새 섹션은 로더가 싣지 않았다(시험 1) → 바이블 블롭에 실어 두고 적재기가 복사한다.
 */
bib_ret = 0x8020BE20;
MEMORY
{
    LOW  (rwx) : ORIGIN = 0x80004888, LENGTH = 0x4CC
    HIGH (rwx) : ORIGIN = 0x8048AC00, LENGTH = 0x1F00
}
SECTIONS
{
    .lowtext : { *(.lowtext*) } > LOW
    .lowdata : { *(.lowdata*) . = ALIGN(4); low_end = .; } > LOW
    .text   : { *(.text*) high_text_end = .; } > HIGH
    .rodata : { *(.rodata*) *(.sdata2*) *(.sbss2*) } > HIGH
    .data   : { *(.data*) *(.sdata*) } > HIGH
    .bss    : { *(.bss*) *(.sbss*) *(COMMON) . = ALIGN(32); } > HIGH
    ksub_end = .;
    /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) }
}
