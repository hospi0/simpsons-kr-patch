# -*- coding: utf-8 -*-
"""대사 재생 전환을 감시해 자막을 순서대로 넘긴다 (훅이 할 일의 호스트판 흉내)."""
import sys, time
sys.path.insert(0, r'C:\claude\project\gc-modern-controls\tools')
from dolmem import Dolphin
STATE=0x8044A7C8; PLAYING=0x803039A8
BASE=0x808BC918     # ★짝수 (LE 검색 주소 -1) · RAM 은 UTF-16 BE
L1=BASE+0x9EAE      # 자막 1줄 슬롯 (Accept 요소가 읽음)
L2=BASE+0x5EE0      # 자막 2줄 슬롯 (Cancel 요소가 읽음)
LINES=[
 ("Homie, somebody ate every dessert in the house.", "[1/4] Marge"),
 ("Uh, must have been one of our kids, probably Milhouse.", "[2/4] Homer"),
 ("Get some of that ice cream with the little pies.", "[3/4] Marge"),
 ("D'oh! Do I have to?", "[4/4] Homer"),
]
d=Dolphin()
def w(addr,s): d.write(addr, s.encode('utf-16-be')+b'\x00\x00')
w(L1,"(waiting for dialogue...)"); w(L2,"")
prev=d.u32(STATE); n=0
t0=time.time()
print('감시 시작 — 대화를 시작하세요 (60초)', flush=True)
while time.time()-t0 < 60:
    v=d.u32(STATE)
    if v!=prev:
        if v==PLAYING:
            a,b=LINES[n%len(LINES)]
            w(L1,a); w(L2,b); n+=1
            print('  %5.1fs  대사 %d 시작 → 자막 갱신: %s' % (time.time()-t0, n, a[:40]), flush=True)
        else:
            print('  %5.1fs  대사 끝' % (time.time()-t0), flush=True)
        prev=v
    time.sleep(0.02)
print('총 %d줄 전환' % n)
