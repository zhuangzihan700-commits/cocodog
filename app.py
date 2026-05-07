# app.py
# ------------------------------------------------------------
# Streamlit + Gemini API 기반 고객 응대 챗봇
# ------------------------------------------------------------
# 주요 기능
# 1. Gemini 모델 선택 기능
# 2. FAQ CSV 조건부 로딩
# 3. session_state 기반 대화 유지
# 4. 최근 6턴만 모델에 전달 (토큰 최적화)
# 5. CSV 로그 자동 저장 및 다운로드
# 6. 에러 처리 (429 포함)
# 7. 대화 초기화 버튼
# ------------------------------------------------------------

import os
import csv
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

# ------------------------------------------------------------
# Streamlit 기본 설정
# ------------------------------------------------------------
st.set_page_config(
    page_title="쇼핑몰 고객 응대 챗봇",
    page_icon="🛍️",
    layout="wide"
)

st.title("🛍️ 쇼핑몰 고객 응대 AI 챗봇")
st.caption("Gemini API + Streamlit 기반 고객 상담 시스템")

# ------------------------------------------------------------
# 모델 목록
# ------------------------------------------------------------
MODEL_LIST = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash"
]

# ------------------------------------------------------------
# 사이드바 UI
# ------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 설정")

    selected_model = st.selectbox(
        "Gemini 모델 선택",
        MODEL_LIST,
        index=0
    )

    st.markdown(f"**현재 모델:** `{selected_model}`")

    # --------------------------------------------------------
    # API KEY 처리
    # 우선순위:
    # 1. st.secrets["GEMINI_API_KEY"]
    # 2. 사용자가 직접 입력
    # --------------------------------------------------------
    api_key = ""

    try:
        api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass

    if not api_key:
        api_key = st.text_input(
            "Gemini API Key 입력",
            type="password",
            help="secrets.toml이 없을 경우 직접 입력"
        )

    # --------------------------------------------------------
    # 대화 초기화 버튼
    # --------------------------------------------------------
    if st.button("🧹 대화 초기화"):
        st.session_state.messages = []
        st.rerun()

# ------------------------------------------------------------
# 세션 상태 초기화
# ------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

# ------------------------------------------------------------
# FAQ CSV 로딩
# ------------------------------------------------------------
faq_markdown = ""
faq_loaded = False

faq_path = Path("faq_data.csv")

if faq_path.exists():
    try:
        faq_df = pd.read_csv(faq_path)

        # 데이터프레임을 마크다운 테이블로 변환
        faq_markdown = faq_df.to_markdown(index=False)

        faq_loaded = True

    except Exception as e:
        st.warning(f"FAQ CSV 로딩 실패: {e}")

# ------------------------------------------------------------
# 시스템 프롬프트 생성
# ------------------------------------------------------------
system_prompt = """
당신은 쇼핑몰의 전문 고객 상담사입니다.
사용자의 불편/불만에 대해 정중하고 공감 어린 말투로 응답하세요.

사용자의 불편 사항을 구체적으로 수집하세요:
- 무엇이 문제인지
- 언제 발생했는지
- 어디서 발생했는지
- 어떻게 발생했는지

또한 수집된 내용을 사내 고객 응대 담당자에게 전달할 예정이라고 안내하세요.

대화의 마지막 단계에서는 담당자가 확인 후 회신할 수 있도록
사용자의 이메일 주소를 요청하세요.

만약 사용자가 연락처 제공을 거부하면:
"죄송하지만, 연락처 정보를 받지 못하여 담당자의 검토 내용을 직접 안내해 드리기 어렵습니다."
라고 정중히 마무리하세요.
"""

# ------------------------------------------------------------
# CSV 데이터가 존재할 경우에만 추가 지침 포함
# ------------------------------------------------------------
if faq_loaded:
    system_prompt += f"""

답변을 할 때는 제공된 [CSV 참조 데이터]를 우선적으로 확인하여 안내하세요.

데이터에 없는 내용이라면 임의로 지어내지 말고:
"담당 부서 확인 후 안내해 드리겠습니다"
라고 답변하세요.

[CSV 참조 데이터]
{faq_markdown}
"""

# ------------------------------------------------------------
# API KEY 체크
# ------------------------------------------------------------
if not api_key:
    st.info("Gemini API Key를 입력해 주세요.")
    st.stop()

# ------------------------------------------------------------
# Gemini Client 생성
# ------------------------------------------------------------
client = genai.Client(api_key=api_key)

# ------------------------------------------------------------
# 기존 대화 UI 표시
# ------------------------------------------------------------
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ------------------------------------------------------------
# CSV 로그 저장 함수
# ------------------------------------------------------------
LOG_FILE = "chat_log.csv"


def save_chat_log(role, content):
    """
    대화 내용을 CSV 파일로 저장하는 함수
    """

    file_exists = os.path.exists(LOG_FILE)

    with open(LOG_FILE, mode="a", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)

        # 최초 생성 시 헤더 작성
        if not file_exists:
            writer.writerow(["timestamp", "role", "content"])

        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            role,
            content
        ])


# ------------------------------------------------------------
# 사용자 입력
# ------------------------------------------------------------
user_input = st.chat_input("불편하신 내용을 입력해 주세요.")

if user_input:

    # --------------------------------------------------------
    # 사용자 메시지 저장
    # --------------------------------------------------------
    st.session_state.messages.append({
        "role": "user",
        "content": user_input
    })

    save_chat_log("user", user_input)

    # --------------------------------------------------------
    # 사용자 메시지 UI 출력
    # --------------------------------------------------------
    with st.chat_message("user"):
        st.markdown(user_input)

    # --------------------------------------------------------
    # 최근 6턴만 유지
    # user-model 왕복 기준 6턴 = 최대 12개 메시지
    # --------------------------------------------------------
    recent_messages = st.session_state.messages[-12:]

    # --------------------------------------------------------
    # Gemini API용 contents 구성
    # --------------------------------------------------------
    contents = []

    for msg in recent_messages:

        role = "user"

        # Gemini에서는 assistant 대신 model 사용
        if msg["role"] == "assistant":
            role = "model"

        contents.append(
            types.Content(
                role=role,
                parts=[types.Part(text=msg["content"])]
            )
        )

    # --------------------------------------------------------
    # 모델 응답 생성
    # --------------------------------------------------------
    with st.chat_message("assistant"):

        try:
            response = client.models.generate_content(
                model=selected_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.5
                )
            )

            bot_reply = response.text

            st.markdown(bot_reply)

            # 세션 저장
            st.session_state.messages.append({
                "role": "assistant",
                "content": bot_reply
            })

            # 로그 저장
            save_chat_log("assistant", bot_reply)

        except Exception as e:

            error_text = str(e)

            # ------------------------------------------------
            # 429 / ResourceExhausted 에러 처리
            # ------------------------------------------------
            if "429" in error_text or "ResourceExhausted" in error_text:
                st.error(
                    "현재 사용량이 많아 응답이 지연되고 있습니다. "
                    "1분 뒤에 다시 시도해 주세요."
                )

            else:
                st.error(f"오류가 발생했습니다: {error_text}")

# ------------------------------------------------------------
# 다운로드 버튼
# ------------------------------------------------------------
st.divider()

st.subheader("📥 대화 로그 다운로드")

if os.path.exists(LOG_FILE):

    with open(LOG_FILE, "rb") as f:
        st.download_button(
            label="CSV 로그 다운로드",
            data=f,
            file_name="chat_log.csv",
            mime="text/csv"
        )

else:
    st.caption("아직 저장된 로그가 없습니다.")
