#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera a dashboard estatica (index.html) de CAPTACAO de leads (isca gratuita) a
partir de DUAS planilhas independentes do cliente:

  - "Leads" (planilha SPREADSHEET_ID_LEADS, aba gid GID_LEADS): fonte PRINCIPAL
    de leads — cada inscricao na isca gratuita. Usada em TODOS os
    graficos/cards/tabelas/calculos de conversao. Traz utm_source/utm_campaign/
    utm_medium/utm_content/utm_term, que atribuem o lead a campanha/conjunto/
    anuncio (nomes identicos ao Meta Ads).
  - "Meta Ads" (planilha SPREADSHEET_ID_META, aba gid GID_META): investimento/
    impressoes/cliques/landing page views do gerenciador.

Esta e' uma ISCA GRATUITA: NAO ha criterio de MQL, nem aba de Compradores/
vendas. O funil vai ate o Lead (Gasto -> Impressoes -> Cliques -> Leads). Os
campos de MQL/venda continuam no schema (q=0, sales=[]) so para manter a
estrutura de dados que o front-end espera, mas nao aparecem na interface.

Este script apenas LE as planilhas (export CSV publico, somente leitura) e emite
os REGISTROS BRUTOS (leads[], meta[]) dentro do HTML. Todos os filtros,
agregacoes, KPIs, tabelas e graficos sao calculados no navegador (client-side).
Nunca escreve nada de volta.

Teste local: --leads-file / --meta-file apontando para CSVs baixados.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

# --------------------------------------------------------------------------- #
# Fontes de dados — DUAS planilhas distintas (Leads e Meta Ads)
# --------------------------------------------------------------------------- #
SPREADSHEET_ID_LEADS = "1_pBhH2m3R1BR11kRdgq2cn_j3L2JaifO3ui3xFbnd28"  # planilha "Leads"
GID_LEADS = "0"                                                        # aba "Leads"
SPREADSHEET_ID_META = "1BL0Lz6d5mDPhT77qEtBbIeN6oMyVN1fEmEQlTgLSSLY"   # planilha "Extração Dashboard - Isca Out26"
GID_META = "0"                                                         # aba "Página1"
EXPORT_URL = "https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"

# Identificação do cliente/conta (usada só em textos — não afeta o cruzamento de dados).
CLIENT_NAME = "Nubia Oliveira"
MAIN_PRODUCT = "raio-x"            # nome do funil / oferta (isca gratuita)
# Prefixo comum a TODAS as campanhas da conta (usado só como referência de
# nomenclatura). As campanhas desta conta começam com "ISCA" (ex.:
# "ISCA-CGU | E2-CAP | LEAD | ABO | ...").
MAIN_PRODUCT_PREFIX = "ISCA"

BRT = timezone(timedelta(hours=-3))   # horario de Brasilia (exibicao)
TAX_FACTOR = 1.13806   # fator de imposto/taxa sobre o gasto de mídia paga (Meta Ads) = 13,806%.
                       # Toggle "Imposto Meta" ativo por padrão no app. Use 1.0 se não houver imposto.

# --------------------------------------------------------------------------- #
# Regras da aba Relatório (Top anúncios de captação)
# --------------------------------------------------------------------------- #
# Amostra mínima para julgar um anúncio como "avaliável". Abaixo disso ele entra
# como "Em observação" (dado insuficiente). Isca gratuita: a amostra é medida em
# LEADS (não há MQL/venda).
SAMPLE_MIN_SPEND = 50.0    # gasto mínimo (R$) para amostra relevante
SAMPLE_MIN_LEADS = 3       # leads mínimos para julgar o anúncio
TOP_ADS_N = 10             # nº de linhas em Top anúncios

