# 바이블 로더 훅 — 0x8020BE1C 의 «stw r3,0x28(r29)» 를 «b hook_bib» 로 바꾼다.
# r29 = 언어 객체(문자열 영역 blob 을 막 대입하는 중). 원래 명령을 그대로 하고 객체를 g_lang 에 남긴다.
# r12 는 호출 규약상 죽는 레지스터라 써도 된다(v0.8 cave5 와 같은 판단).
# 저메모리 케이브(.lowtext)에 둔다 — 부팅 때 바로 불리므로 «확실히 실리는» 곳이어야 한다.
    .section .lowtext,"ax",@progbits
    .globl hook_bib
hook_bib:
    stw   3, 0x28(29)
    lis   12, g_lang@ha
    stw   29, g_lang@l(12)
    b     bib_ret
