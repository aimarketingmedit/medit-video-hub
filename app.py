"""
Medit Video Hub - Hugging Face Spaces 배포 버전
- 유튜브 영상에 다국어 자막을 입혀서 인코딩
- 결과물은 Google Drive에 자동 업로드 (Service Account 사용)
"""
import io
import json
import os
import re
import shutil
import subprocess
import uuid

import gradio as gr
import yt_dlp
from babel import Locale
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# =================================================================#
# 설정
# =================================================================#
APP_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_FONT_DIR = os.path.join(APP_DIR, "fonts")
USER_FONT_DIR = os.path.expanduser("~/.fonts")
TMP_DIR = "/tmp/medit-video-hub"
os.makedirs(TMP_DIR, exist_ok=True)

# 환경변수 (HF Spaces Secrets로 주입)
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "1yfx85aafe424guB_aGefjTcrxTByoQ1-")
GDRIVE_CREDENTIALS = os.environ.get("GDRIVE_CREDENTIALS", "")


# =================================================================#
# 번들된 폰트를 fontconfig가 인식하는 위치로 복사 + 캐시 갱신
#  (Pretendard는 repo에 동봉, Noto는 packages.txt로 설치)
# =================================================================#
def install_bundled_fonts():
    if not os.path.exists(BUNDLED_FONT_DIR):
        print("[Font] Bundled fonts directory not found, skip")
        return
    os.makedirs(USER_FONT_DIR, exist_ok=True)
    copied = 0
    for f in os.listdir(BUNDLED_FONT_DIR):
        if f.endswith((".otf", ".ttf")):
            src = os.path.join(BUNDLED_FONT_DIR, f)
            dst = os.path.join(USER_FONT_DIR, f)
            if not os.path.exists(dst):
                shutil.copy(src, dst)
                copied += 1
    if copied:
        subprocess.run(["fc-cache", "-fv"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[Font] Installed {copied} bundled font(s)")


install_bundled_fonts()


# =================================================================#
# 언어 코드 → 폰트 매핑 (Pretendard로 안 되는 스크립트만 Noto로 분기)
# =================================================================#
DEFAULT_FONT = "Pretendard"
LANG_FONT_MAP = {
    # 아시아 (CJK 한자)
    "ja":      "Noto Sans CJK JP",
    "zh":      "Noto Sans CJK SC",
    "zh-Hans": "Noto Sans CJK SC",
    "zh-CN":   "Noto Sans CJK SC",
    "zh-Hant": "Noto Sans CJK TC",
    "zh-TW":   "Noto Sans CJK TC",
    "zh-HK":   "Noto Sans CJK TC",
    # 아시아 (기타 스크립트)
    "th":      "Noto Sans Thai",
    "hi":      "Noto Sans Devanagari",
    "bn":      "Noto Sans Bengali",
    "ta":      "Noto Sans Tamil",
    "te":      "Noto Sans Telugu",
    "ml":      "Noto Sans Malayalam",
    "kn":      "Noto Sans Kannada",
    "si":      "Noto Sans Sinhala",
    "my":      "Noto Sans Myanmar",
    "km":      "Noto Sans Khmer",
    "lo":      "Noto Sans Lao",
    # 중동
    "ar":      "Noto Sans Arabic",
    "fa":      "Noto Sans Arabic",
    "ur":      "Noto Sans Arabic",
    "ps":      "Noto Sans Arabic",
    "he":      "Noto Sans Hebrew",
    "iw":      "Noto Sans Hebrew",
    "yi":      "Noto Sans Hebrew",
    # 라틴 계열은 Pretendard 그대로
}


def get_font_for_lang(lang_code: str) -> str:
    if not lang_code:
        return DEFAULT_FONT
    if lang_code in LANG_FONT_MAP:
        return LANG_FONT_MAP[lang_code]
    base = lang_code.split('-')[0]
    return LANG_FONT_MAP.get(base, DEFAULT_FONT)


# =================================================================#
# Google Drive 업로드 (Service Account)
# =================================================================#
_drive_service = None


def get_drive_service():
    """Google Drive API 서비스 객체. 자격증명 없으면 None."""
    global _drive_service
    if _drive_service is not None:
        return _drive_service
    if not GDRIVE_CREDENTIALS:
        print("[Drive] GDRIVE_CREDENTIALS not set, Drive upload disabled")
        return None
    try:
        info = json.loads(GDRIVE_CREDENTIALS)
        creds = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        _drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
        print("[Drive] Service initialized")
        return _drive_service
    except Exception as e:
        print(f"[Drive] Init failed: {e}")
        return None


def upload_to_drive(local_path: str, filename: str):
    """Drive 폴더에 파일 업로드. (webViewLink, error_msg) 튜플 반환."""
    svc = get_drive_service()
    if not svc:
        return None, "Drive 미연동 (관리자 확인 필요)"
    try:
        media = MediaFileUpload(local_path, mimetype="video/mp4", resumable=True)
        f = svc.files().create(
            body={"name": filename, "parents": [DRIVE_FOLDER_ID]},
            media_body=media,
            fields="id, webViewLink",
            supportsAllDrives=True,
        ).execute()
        link = f.get("webViewLink")
        print(f"[Drive] Uploaded: {link}")
        return link, None
    except Exception as e:
        print(f"[Drive] Upload failed: {e}")
        return None, str(e)


# =================================================================#
# Helper
# =================================================================#
def get_file_size_mb(file_path: str) -> float:
    return round(os.path.getsize(file_path) / (1024 * 1024), 2)


def get_full_language_name(code: str) -> str:
    try:
        mapping = {
            "ko": "Korean", "en": "English", "ja": "Japanese",
            "zh-Hans": "Chinese (Simplified)", "zh-Hant": "Chinese (Traditional)",
        }
        base = code.split("-")[0]
        name = mapping.get(code) or mapping.get(base) or Locale.parse(base).display_name
        return f"{name} ({code})"
    except Exception:
        return code


def get_video_info_final(url: str):
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get("title", "video")
        subs = info.get("subtitles", {}) or {}
        auto = info.get("automatic_captions", {}) or {}
        codes = sorted(set(list(subs.keys()) + list(auto.keys())))
        lang_choices = [(get_full_language_name(c), c) for c in codes]
        return title, lang_choices


# =================================================================#
# 메인 처리 함수
# =================================================================#
def process_dental_video_final(url, selected_lang_code, progress=gr.Progress()):
    if not url or not selected_lang_code:
        return None, "오류: URL과 언어를 확인하세요.", ""

    job_id = uuid.uuid4().hex[:8]
    job_dir = os.path.join(TMP_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    try:
        progress(0, desc="유튜브 데이터 분석 중...")
        raw_title, _ = get_video_info_final(url)
        clean_title = re.sub(r'[\\/*?:"<>|]', "", raw_title).strip()

        video_in        = os.path.join(job_dir, f"{clean_title}.mp4")
        video_out_local = os.path.join(job_dir, f"{clean_title}_{selected_lang_code}.mp4")
        safe_srt        = os.path.join(job_dir, "_sub.srt")

        # 1) 다운로드
        progress(0.1, desc="영상 및 자막 추출 중...")
        dl_opts = [
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
            "--write-subs", "--write-auto-subs",
            "--sub-langs", selected_lang_code,
            "--convert-subs", "srt",
            "-o", os.path.join(job_dir, f"{clean_title}.%(ext)s"),
            url,
        ]
        subprocess.run(dl_opts, check=False)

        srt_actual = os.path.join(job_dir, f"{clean_title}.{selected_lang_code}.srt")
        if not os.path.exists(srt_actual):
            srt_candidates = [f for f in os.listdir(job_dir) if f.endswith(".srt")]
            if srt_candidates:
                srt_actual = os.path.join(job_dir, srt_candidates[0])
            else:
                return None, "자막 파일 로드 실패", ""

        shutil.copy(srt_actual, safe_srt)

        # 2) 자막 스타일 (유튜브 스타일 반투명 박스)
        font_name = get_font_for_lang(selected_lang_code)
        print(f"[Job {job_id}] [Font] {selected_lang_code} → {font_name}")
        sub_style = (
            "force_style='"
            f"FontName={font_name},"
            "FontSize=15,Bold=1,"
            "PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H80000000,"
            "BackColour=&H00000000,"
            "BorderStyle=3,Outline=3,Shadow=0,"
            "Alignment=2,MarginV=40"
            "'"
        )

        # 3) 인코딩
        progress(0.4, desc="고화질 인코딩 중...")
        ff_cmd = [
            "ffmpeg", "-y", "-i", video_in,
            "-vf", f"subtitles=filename={safe_srt}:{sub_style}",
            "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
            "-c:a", "copy",
            video_out_local,
        ]
        subprocess.run(ff_cmd, check=False)

        if not os.path.exists(video_out_local):
            return None, "인코딩 실패", ""

        # 4) Drive 업로드
        progress(0.9, desc="Google Drive에 백업 중...")
        drive_filename = f"Final_{selected_lang_code}_{clean_title}.mp4"
        drive_link, drive_err = upload_to_drive(video_out_local, drive_filename)

        size = get_file_size_mb(video_out_local)
        if drive_link:
            status = f"✅ 성공! (용량: {size}MB) — Drive 백업 완료"
            link_md = f"📂 **[Google Drive에서 보기]({drive_link})**"
        else:
            status = f"⚠️ 인코딩 성공 ({size}MB) — Drive 업로드 실패: {drive_err}"
            link_md = ""

        return video_out_local, status, link_md

    finally:
        # 다음 잡 실행 시 정리되도록 디스크 부담 줄이기:
        # 임시 srt와 원본 mp4만 삭제, 출력 mp4는 다운로드/링크 위해 남김
        try:
            for f in os.listdir(job_dir):
                if f.endswith(".srt") or (f.endswith(".mp4") and not f.endswith(f"_{selected_lang_code}.mp4")):
                    p = os.path.join(job_dir, f)
                    if os.path.exists(p):
                        os.remove(p)
        except Exception:
            pass


# =================================================================#
# Gradio UI
# =================================================================#
CUSTOM_CSS = """
#download_box .file-preview,
#download_box [data-testid="file"] {
    cursor: pointer !important;
    border-radius: 8px !important;
    transition: background 0.15s ease, box-shadow 0.15s ease;
}
#download_box .file-preview:hover,
#download_box [data-testid="file"]:hover {
    background: #eef4ff !important;
    box-shadow: 0 2px 6px rgba(74,144,226,0.2);
}
#download_box .file-preview > *,
#download_box [data-testid="file"] > * {
    cursor: pointer !important;
}
#download_box label {
    font-weight: 700 !important;
    font-size: 15px !important;
    margin-bottom: 6px !important;
}
"""

ROW_CLICK_JS = """
() => {
    const bindClicks = () => {
        const box = document.querySelector('#download_box');
        if (!box) return;
        const rows = box.querySelectorAll('.file-preview, [data-testid="file"], .file, .wrap > div');
        rows.forEach(row => {
            if (row.dataset.rowClickBound === '1') return;
            const link = row.querySelector('a[download], a[href*="/file="], a[href*="gradio_api"], a[href]');
            if (!link) return;
            row.dataset.rowClickBound = '1';
            row.style.cursor = 'pointer';
            row.addEventListener('click', (e) => {
                if (e.target.closest('a') || e.target.closest('button')) return;
                e.preventDefault();
                link.click();
            });
        });
    };
    bindClicks();
    const mo = new MutationObserver(bindClicks);
    mo.observe(document.body, { childList: true, subtree: true });
}
"""

with gr.Blocks(title="Medit Video Hub", css=CUSTOM_CSS, theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🦷 Medit 치과 클리닉 자막 영상 제작 센터")

    with gr.Row():
        gr.Markdown("### 📺 공식 채널 바로가기")
        gr.HTML("""
            <div style="display:flex; gap:10px;">
              <a href="https://www.youtube.com/@meditcompany" target="_blank" style="text-decoration:none;">
                <button style="background:#FF0000;color:#fff;border:0;padding:10px 20px;border-radius:5px;font-weight:bold;cursor:pointer;">Medit Official</button>
              </a>
              <a href="https://www.youtube.com/@MeditAcademy" target="_blank" style="text-decoration:none;">
                <button style="background:#2D2D2D;color:#fff;border:0;padding:10px 20px;border-radius:5px;font-weight:bold;cursor:pointer;">Medit Academy</button>
              </a>
            </div>
        """)

    gr.HTML("<hr style='border:0.5px solid #ddd;margin:20px 0;'>")

    url_input = gr.Textbox(label="1. 유튜브 URL 입력", placeholder="https://youtu.be/...")

    with gr.Column():
        title_display = gr.Markdown("### 🔍 URL을 입력하고 아래 버튼을 눌러주세요.")
        btn_check = gr.Button("2. 영상 확인 및 자막 언어 찾기", variant="secondary")
        lang_dropdown = gr.Dropdown(label="3. 자막 언어 선택", choices=[], interactive=True)

    btn_run = gr.Button("4. 영상 생성 시작 (YouTube Style)", variant="primary")

    status_msg = gr.Textbox(label="진행 상태", interactive=False)
    drive_link_md = gr.Markdown("")
    file_output = gr.File(
        label="📥 인코딩 완료! 행 전체를 클릭하여 다운로드 (MP4)",
        elem_id="download_box",
    )

    def update_ui_info(url):
        try:
            title, lang_choices = get_video_info_final(url)
            return (
                gr.update(choices=lang_choices,
                          value=lang_choices[0][1] if lang_choices else None),
                f"### ✅ 선택된 영상: {title}",
            )
        except Exception:
            return gr.update(choices=[]), "### ❌ 영상을 찾을 수 없습니다."

    btn_check.click(update_ui_info, inputs=url_input,
                    outputs=[lang_dropdown, title_display])
    btn_run.click(process_dental_video_final,
                  inputs=[url_input, lang_dropdown],
                  outputs=[file_output, status_msg, drive_link_md])

    demo.load(fn=None, inputs=None, outputs=None, js=ROW_CLICK_JS)


# 동시 처리 슬롯 2개 (HF 무료 CPU 부담 고려)
demo.queue(default_concurrency_limit=2, max_size=20)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