# Metas & parâmetros da conta (DEFAULTS do painel editável da aba Relatório).
# Isca gratuita: a meta principal é o CPL (custo por lead). None = "não definida".
META_CPL = None            # meta de CPL (R$/lead); None = não definida
VOLUME_MIN_AMOSTRAL = SAMPLE_MIN_LEADS  # leads mínimos p/ amostra confiável
N_DIAS_CORTE = 5           # dias consecutivos acima do teto p/ considerar corte


# --------------------------------------------------------------------------- #
# Leitura
# --------------------------------------------------------------------------- #
FETCH_RETRIES = 3       # tentativas totais em caso de timeout/erro de rede no export CSV
FETCH_RETRY_DELAY = 15  # segundos entre tentativas (o Google Sheets às vezes trava a resposta)


def fetch_csv(url: str) -> list[list[str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "dash-template-bot/1.0"})
    last_err: Exception | None = None
    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            return list(csv.reader(io.StringIO(raw)))
        except (TimeoutError, urllib.error.URLError) as exc:
            last_err = exc
            if attempt < FETCH_RETRIES:
                print(f"[fetch_csv] tentativa {attempt}/{FETCH_RETRIES} falhou ({exc!r}); "
                      f"tentando de novo em {FETCH_RETRY_DELAY}s...", file=sys.stderr)
                time.sleep(FETCH_RETRY_DELAY)
    raise last_err


def read_csv_file(path: str) -> list[list[str]]:
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        return list(csv.reader(f))


def load_rows(url: str, local: str | None) -> list[list[str]]:
    return read_csv_file(local) if local else fetch_csv(url)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str | None) -> str:
    return strip_accents((s or "").strip().lower())


def to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v).strip())
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_date(v: str) -> str | None:
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    # pega só a parte de data quando vem "dd/mm/aaaa hh:mm"
    s = s.split(" ")[0].split("T")[0] if (" " in s or "T" in s) else s
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d/%m/%y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def is_test_lead(rowtext: str) -> bool:
    low = rowtext.lower()
    return "<test lead" in low or " teste" in (" " + low)


def pretty_val(v: str, default: str) -> str:
    s = (v or "").strip()
    return s if s else default


def mask_email(e: str) -> str:
    e = (e or "").strip()
    if "@" not in e:
        return "—"
    user, dom = e.split("@", 1)
    keep = user[:2] if len(user) > 2 else user[:1]
    return f"{keep}****@{dom}"


def mask_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p or "")
    return f"…{digits[-4:]}" if len(digits) >= 4 else "—"


def first_last_initial(name: str) -> str:
    parts = (name or "").strip().split()
    if not parts:
        return "—"
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][:1]}."


def valid_utm(campaign: str) -> bool:
    c = norm(campaign)
    return bool(c) and c not in ("-", "—", "nao encontrado", "(not set)", "not set")


def platform_of(utm_term: str, utm_source: str) -> str:
    """Plataforma a partir do posicionamento (utm_term) ou da origem (utm_source)."""
    t = norm(utm_term) + " " + norm(utm_source)
    if "instagram" in t or t.strip().startswith("ig"):
        return "ig"
    if "facebook" in t or "fb_" in t or t.strip().startswith("fb"):
        return "fb"
    return "—"


# --------------------------------------------------------------------------- #
# Indexacao das colunas
# --------------------------------------------------------------------------- #
def header_index(header, wanted, fallback):
    idx = {}
    hn = [norm(h) for h in header]
    for key, aliases in wanted.items():
        found = None
        for a in aliases:
            a = norm(a)
            for i, h in enumerate(hn):
                if h == a or (a and a in h):
                    found = i
                    break
            if found is not None:
                break
        idx[key] = found if found is not None else fallback.get(key)
    return idx


def cell(row, i):
    if i is None or i < 0 or i >= len(row):
        return ""
    return (row[i] or "").strip()


