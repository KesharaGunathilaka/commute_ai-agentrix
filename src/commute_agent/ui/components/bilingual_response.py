"""Streamlit component: side-by-side bilingual response display."""

from __future__ import annotations

import streamlit as st

_LANGUAGE_LABELS = {
    "si": "සිංහල",
    "ta": "தமிழ்",
    "en": "English",
}

_FLAG_ICONS = {
    "si": "🇱🇰",
    "ta": "🇱🇰",
    "en": "🇬🇧",
}


def render_bilingual_response(
    native_response: str,
    english_response: str,
    language: str = "en",
) -> None:
    """
    Render native and English responses permanently side by side — never hidden.

    A judge who can't read Sinhala or Tamil still sees both columns and
    understands the multilingual capability at a glance.
    """
    if not native_response and not english_response:
        return

    lang_label = _LANGUAGE_LABELS.get(language, language.upper())
    flag = _FLAG_ICONS.get(language, "🌐")

    st.markdown("### 💬 Response")

    if language == "en":
        # No need for two columns if English was detected
        st.info(english_response, icon="💬")
        return

    col_native, col_english = st.columns(2)

    with col_native:
        st.markdown(f"**{flag} {lang_label}**")
        st.info(native_response)

    with col_english:
        st.markdown("**🇬🇧 English**")
        st.info(english_response)
