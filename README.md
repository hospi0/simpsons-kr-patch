# 심슨 히트 앤 런 (게임큐브 북미판) 한글 패치

> **내려받기:** [릴리즈 페이지](https://github.com/hospi0/simpsons-kr-patch/releases/latest) — 최신 v0.9. 적용 방법·원본 MD5 는 패치 묶음의 readme 에 있습니다.
>
> 이 저장소에는 도구·번역 텍스트·작업 문서만 있습니다(ROM·빌드 결과물 없음).

## v0.9

- 음성 자막을 새로 구현 — 소리 재생 훅 + 자체 그리기(`ksub/`, `tools/ksub.py`), 3,862줄
- 자막 없던 음성 3,259줄 받아쓰기·번역(`work/snd/`)
- 튜토리얼 상자 한글 + 원본 버튼 아이콘(`tools/tutkr.py`, `work/tut/tut_ko.tsv`)
- UI 한글 폰트 1.5배 해상도(`tools/kfont2x.py`)
- 작업 기록: `docs/08_v0.9_소리재생훅.md`