# --------------------------------------------------------------------------- #
# Processamento -> registros brutos
# --------------------------------------------------------------------------- #
def process(leads_rows, meta_rows):
    # ------- Leads (fonte principal) -------
    lheader = leads_rows[0] if leads_rows else []
    lidx = header_index(
        lheader,
        {"created": ["data_inscricao", "data", "created", "timestamp"],
         "name": ["nome", "name"], "email": ["email", "e-mail"],
         "phone": ["telefone", "phone", "whatsapp"],
         "source": ["utm_source", "source", "origem"],
         "campaign": ["utm_campaign", "campanha", "campaign"],
         "adset": ["utm_medium", "conjunto", "ad set", "adset"],
         "ad": ["utm_content", "anuncio", "ad name", "ad"],
         "term": ["utm_term", "posicionamento", "placement"]},
        {"created": 0, "name": 1, "email": 2, "phone": 3, "source": 4,
         "campaign": 5, "adset": 6, "ad": 7, "term": 8},
    )

    leads = []
    for row in leads_rows[1:]:
        if not any((c or "").strip() for c in row):
            continue
        if is_test_lead(" ".join(str(c) for c in row)):
            continue
        campaign_raw = cell(row, lidx["campaign"])
        campaign_valid = valid_utm(campaign_raw)
        src = "meta" if campaign_valid else "org"
        camp = campaign_raw if campaign_valid else "(sem campanha)"
        adset = cell(row, lidx["adset"]) if campaign_valid else "(sem conjunto)"
        ad = cell(row, lidx["ad"]) if campaign_valid else "(sem anúncio)"
        term = cell(row, lidx["term"])
        pos = pretty_val(term, "Sem posicionamento")
        plat = platform_of(term, cell(row, lidx["source"]))
        leads.append({
            "d": parse_date(cell(row, lidx["created"])),
            "src": src,
            "plat": plat,
            "camp": camp,
            "adset": adset,
            "ad": ad,
            "prof": pos,       # mantém chave 'prof' do schema; usada como "posicionamento"
            "bucket": pos,     # idem — dimensão de posicionamento
            "pos": pos,
            "q": 0,            # isca gratuita: sem MQL
            "utm": 1 if campaign_valid else 0,
            "nm": first_last_initial(cell(row, lidx["name"])),
            "em": mask_email(cell(row, lidx["email"])),
            "ph": mask_phone(cell(row, lidx["phone"])),
        })

    # ------- Meta Ads -------
    mheader = meta_rows[0] if meta_rows else []
    midx = header_index(
        mheader,
        {"day": ["day", "data"], "campaign": ["campaign name", "campaign", "campanha"],
         "adset": ["ad set name", "adset", "conjunto"], "ad": ["ad name", "anuncio"],
         "spent": ["amount spent", "valor gasto", "gasto"], "impr": ["impressions", "impress"],
         "clicks": ["link clicks", "clicks", "cliques"], "leads": ["leads", "results", "resultados"],
         "pv": ["landing page views", "page views", "pageviews"],
         "chk": ["adds to cart", "add to cart", "initiate checkout", "checkouts"],
         "link": ["creative instagram permalink", "instagram permalink", "permalink",
                  "creative link", "link do anuncio", "link do criativo"]},
        {"day": 0, "campaign": 1, "adset": 2, "ad": 3, "impr": 4, "clicks": 5, "pv": 6, "spent": 7,
         "leads": None, "chk": None, "link": None},
    )

    meta = []
    ad_links = {}
    for row in meta_rows[1:]:
        if not any((c or "").strip() for c in row):
            continue
        ad = cell(row, midx["ad"]) or "(sem anúncio)"
        link = cell(row, midx["link"])
        if link and ad not in ad_links:
            ad_links[ad] = link
        meta.append({
            "d": parse_date(cell(row, midx["day"])),
            "camp": cell(row, midx["campaign"]) or "(sem campanha)",
            "adset": cell(row, midx["adset"]) or "(sem conjunto)",
            "ad": ad,
            "sp": round(to_float(cell(row, midx["spent"])), 4),
            "im": to_float(cell(row, midx["impr"])),
            "cl": to_float(cell(row, midx["clicks"])),
            "pv": to_float(cell(row, midx["pv"])),
            "ck": to_float(cell(row, midx["chk"])),
            "ml": to_float(cell(row, midx["leads"])),
        })

    dates = sorted({d for d in (
        [l["d"] for l in leads if l["d"]] + [m["d"] for m in meta if m["d"]]
    )})
    now_brt = datetime.now(BRT)
    return {
        "build": {
            "generated_at_brt": now_brt.strftime("%d/%m/%Y %H:%M"),
            "build_id": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "today": now_brt.strftime("%Y-%m-%d"),
            "date_min": dates[0] if dates else None,
            "date_max": dates[-1] if dates else None,
            "tax_factor": TAX_FACTOR,
            # config da aba Relatório (lida pelo front) — isca: amostra em leads
            "sample_min_spend": SAMPLE_MIN_SPEND,
            "sample_min_leads": SAMPLE_MIN_LEADS,
            "top_ads_n": TOP_ADS_N,
            # metas & parâmetros (defaults do painel editável; None = não definida)
            "meta_cpl": META_CPL,
            "volume_min_amostral": VOLUME_MIN_AMOSTRAL,
            "n_dias_corte": N_DIAS_CORTE,
            # isca gratuita: sem fonte de leads legado
            "leads_lp_total": 0,
        },
        "leads": leads,
        "meta": meta,
        "sales": [],         # isca gratuita: sem vendas/compradores
        "ad_links": ad_links,
        "briefings": {},     # Insights de Tráfego (opcional, lido de relatorios.json)
    }


