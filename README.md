---
title: Medit Video Hub
emoji: 🦷
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 4.44.0
app_file: app.py
pinned: false
license: mit
short_description: YouTube 영상에 다국어 자막을 입혀 Drive에 백업
---

# 🦷 Medit Video Hub

메디트 마케팅팀 내부 도구 — YouTube 영상에 다국어 자막(유튜브 스타일 반투명 박스)을 입혀 인코딩하고, 결과물을 마케팅팀 Google Drive에 자동 백업합니다.

## 주요 기능

- 유튜브 URL 입력 → 영상 + 자막(공식/자동 생성) 다운로드
- 언어별 적절한 폰트 자동 매칭
  - 한국어/영어/라틴: Pretendard
  - 일본어/중국어: Noto Sans CJK
  - 아랍어/히브리어/태국어 등: Noto Sans 계열
- 유튜브 스타일 자막 박스 (반투명 검정 배경 + 흰 글씨)
- 결과물 즉시 다운로드 + Google Drive 자동 백업
- 동시 요청 2건까지 병렬 처리

## 환경 변수 (HF Space Secrets)

| 키 | 설명 |
|---|---|
| `GDRIVE_CREDENTIALS` | Google Cloud Service Account의 JSON 키 파일 내용 (통째로) |
| `DRIVE_FOLDER_ID` | 결과물이 저장될 Drive 폴더 ID (기본값 코드에 하드코딩됨) |

## 로컬 실행 (개발용)

```bash
pip install -r requirements.txt
sudo apt-get install -y ffmpeg fonts-noto-cjk fonts-noto-core

export GDRIVE_CREDENTIALS=$(cat /path/to/service-account.json)
export DRIVE_FOLDER_ID=your_folder_id
python app.py
```

## 라이선스

내부 사용 목적. 메디트 자사 채널 영상에 한정해 사용.
