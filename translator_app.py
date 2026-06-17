"""
루비알엔 번체 번역 대시보드 — Streamlit
실행: streamlit run translator_app.py
"""
import os, sys, json, subprocess, re
import pandas as pd
from pathlib import Path
import streamlit as st

BASE        = Path(__file__).parent
MEMORY_FILE = BASE / "product_memory.json"
ANAL_DIR    = BASE / "data" / "analysis"

st.set_page_config(page_title="메라블 번체 번역", page_icon="🈳", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 1rem; }
.stTextArea textarea { font-size: 15px; line-height: 1.7; }
.result-box {
    background: #f8f9fa; border-left: 4px solid #c9184a;
    border-radius: 8px; padding: 1.4rem 1.6rem;
    font-size: 16px; line-height: 2; white-space: pre-wrap; min-height: 120px;
}
.ok-box   { background:#d1e7dd; border-left:4px solid #198754; border-radius:6px; padding:.6rem 1rem; font-size:13px; margin-top:.4rem; }
.warn-box { background:#fff3cd; border-left:4px solid #ffc107; border-radius:6px; padding:.6rem 1rem; font-size:13px; margin-top:.4rem; }
.kw-row   { display:flex; align-items:center; gap:8px; margin:4px 0; }
.kw-chip  { display:inline-block; background:#d1e7dd; color:#0a3622; border-radius:20px; padding:3px 14px; font-size:13px; }
.kw-chip.miss { background:#f8d7da; color:#58151c; }
table.tr-table { width:100%; border-collapse:collapse; font-size:15px; }
table.tr-table th { background:#c9184a; color:white; padding:10px 14px; text-align:left; }
table.tr-table td { padding:9px 14px; border-bottom:1px solid #e9ecef; vertical-align:top; line-height:1.7; }
table.tr-table tr:nth-child(even) td { background:#f8f9fa; }
</style>
""", unsafe_allow_html=True)

PRODUCT_LABELS = {
    "루비알엔앰플":   "루비알엔 앰플 클렌저",
    "루비알엔크림":   "루비알엔 피코샷 크림",
    "루비알엔세트":   "루비알엔 세트 (앰플+크림)",
    "포어시그널앰플": "포어시그널 앰플",
    "포어시그널크림": "포어시그널 크림",
}

TONE_GUIDE = {
    "MZ·숏폼":  "인플루언서 구어체 최대. 竟然/真的/超/太/哇 등 감탄사 적극 사용. 흥분되고 친근한 톤.",
    "기본":      "자연스러운 구어체. 적당한 감탄 표현. 읽기 편하고 공감되는 톤.",
    "전문가·차분": "구어체이되 감탄사 자제. 신뢰감 있고 부드러운 톤.",
}
LENGTH_GUIDE = {
    "의역":    "원문의 핵심 메시지와 감정을 살리되 중화권 인플루언서가 자연스럽게 말하는 방식으로 재구성. 원문과 비슷한 길이 유지.",
    "짧게 압축": "핵심 메시지만 뽑아서 임팩트 있게 압축. 원문의 50~60% 분량으로 줄임. 숏폼 자막·광고 카피 스타일.",
}

# ── 데이터 로드 ───────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_memory():
    if not MEMORY_FILE.exists():
        return {"products": {}, "global_settings": {}}
    return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))

@st.cache_data(show_spinner=False)
def load_style_examples():
    if not ANAL_DIR.exists(): return []
    bad  = ["蛋斑","解麵","截面","安平","衣美","立珠蘭","辣黃","設量"]
    good = ["竟然","真的","一開始","完全","洗臉","皮膚","缺貨","兩週","比","不用","就像","在家","素顏","光澤"]
    phrases, seen = [], set()
    for f in sorted(ANAL_DIR.glob("*.json"))[:60]:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            for ph in (d.get("key_phrases") or []):
                if not ph or len(ph)<8 or len(ph)>50: continue
                if any(b in ph for b in bad): continue
                if any(g in ph for g in good) and ph not in seen:
                    seen.add(ph); phrases.append(ph)
        except: pass
    return phrases[:20]

def save_memory(mem):
    MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")
    st.cache_data.clear()

def get_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY","")
    if not key:
        r = subprocess.run(["powershell","-Command",
            '[System.Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY","User")'],
            capture_output=True, text=True)
        key = r.stdout.strip()
    return key

# ── 시스템 프롬프트 ───────────────────────────────────────────────────────────
def build_system_prompt(product_key, region, length_mode, tone_level, mem, style_examples):
    p   = mem["products"][product_key]
    gs  = mem.get("global_settings", {})
    rv  = gs.get("region_variants", {}).get(region, {})
    inf = gs.get("influencer_style", {})
    samples   = "\n".join(f"  KO: {s['ko']}\n  ZH: {s['zh']}" for s in p.get("sample_phrases",[])[-6:])
    claims    = "\n".join(f"  - {c}" for c in p.get("key_claims",[]))
    required  = "、".join(p.get("required_keywords",[]))
    mechanism = p.get("mechanism","")
    style_block = "\n".join(f"  · {e}" for e in style_examples[:8]) if style_examples else "  (없음)"

    return f"""당신은 K-뷰티 브랜드 「루비알엔(Ruby PDRN)」의 {region} 마케팅 번역 전문가입니다.
실제 중화권 인플루언서 영상 79편 분석 데이터를 바탕으로 번역합니다.

【번역 제품】
- 한국어명: {p.get('name_ko')} | 번체명: {p.get('name_zh')}
- 타겟: {p.get('target')}

【제품 메커니즘】
{mechanism}

【제품 핵심 주장】
{claims}

【번역 방식】 {LENGTH_GUIDE[length_mode]}
【톤 강도】 {TONE_GUIDE[tone_level]}

【인플루언서 실제 표현 스타일】
감탄·놀람: {' / '.join(inf.get('surprise_expressions',[]))}
반신반의: {' / '.join(inf.get('skeptic_openers',[]))}
결과 묘사: {' / '.join(inf.get('result_expressions',[]))}
비교 표현: {' / '.join(inf.get('comparison_expressions',[]))}
사회적 증명: {' / '.join(inf.get('social_proof',[]))}

【실제 영상 핵심 문장】
{style_block}

【번역 규칙】
1. 반드시 번체(繁體中文) — 간체 혼용 절대 금지
2. 지역: {region} — 약국={rv.get('pharmacy','藥局')}, 피부과={rv.get('dermatologist','皮膚科診所')}, 레이저={rv.get('laser','雷射')}
3. 필수 포함 키워드: {required}
4. 제품명: 「{p.get('name_zh')}」또는 「Ruby PDRN」으로 통일
5. 딱딱한 광고 문체 금지

【최종 확정 레퍼런스 스크립트 (가장 중요 — 이 스타일을 최우선 참고)】
{get_reference_block(product_key, mem) or '  (아직 없음 — 레퍼런스 학습 탭에서 추가하세요)'}

【승인된 번역 샘플 (문장 단위)】
{samples if samples else '  (없음)'}"""

# ── 번역 함수 (전체 텍스트) ───────────────────────────────────────────────────
def translate_full(text, product_key, region, length_mode, tone_level, mem, style_examples):
    api_key = get_api_key()
    if not api_key: return None, "API 키 없음"
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=2048,
            system=build_system_prompt(product_key, region, length_mode, tone_level, mem, style_examples),
            messages=[{"role":"user","content":f"다음을 번체 중국어로 번역하세요:\n\n{text}"}]
        )
        return resp.content[0].text.strip(), None
    except Exception as e:
        return None, str(e)

# ── 번역 함수 (표 형식 — 줄별 JSON) ─────────────────────────────────────────
def translate_table(lines, product_key, region, length_mode, tone_level, mem, style_examples):
    api_key = get_api_key()
    if not api_key: return None, "API 키 없음"
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        system = build_system_prompt(product_key, region, length_mode, tone_level, mem, style_examples)
        numbered = "\n".join(f"{i+1}. {l}" for i, l in enumerate(lines))
        user_msg = (
            f"아래 {len(lines)}개 항목을 각각 번체 중국어로 번역하세요.\n"
            f"반드시 아래 JSON 배열 형식으로만 반환하세요. 설명 없이 JSON만:\n"
            f'[{{"ko":"원문1","zh":"번역1"}}, {{"ko":"원문2","zh":"번역2"}}, ...]\n\n'
            f"{numbered}"
        )
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=3000,
            system=system,
            messages=[{"role":"user","content":user_msg}]
        )
        raw = resp.content[0].text.strip()
        m = re.search(r'\[[\s\S]*\]', raw)
        if m:
            pairs = json.loads(m.group())
            return pairs, None
        return None, "JSON 파싱 실패"
    except Exception as e:
        return None, str(e)

def get_reference_block(product_key, mem, max_refs=2, max_chars=600):
    """최신 레퍼런스 스크립트를 시스템 프롬프트용 텍스트로 변환"""
    refs = mem["products"].get(product_key, {}).get("reference_scripts", [])
    if not refs:
        return ""
    block = ""
    for ref in reversed(refs[-max_refs:]):
        label = ref.get("label", "레퍼런스")
        ko    = ref.get("ko", "")[:max_chars]
        zh    = ref.get("zh", "")[:max_chars]
        block += f"\n[{label}]\nKO: {ko}\nZH: {zh}\n"
    return block.strip()

def quality_check(text, product_key, mem):
    p = mem["products"][product_key]
    missing = [kw for kw in p.get("required_keywords",[]) if kw not in text]
    simp = ["简","发","统","补","该","处","爱","专","产","时间"]
    found_simp = [c for c in simp if c in text]
    return missing, found_simp

def pairs_to_notion(pairs):
    """노션 붙여넣기용 마크다운 테이블"""
    lines = ["| META | 번역 |", "|------|------|"]
    for p in pairs:
        ko = p.get("ko","").replace("|","｜").replace("\n"," ")
        zh = p.get("zh","").replace("|","｜").replace("\n","<br>")
        lines.append(f"| {ko} | {zh} |")
    return "\n".join(lines)

def pairs_to_html(pairs):
    rows = ""
    for p in pairs:
        ko = p.get("ko","").replace("<","&lt;")
        zh = p.get("zh","").replace("\n","<br>").replace("<br><br>","<br>")
        rows += f"<tr><td>{ko}</td><td>{zh}</td></tr>"
    return f"""<table class='tr-table'>
<thead><tr><th>META</th><th>번역</th></tr></thead>
<tbody>{rows}</tbody></table>"""

# ════════════════════════════════════════════════════════════════════════════════
# UI
# ════════════════════════════════════════════════════════════════════════════════
mem            = load_memory()
style_examples = load_style_examples()
products       = mem.get("products", {})

st.title("🈳 메라블 번체 번역 대시보드")
st.caption("영상 기획안 또는 스크립트 → 번체(Traditional Chinese) 번역")
st.divider()

tab_trans, tab_ref, tab_product, tab_video = st.tabs(["번역", "레퍼런스 학습", "제품 설정", "🎬 영상→한국어"])

# ════════════════════════════════════════════════════════════════════════════════
# 탭 1: 번역
# ════════════════════════════════════════════════════════════════════════════════
with tab_trans:
    # ── 컨트롤 바 ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])
    with c1:
        available = [k for k in PRODUCT_LABELS if k in products]
        product_key = st.selectbox("제품", options=available,
                                   format_func=lambda k: PRODUCT_LABELS.get(k,k))
    with c2:
        gs = mem.get("global_settings",{})
        regions = list(gs.get("region_variants",{"대만":{},"홍콩":{}}).keys())
        region = st.selectbox("지역", options=regions,
                              help="대만(藥局·雷射) vs 홍콩(藥房·鐳射)")
    with c3:
        length_mode = st.selectbox("번역 방식", ["의역","짧게 압축"],
                                   help="의역: 원문 길이 유지\n짧게 압축: 핵심만 50~60%로 줄임")
    with c4:
        tone_level = st.selectbox("톤 강도", ["기본","MZ·숏폼","전문가·차분"],
                                  help="MZ·숏폼: 감탄사 풀가동, 인플루언서 느낌\n기본: 자연스러운 구어체\n전문가·차분: 신뢰감 있고 차분한 톤")
    with c5:
        out_format = st.selectbox("출력 형식", ["표 형식","전체 번역"],
                                  help="표 형식: META|번역 테이블 (노션 복붙 가능)\n전체 번역: 텍스트 그대로")

    p_cur = products.get(product_key,{})
    with st.expander(f"제품 정보 — {PRODUCT_LABELS.get(product_key,'')}", expanded=False):
        col_m, col_k = st.columns(2)
        with col_m:
            st.caption("**메커니즘**")
            st.write(p_cur.get("mechanism","(미입력)"))
        with col_k:
            st.caption("**필수 키워드**")
            chips = "".join(f"<span class='kw-chip'>{kw}</span> " for kw in p_cur.get("required_keywords",[]))
            st.markdown(chips or "(없음)", unsafe_allow_html=True)

    st.divider()

    # ── 입력 / 출력 ───────────────────────────────────────────────────────────
    col_in, col_out = st.columns(2, gap="large")

    with col_in:
        st.subheader("한국어 원문")
        if out_format == "표 형식":
            st.caption("줄바꿈(Enter) 기준으로 각 행이 테이블 한 줄이 됩니다.")
        input_text = st.text_area(
            label="input", height=380, label_visibility="collapsed",
            placeholder=(
                "영상 기획안 또는 스크립트를 입력하세요.\n\n"
                "예)\n본연의 내 피부 자체가 좋으려면\n"
                "채우는 것보다 비우는 게 더 중요하잖아요\n"
                "제가 단독사용만으로\n"
                "흙톤피부 심폐소생해주는"
            )
        )
        st.caption(f"{len(input_text)}자")
        btn = st.button("번역하기 →", type="primary", use_container_width=True,
                        disabled=(len(input_text.strip())==0))

    with col_out:
        st.subheader(f"번체 번역 — {region}")

        for key in ["tr_pairs","tr_full","tr_input","tr_product"]:
            if key not in st.session_state:
                st.session_state[key] = None if key in ["tr_pairs","tr_full"] else ""
        if "tr_version" not in st.session_state:
            st.session_state.tr_version = 0

        if btn and input_text.strip():
            if out_format == "표 형식":
                lines = [l.strip() for l in input_text.strip().split("\n") if l.strip()]
                with st.spinner(f"표 형식 번역 중 ({len(lines)}행)..."):
                    pairs, err = translate_table(lines, product_key, region, length_mode, tone_level, mem, style_examples)
                if err:
                    st.error(f"오류: {err}")
                else:
                    st.session_state.tr_pairs   = pairs
                    st.session_state.tr_full    = None
                    st.session_state.tr_input   = input_text.strip()
                    st.session_state.tr_product = product_key
                    st.session_state.tr_version += 1
            else:
                with st.spinner("번역 중..."):
                    result, err = translate_full(input_text.strip(), product_key, region, length_mode, tone_level, mem, style_examples)
                if err:
                    st.error(f"오류: {err}")
                else:
                    st.session_state.tr_full    = result
                    st.session_state.tr_pairs   = None
                    st.session_state.tr_input   = input_text.strip()
                    st.session_state.tr_product = product_key

        # ── 표 형식 결과 ──────────────────────────────────────────────────────
        if st.session_state.tr_pairs:
            pairs = st.session_state.tr_pairs
            used_pk = st.session_state.tr_product

            # 편집 가능한 테이블 (ZH 칸 직접 수정 가능)
            df = pd.DataFrame({
                "META": [p.get("ko","") for p in pairs],
                "번역": [p.get("zh","") for p in pairs],
            })
            edited = st.data_editor(
                df,
                column_config={
                    "META": st.column_config.TextColumn("META", disabled=True, width="medium"),
                    "번역": st.column_config.TextColumn("번역", width="large"),
                },
                hide_index=True,
                use_container_width=True,
                num_rows="fixed",
                key=f"et_{st.session_state.tr_version}",
            )
            edited_pairs = [{"ko": r["META"], "zh": r["번역"]} for _, r in edited.iterrows()]

            # 품질 체크
            all_zh = " ".join(p["zh"] for p in edited_pairs)
            if used_pk in products:
                missing, found_simp = quality_check(all_zh, used_pk, mem)
                if not missing and not found_simp:
                    st.markdown("<div class='ok-box'>✅ 품질 통과</div>", unsafe_allow_html=True)
                else:
                    msg = ""
                    if missing: msg += f"⚠️ 키워드 누락: {'、'.join(missing)}<br>"
                    if found_simp: msg += f"🔤 간체 의심: {'、'.join(found_simp)}"
                    st.markdown(f"<div class='warn-box'>{msg}</div>", unsafe_allow_html=True)

            st.markdown("---")

            # 노션 복사 버튼
            notion_md = pairs_to_notion(edited_pairs)
            notion_json = json.dumps(notion_md)
            st.components.v1.html(f"""
<script>var _nt = {notion_json};</script>
<button id="nb" onclick="navigator.clipboard.writeText(_nt).then(function(){{
  document.getElementById('nb').textContent='✅ 복사 완료!';
  setTimeout(function(){{document.getElementById('nb').textContent='📋 노션 복사';}},1500);
}})" style="background:#c9184a;color:white;border:none;border-radius:8px;
padding:10px 0;cursor:pointer;font-size:15px;width:100%;font-weight:600;">
📋 노션 복사
</button>
""", height=55)

            col_s, col_c = st.columns(2)
            with col_s:
                if st.button("✅ 메모리 저장", use_container_width=True):
                    m2 = load_memory()
                    for p in edited_pairs:
                        if p.get("ko") and p.get("zh"):
                            m2["products"][used_pk].setdefault("sample_phrases",[]).append(
                                {"ko": p["ko"], "zh": p["zh"]}
                            )
                    save_memory(m2)
                    st.success("저장 완료")
            with col_c:
                if st.button("🗑 초기화", use_container_width=True):
                    st.session_state.tr_pairs = None
                    st.rerun()

        # ── 전체 번역 결과 ────────────────────────────────────────────────────
        elif st.session_state.tr_full:
            result  = st.session_state.tr_full
            used_pk = st.session_state.tr_product

            st.markdown(f"<div class='result-box'>{result}</div>", unsafe_allow_html=True)
            st.caption(f"{len(result)}자")

            if used_pk in products:
                missing, found_simp = quality_check(result, used_pk, mem)
                if not missing and not found_simp:
                    st.markdown("<div class='ok-box'>✅ 품질 통과</div>", unsafe_allow_html=True)
                else:
                    msg = ""
                    if missing: msg += f"⚠️ 키워드 누락: {'、'.join(missing)}<br>"
                    if found_simp: msg += f"🔤 간체 의심: {'、'.join(found_simp)}"
                    st.markdown(f"<div class='warn-box'>{msg}</div>", unsafe_allow_html=True)

            st.markdown("---")
            st.text_area("복사용", value=result, height=150, key="full_copy")

            col_s, col_c = st.columns(2)
            with col_s:
                if st.button("✅ 메모리 저장", use_container_width=True):
                    m2 = load_memory()
                    m2["products"][used_pk].setdefault("sample_phrases",[]).append(
                        {"ko": st.session_state.tr_input, "zh": result}
                    )
                    save_memory(m2)
                    st.success("저장 완료")
            with col_c:
                if st.button("🗑 초기화", use_container_width=True):
                    st.session_state.tr_full = None
                    st.rerun()
        else:
            st.markdown("<div class='result-box' style='color:#ccc;'>번역 결과가 여기에 표시됩니다.</div>",
                        unsafe_allow_html=True)

    # 샘플 보기
    samples = p_cur.get("sample_phrases",[])
    with st.expander(f"저장된 번역 샘플 ({len(samples)}건)", expanded=False):
        if not samples:
            st.caption("아직 없음.")
        else:
            for s in reversed(samples[-10:]):
                a, b = st.columns(2)
                with a: st.markdown(f"**KO** {s['ko']}")
                with b: st.markdown(f"**ZH** {s['zh']}")
                st.divider()

# ════════════════════════════════════════════════════════════════════════════════
# 탭 2: 레퍼런스 학습
# ════════════════════════════════════════════════════════════════════════════════
with tab_ref:
    st.subheader("레퍼런스 학습")
    st.caption("최종 확정된 스크립트를 등록하면 이후 번역에 스타일이 자동 반영됩니다. 많이 쌓을수록 번역이 자연스러워집니다.")

    ref_available = [k for k in PRODUCT_LABELS if k in products]
    ref_product = st.selectbox("제품 선택", options=ref_available,
                                format_func=lambda k: PRODUCT_LABELS.get(k,k),
                                key="ref_product_select")

    ref_data = products.get(ref_product, {})
    existing_refs = ref_data.get("reference_scripts", [])

    # ── 새 레퍼런스 추가 ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 새 레퍼런스 추가")

    ref_label = st.text_input("레퍼런스 이름", placeholder="예) 앰플클렌저_기미스토리_김건_0615",
                               key="ref_label_input")

    rc1, rc2 = st.columns(2, gap="large")
    with rc1:
        st.caption("한국어 원문 (최종 확정본)")
        ref_ko = st.text_area("ref_ko", height=300, label_visibility="collapsed",
                               placeholder="최종 확정된 한국어 스크립트를 붙여넣으세요.",
                               key="ref_ko_input")
    with rc2:
        st.caption("번체 번역 (최종 확정본)")
        ref_zh = st.text_area("ref_zh", height=300, label_visibility="collapsed",
                               placeholder="최종 확정된 번체 번역을 붙여넣으세요.",
                               key="ref_zh_input")

    if st.button("➕ 레퍼런스 저장", type="primary",
                 disabled=(not ref_ko.strip() or not ref_zh.strip())):
        import time as _time
        m2 = load_memory()
        m2["products"][ref_product].setdefault("reference_scripts", []).append({
            "label":    ref_label.strip() or f"레퍼런스_{len(existing_refs)+1}",
            "ko":       ref_ko.strip(),
            "zh":       ref_zh.strip(),
            "added_at": _time.strftime("%Y-%m-%d"),
        })
        save_memory(m2)
        st.success(f"✅ 레퍼런스 저장 완료 — 번역에 즉시 반영됩니다.")
        st.rerun()

    # ── 기존 레퍼런스 목록 ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(f"#### 등록된 레퍼런스 — {PRODUCT_LABELS.get(ref_product,'')} ({len(existing_refs)}건)")
    st.caption("최신 2개가 번역 시 자동 참고됩니다. 많이 쌓일수록 스타일이 정교해집니다.")

    if not existing_refs:
        st.info("아직 등록된 레퍼런스가 없습니다. 위에서 추가해주세요.")
    else:
        for i, ref in enumerate(reversed(existing_refs)):
            real_idx = len(existing_refs) - 1 - i
            with st.expander(f"{'⭐ ' if i < 2 else ''}[{ref.get('added_at','')}] {ref.get('label','레퍼런스')}   {'← 번역 시 참고 중' if i < 2 else ''}", expanded=(i==0)):
                ec1, ec2 = st.columns(2, gap="medium")
                with ec1:
                    st.caption("한국어 원문")
                    st.text(ref.get("ko","")[:500] + ("..." if len(ref.get("ko","")) > 500 else ""))
                with ec2:
                    st.caption("번체 번역")
                    st.text(ref.get("zh","")[:500] + ("..." if len(ref.get("zh","")) > 500 else ""))
                if st.button("🗑 삭제", key=f"del_ref_{ref_product}_{real_idx}"):
                    m2 = load_memory()
                    m2["products"][ref_product]["reference_scripts"].pop(real_idx)
                    save_memory(m2)
                    st.rerun()

# ════════════════════════════════════════════════════════════════════════════════
# 탭 3: 제품 설정
# ════════════════════════════════════════════════════════════════════════════════
with tab_product:
    st.subheader("제품 설정")
    mem = load_memory()
    products = mem.get("products", {})

    available2 = [k for k in PRODUCT_LABELS if k in products]
    edit_key = st.selectbox("수정할 제품", options=available2,
                             format_func=lambda k: PRODUCT_LABELS.get(k,k),
                             key="edit_product_select")
    ep = products.get(edit_key, {})

    # 키워드 session_state 초기화 (제품 변경 시 리셋)
    if st.session_state.get("kw_product") != edit_key:
        st.session_state.kw_list    = list(ep.get("required_keywords", []))
        st.session_state.kw_product = edit_key

    col_a, col_b = st.columns(2, gap="large")

    with col_a:
        st.markdown("#### 메커니즘")
        st.caption("제품이 피부에서 어떻게 작동하는지. 번역 시 이 원리를 자연스럽게 녹입니다.")
        new_mechanism = st.text_area("mechanism", value=ep.get("mechanism",""),
                                     height=180, label_visibility="collapsed",
                                     placeholder="예) Ruby PDRN 성분이 피부 기저층까지 침투해 멜라닌 생성 억제...")

        st.markdown("#### 제품명 (번체)")
        new_name_zh = st.text_input("번체명", value=ep.get("name_zh",""), label_visibility="collapsed")

        st.markdown("#### 타겟")
        new_target = st.text_input("타겟", value=ep.get("target",""), label_visibility="collapsed")

        st.markdown("#### 어투 가이드")
        new_tone_guide = st.text_area("tone_guide", value=ep.get("tone_guidelines",""),
                                      height=90, label_visibility="collapsed")

    with col_b:
        st.markdown("#### 필수 키워드 데이터베이스")
        st.caption("번역 결과에 반드시 포함되어야 할 단어. 품질 체크에도 사용됩니다.")

        # 키워드 목록 + 삭제 버튼
        to_delete = None
        for i, kw in enumerate(st.session_state.kw_list):
            kc, dc = st.columns([6, 1])
            with kc:
                st.markdown(f"<span class='kw-chip'>　{kw}　</span>", unsafe_allow_html=True)
            with dc:
                if st.button("✕", key=f"delkw_{edit_key}_{i}_{kw}"):
                    to_delete = i

        if to_delete is not None:
            st.session_state.kw_list.pop(to_delete)
            st.rerun()

        # 새 키워드 추가
        st.markdown("")
        add_c, btn_c = st.columns([4, 1])
        with add_c:
            new_kw_input = st.text_input("키워드 추가", placeholder="예) 潔面",
                                         label_visibility="collapsed", key=f"newkw_{edit_key}")
        with btn_c:
            if st.button("＋ 추가", key=f"addkw_{edit_key}"):
                nk = new_kw_input.strip()
                if nk and nk not in st.session_state.kw_list:
                    st.session_state.kw_list.append(nk)
                    st.rerun()

        st.caption(f"현재 {len(st.session_state.kw_list)}개")

    st.divider()
    if st.button("💾 저장", type="primary"):
        m2 = load_memory()
        m2["products"][edit_key]["mechanism"]        = new_mechanism
        m2["products"][edit_key]["name_zh"]          = new_name_zh
        m2["products"][edit_key]["target"]           = new_target
        m2["products"][edit_key]["required_keywords"]= list(st.session_state.kw_list)
        m2["products"][edit_key]["tone_guidelines"]  = new_tone_guide
        save_memory(m2)
        st.session_state.kw_list    = list(st.session_state.kw_list)
        st.session_state.kw_product = edit_key
        st.success(f"✅ {PRODUCT_LABELS.get(edit_key,'')} 저장 완료")
        st.rerun()

# ════════════════════════════════════════════════════════════════════════════════
# 탭 4: 영상 → 한국어 번역
# ════════════════════════════════════════════════════════════════════════════════
with tab_video:
    st.subheader("🎬 영상 → 한국어 번역")
    st.caption("중국어 영상의 자막(유튜브) 또는 음성(파일 업로드)을 한국어로 번역합니다.")

    for k in ["v_zh_text", "v_ko_text"]:
        if k not in st.session_state:
            st.session_state[k] = ""

    v_method = st.radio("입력 방식", ["📝 텍스트 직접 입력", "🔗 유튜브 링크", "📁 파일 업로드"], horizontal=True, key="v_method")

    if v_method == "🔗 유튜브 링크":
        v_url = st.text_input("유튜브 URL", placeholder="https://www.youtube.com/watch?v=...", key="v_url_input")
        if st.button("자막 가져오기", key="v_fetch_btn") and v_url.strip():
            try:
                from youtube_transcript_api import YouTubeTranscriptApi
                vid_match = re.search(r"(?:v=|youtu\.be/)([^&\n?#]+)", v_url)
                if not vid_match:
                    st.error("유효한 유튜브 URL이 아닙니다.")
                else:
                    with st.spinner("자막 가져오는 중..."):
                        try:
                            transcript = YouTubeTranscriptApi.get_transcript(
                                vid_match.group(1), languages=["zh-Hant","zh-Hans","zh"])
                        except Exception:
                            transcript = YouTubeTranscriptApi.get_transcript(vid_match.group(1))
                        st.session_state.v_zh_text = " ".join(t["text"] for t in transcript)
                    st.success(f"자막 {len(transcript)}개 가져옴")
            except Exception as e:
                st.error(f"오류: {e}")
    elif v_method == "📁 파일 업로드":
        v_file = st.file_uploader("영상 파일 업로드", type=["mp4","mov","avi","mkv","m4v"], key="v_file_upload")
        if st.button("음성 인식(STT)", key="v_stt_btn") and v_file:
            try:
                import whisper as _w, tempfile as _tf
                suffix = Path(v_file.name).suffix
                with _tf.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(v_file.read())
                    tmp_path = tmp.name
                with st.spinner("음성 인식 중 (첫 실행 시 모델 다운로드로 2~5분 소요)..."):
                    wm = _w.load_model("tiny")
                    result = wm.transcribe(tmp_path, language=None)
                    st.session_state.v_zh_text = result.get("text","").strip()
                    lang = result.get("language","?")
                os.unlink(tmp_path)
                st.success(f"STT 완료 (감지 언어: {lang})")
            except ImportError:
                st.error("openai-whisper 패키지가 없습니다. 잠시 후 다시 시도하세요.")
            except Exception as e:
                st.error(f"STT 오류: {e}")

    st.divider()
    v_col1, v_col2 = st.columns(2, gap="large")

    with v_col1:
        st.caption("중국어 원문 (수정 가능)")
        v_zh_edit = st.text_area("v_zh", value=st.session_state.v_zh_text,
                                  height=380, label_visibility="collapsed", key="v_zh_area")

    with v_col2:
        st.caption("한국어 번역 결과")
        if st.button("한국어로 번역 →", type="primary", key="v_translate_btn",
                     disabled=(not v_zh_edit.strip())):
            api_key = get_api_key()
            if api_key:
                import anthropic as _ant
                client = _ant.Anthropic(api_key=api_key)
                with st.spinner("번역 중..."):
                    resp = client.messages.create(
                        model="claude-sonnet-4-6", max_tokens=3000,
                        system=(
                            "당신은 K-뷰티 브랜드 마케팅 전문 번역가입니다.\n"
                            "중국어(번체 또는 간체) 영상 스크립트를 자연스러운 한국어로 번역합니다.\n"
                            "인플루언서의 구어체 말투와 감정을 살려서 번역하세요.\n"
                            "번역 결과만 출력하고 다른 설명은 하지 마세요."
                        ),
                        messages=[{"role":"user","content":f"다음을 한국어로 번역하세요:\n\n{v_zh_edit}"}]
                    )
                    st.session_state.v_ko_text = resp.content[0].text.strip()
            else:
                st.error("API 키 없음")

        if st.session_state.v_ko_text:
            st.text_area("v_ko", value=st.session_state.v_ko_text,
                         height=380, label_visibility="collapsed", key="v_ko_area")