# --------------------------------------------------------------------------- #
# Insights de Tráfego (aba Relatório) — opcional, só lê o JSON já pronto
# --------------------------------------------------------------------------- #
def load_briefings(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except (ValueError, OSError):
        return {}


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def render(data, template_path):
    base = os.path.dirname(os.path.abspath(template_path))

    def readf(name):
        with open(os.path.join(base, name), "r", encoding="utf-8") as f:
            return f.read()

    with open(template_path, "r", encoding="utf-8") as f:
        tpl = f.read()
    styles = readf("identidade-visual.css") + "\n" + readf("estilos.css")
    tpl = tpl.replace("__STYLES__", styles)
    tpl = tpl.replace("__APP_JS__", readf("app.js"))
    tpl = tpl.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    tpl = tpl.replace("__BUILD_ID__", data["build"]["build_id"])
    tpl = tpl.replace("__GENERATED_BRT__", data["build"]["generated_at_brt"])
    return tpl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leads-file", help="CSV local da aba Leads (fonte principal)")
    ap.add_argument("--meta-file", help="CSV local da aba Meta Ads")
    ap.add_argument("--template", default="build/template.html")
    ap.add_argument("--out", default="dist/index.html")
    args = ap.parse_args()

    leads_rows = load_rows(EXPORT_URL.format(sid=SPREADSHEET_ID_LEADS, gid=GID_LEADS), args.leads_file)
    meta_rows = load_rows(EXPORT_URL.format(sid=SPREADSHEET_ID_META, gid=GID_META), args.meta_file)

    data = process(leads_rows, meta_rows)

    briefings_path = os.path.join(os.path.dirname(os.path.abspath(args.template)), "relatorios.json")
    data["briefings"] = load_briefings(briefings_path)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(render(data, args.template))

    b = data["build"]
    nads = sum(1 for l in data["leads"] if l["src"] == "meta")
    norg = sum(1 for l in data["leads"] if l["src"] == "org")
    print("== build ok (isca gratuita · captação) ==", file=sys.stderr)
    print(f"  periodo   : {b['date_min']} -> {b['date_max']}", file=sys.stderr)
    print(f"  leads     : {len(data['leads'])}  (meta: {nads} · orgânico: {norg})", file=sys.stderr)
    print(f"  meta      : {len(data['meta'])} linhas", file=sys.stderr)
    print(f"  out       : {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
