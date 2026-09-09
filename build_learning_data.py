# -*- coding: utf-8 -*-
"""
메라블_번역학습데이터.xlsx → data/learning_data.json 변환기

엑셀 시트 ②(번체 표현) · ③(번역 규칙)을 앱이 제품·톤별로 바로 쓸 수 있는
형태로 정제해 저장한다. ①(확정 번역쌍)·④(용어집)은 이미 product_memory.json에
반영돼 있으므로 제외한다.

사용법: python build_learning_data.py [엑셀경로]
"""
import json, re, sys
from pathlib import Path
import pandas as pd

BASE    = Path(__file__).parent
OUT     = BASE / "data" / "learning_data.json"
DEFAULT_XLSX = Path(r"C:\Users\MKM10046\Desktop\영상번역봇\메라블_번역학습데이터.xlsx")

# 엑셀 제품 표기 → product_memory.json 키
PRODUCT_KEY = {
    "루비알엔 앰플 클렌저": "루비알엔앰플",
    "루비알엔 피코샷 크림": "루비알엔크림",
    "루비알엔 세트":       "루비알엔세트",
    "포어시그널 앰플":     "포어시그널앰플",
    "포어시그널 크림":     "포어시그널크림",
}

HANGUL = re.compile(r"[가-힣]")
# STT 오인식으로 생긴 잘못된 표기 — translator_app.py의 기존 필터와 동일 기준
BAD_TOKENS = ["蛋斑", "解麵", "截面", "安平", "衣美", "立珠蘭", "辣黃", "設量",
              "水煮蛋", "嫩透雞", "貴於聖泰"]


def clean_expressions(df):
    """번체 표현 시트 정제: 한글 잔류·STT 오인식·너무 짧은 표현 제거"""
    rows, dropped = [], {"한글잔류": 0, "STT오인식": 0, "너무짧음": 0}
    for _, r in df.iterrows():
        text = str(r["번체 표현"]).strip()
        if not text or text == "nan":
            continue
        if HANGUL.search(text):
            dropped["한글잔류"] += 1
            continue
        if any(b in text for b in BAD_TOKENS):
            dropped["STT오인식"] += 1
            continue
        if len(text) < 4:
            dropped["너무짧음"] += 1
            continue
        rows.append({
            "video_id": str(r["영상ID"]),
            "product":  PRODUCT_KEY.get(str(r["제품"]).strip(), ""),
            "tone":     str(r["톤"]).strip(),
            "score":    int(r["점수"]),
            "text":     text,
        })
    return rows, dropped


def clean_rules(df):
    """번역 규칙 시트 정제: 중복 제거"""
    rows, seen = [], set()
    for _, r in df.iterrows():
        tip = str(r["번역 규칙 / 팁"]).strip()
        if not tip or tip == "nan" or tip in seen:
            continue
        seen.add(tip)
        rows.append({
            "video_id": str(r["영상ID"]),
            "product":  PRODUCT_KEY.get(str(r["제품"]).strip(), ""),
            "tip":      tip,
        })
    return rows


def main():
    xlsx = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_XLSX
    if not xlsx.exists():
        sys.exit(f"엑셀 파일 없음: {xlsx}")

    x = pd.ExcelFile(xlsx)
    expressions, dropped = clean_expressions(x.parse("② 번체 표현"))
    rules = clean_rules(x.parse("③ 번역 규칙"))

    data = {
        "source": xlsx.name,
        "expressions": expressions,
        "rules": rules,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"저장: {OUT}")
    print(f"  표현 {len(expressions)}건 (제외: {dropped})")
    print(f"  규칙 {len(rules)}건")
    for key in PRODUCT_KEY.values():
        e = sum(1 for r in expressions if r["product"] == key)
        u = sum(1 for r in rules if r["product"] == key)
        print(f"  - {key}: 표현 {e} / 규칙 {u}")


if __name__ == "__main__":
    main()
