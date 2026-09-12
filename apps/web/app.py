from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.getenv("COPILOT_API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="中葡经贸合规智能体", page_icon="🌐", layout="wide")
st.title("中葡经贸合规智能体")
st.caption("跨语言检索 · 句级溯源 · 证据门控 · 有依据才回答")

with st.sidebar:
    language = st.selectbox("回答语言 / Idioma", [("中文", "zh"), ("Português", "pt")], format_func=lambda x: x[0])[1]
    selected = st.multiselect("法域 / Jurisdição", [("巴西", "BR"), ("葡萄牙", "PT")], format_func=lambda x: x[0])
    st.info("本系统用于资料检索，不构成法律、税务或投资意见。")
    try:
        health = httpx.get(f"{API_URL}/health", timeout=3).json()
        st.metric("已索引片段", health["index"]["chunks"])
    except (httpx.HTTPError, KeyError, ValueError):
        st.warning("API 尚未连接")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

query = st.chat_input("请输入关于巴西或葡萄牙投资、税务、劳动用工的问题")
if query:
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)
    with st.chat_message("assistant"), st.spinner("正在构建上下文并核验证据…"):
            payload = {
                "query": query,
                "answer_language": language,
                "jurisdictions": [value for _, value in selected],
                "conversation": st.session_state.messages[-9:-1],
            }
            try:
                response = httpx.post(f"{API_URL}/v1/query", json=payload, timeout=60)
                response.raise_for_status()
                data = response.json()
                badge = f"**{data['status']} · 证据{data['evidence_level']}**"
                st.markdown(badge)
                st.markdown(data["answer"])
                for citation in data["citations"]:
                    location = f"第 {citation['page']} 页" if citation.get("page") else citation.get("section") or "章节未标注"
                    with st.expander(f"[{citation['id']}] {citation['title']} · {location}"):
                        st.caption(f"{citation['publisher']} · {citation['source_url']}")
                        st.write(citation["quote"])
                st.caption(data["disclaimer"])
                rendered = f"{badge}\n\n{data['answer']}"
            except httpx.HTTPStatusError as exc:
                rendered = f"请求失败：{exc.response.text}"
                st.error(rendered)
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                rendered = f"无法连接 API：{type(exc).__name__}"
                st.error(rendered)
    st.session_state.messages.append({"role": "assistant", "content": rendered})
