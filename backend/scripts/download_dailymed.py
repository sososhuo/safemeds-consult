import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import requests


DRUGS = ["warfarin", "ibuprofen", "fluconazole", "simvastatin", "clarithromycin", "sildenafil", "nitroglycerin", "metformin"]
OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "dailymed_samples.json"


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fetch_spls(drug: str):
    url = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"
    resp = requests.get(url, params={"drug_name": drug, "pagesize": 1}, timeout=20)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if not data:
        return None
    setid = data[0]["setid"]
    xml = requests.get(f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{setid}.xml", timeout=20)
    xml.raise_for_status()
    return setid, xml.text


def extract_sections(xml_text: str):
    root = ET.fromstring(xml_text)
    sections = []
    for component in root.iter():
        title = None
        text_parts = []
        for child in component:
            tag = child.tag.split("}")[-1]
            if tag == "title":
                title = clean("".join(child.itertext()))
            if tag == "text":
                text_parts.append(clean(" ".join(child.itertext())))
        if title and text_parts and any(key in title.upper() for key in ["INTERACTIONS", "CONTRAINDICATIONS", "WARNINGS", "PRECAUTIONS"]):
            sections.append({"title": title, "content": " ".join(text_parts)[:2500]})
    return sections[:8]


def main():
    results = []
    for drug in DRUGS:
        try:
            payload = fetch_spls(drug)
            if not payload:
                print(f"未找到: {drug}")
                continue
            setid, xml_text = payload
            results.append({"drug": drug, "setid": setid, "sections": extract_sections(xml_text)})
            print(f"已下载: {drug} {setid}")
        except Exception as exc:
            print(f"下载失败 {drug}: {exc}")
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"保存到 {OUT}")


if __name__ == "__main__":
    main()
