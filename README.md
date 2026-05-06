# KStudio

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Windows 용 1인 사용자 스튜디오 — 스크린 녹화 + 스크린샷 + 주석/이미지 편집을 한
프로그램에서.

> 옛 이름: Screen Recorder. archive 된 [KimyoriPhotoShop](https://github.com/kimyori7/KimyoriPhotoShop)
> (JS 기반 Phase 1 완료) 의 이미지 편집 기능을 흡수하면서 더 넓은 도구로 발전 중.

## 주요 기능

- **스크린 녹화** — 전체 화면 / 특정 창 / 지정 영역. mp4 (H.264/H.265) + GIF 출력
- **스크린샷** — 전체 / 영역. 다중 모니터 지원
- **이미지 편집** — 주석 (사각형/화살표/텍스트/브러시), 자르기, 마법봉 선택,
  배경 제거 (rembg), AI 업스케일
- **영상 트림** — `[`/`]` 로 in/out 마크 → 잘라내기
- **드래그 저장** — 라이브러리 항목 또는 글로벌 툴바에서 폴더로 드래그하면 PNG 저장
- **다국어** — 한국어 / 영어 (Preferences → Language)

## 설치 / 실행 (소스에서)

```bash
pip install -e .[dev]
python -m screen_recorder
```

`bin/ffmpeg.exe` 가 동봉돼 있어 별도 설치 불필요. (없으면 시스템 PATH 의 ffmpeg 사용)

## 빌드 (PyInstaller + Inno Setup)

```bash
# 1. PyInstaller onedir 빌드
pyinstaller KStudio.spec
# 2. dist/KStudio/ 가 생성됨. Inno Setup 으로 인스톨러 생성:
ISCC installer\KStudio.iss
# 결과: dist/installer/KStudio-Setup-<version>.exe
```

## 테스트

```bash
pytest
```

## 라이선스

KStudio 소스 코드는 [MIT 라이선스](LICENSE) 입니다. 누구나 자유롭게 사용·수정·
재배포 가능합니다.

> 동봉된 FFmpeg (`bin/ffmpeg.exe`) 는 GPL v3 라이선스라, **빌드된 바이너리/
> 인스톨러 배포물** 은 사실상 GPL v3 의 의무를 따릅니다 (소스 공개 의무 — 본
> 레포가 GitHub 공개라 자동 충족). KStudio 소스 자체는 MIT 그대로 유지되어
> 다른 사람이 코드를 가져다 쓰는 건 자유.

서드파티 라이브러리 라이선스 전체 목록: [THIRD-PARTY-LICENSES.txt](THIRD-PARTY-LICENSES.txt)

## 후원 (Donations)

KStudio 가 도움이 되었다면 따뜻한 한 잔 사주세요 ☕

- ☕ Buy Me a Coffee: *(준비 중 — 셋업 후 링크 추가 예정)*

## 기여

이슈 / PR 환영합니다. 코드 컨벤션은 기존 패턴을 따라주세요. 큰 변경은 먼저 이슈로
논의 부탁드립니다.

## Acknowledgements

- [FFmpeg](https://ffmpeg.org/) — 영상 인코딩의 핵심
- [PySide6 (Qt)](https://www.qt.io/qt-for-python) — UI 프레임워크
- [Lucide Icons](https://lucide.dev/) — UI 아이콘 (icons.py 의 path 데이터)
- [rembg](https://github.com/danielgatis/rembg) — 배경 제거
- [dxcam](https://github.com/ra1nty/DXcam) — 빠른 화면 캡처
