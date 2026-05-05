#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Radar de Licitacoes v2 - PNCP com classificacao por area juridica"""

import argparse, json, sys, time, webbrowser
from datetime import datetime, timezone
from html import escape
from pathlib import Path

try:
    import requests
except ImportError:
    print("Instale com: pip install requests"); sys.exit(1)

PALAVRAS_CHAVE = [
    "consultoria tributaria", "consultoria juridica", "escritorio de advocacia",
    "sociedade de advogados", "assessoria juridica", "servicos advocaticios",
    "servicos de advocacia", "patrocinio judicial", "representacao judicial",
    "contencioso administrativo", "contencioso tributario", "contencioso trabalhista",
    "parecer juridico", "recuperacao de creditos tributarios",
]

PNCP_HOST = "pncp.gov.br"
PNCP_SEARCH_URL = f"https://{PNCP_HOST}/api/search/"
PAGINAS_POR_KEYWORD = 3
RESULTADOS_POR_PAGINA = 20
PAUSA_ENTRE_REQUESTS = 0.4
LIMITE_RESPOSTA_BYTES = 5_000_000
TIMEOUT_SEGUNDOS = 30

# Output em docs/ - GitHub Pages serve essa pasta como site
OUTPUT_DIR = Path(__file__).resolve().parent / "docs"
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_HTML = OUTPUT_DIR / "index.html"
OUTPUT_JSON = OUTPUT_DIR / "radar_licitacoes.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (RadarLicitacoes/4.0)", "Accept": "application/json"}


def url_segura(url):
    if not isinstance(url, str): return f"https://{PNCP_HOST}/app"
    u = url.strip()
    if u.startswith(("https://pncp.gov.br/", "https://www.pncp.gov.br/")): return u
    return f"https://{PNCP_HOST}/app"


def texto_seguro(s, limite=5000):
    if s is None: return ""
    s = str(s)[:limite]
    return "".join(c for c in s if c == "\n" or c == "\t" or (ord(c) >= 32 and ord(c) != 127))


AREAS_JURIDICAS = {
    "Tributario": {"cor": "#dc2626", "termos": ["tributari", "fiscal", "icms", "iss", "ipva", "iptu", "ipi", "pis", "cofins", "imposto", "tributo", "execucao fiscal", "credito tributario", "auto de infracao", "isencao", "refis", "recuperacao de credito"]},
    "Trabalhista": {"cor": "#ea580c", "termos": ["trabalhist", "clt", "verbas rescis", "rescis", "sindical", "vinculo emprega", "horas extras", "fgts", "estabilidade", "reintegra", "negociacao coletiva", "dissidio", "convencao coletiva"]},
    "Previdenciario": {"cor": "#7c3aed", "termos": ["previdenciari", "inss", "aposentadoria", "auxilio-doenca", "beneficio previden", "pensao por morte", "salario-maternidade", "rgps", "rpps"]},
    "Administrativo": {"cor": "#0891b2", "termos": ["administrativ", "improbidade", "lei 8429", "concurso publico", "servidor publico", "tomada de contas", "controle externo", "tcu", "tribunal de contas"]},
    "Civel": {"cor": "#16a34a", "termos": ["indenizacao", "danos morais", "danos materiais", "responsabilidade civil", "obrigacao", "contrato civil", "execucao de titulo", "cobranca", "consignacao", "usucapiao", "despejo"]},
    "Empresarial": {"cor": "#1d4ed8", "termos": ["empresari", "societari", "falencia", "recuperacao judicial", "marca", "patente", "propriedade industrial", "antitruste"]},
    "Penal": {"cor": "#9f1239", "termos": ["penal", "criminal", "habeas corpus", "denuncia", "acao penal", "tribunal do juri", "lavagem de dinheiro", "crime contra"]},
    "Ambiental": {"cor": "#15803d", "termos": ["ambient", "licenciamento ambiental", "ibama", "compensacao ambiental"]},
    "Consumidor": {"cor": "#be185d", "termos": ["consumidor", "cdc", "codigo de defesa", "procon", "vicio do produto", "vicio do servico"]},
}


def classificar_areas(titulo, descricao):
    texto = f"{titulo} {descricao}".lower()
    achadas = [a for a, conf in AREAS_JURIDICAS.items() if any(t.lower() in texto for t in conf["termos"])]
    return achadas or ["Geral"]


def buscar_pncp(keyword, somente_abertos):
    coletados = []
    for pagina in range(1, PAGINAS_POR_KEYWORD + 1):
        params = {"q": keyword, "tipos_documento": "edital", "ordenacao": "-data",
                  "pagina": pagina, "tam_pagina": RESULTADOS_POR_PAGINA}
        if somente_abertos: params["status"] = "recebendo_proposta"
        try:
            resp = requests.get(PNCP_SEARCH_URL, params=params, headers=HEADERS,
                                timeout=TIMEOUT_SEGUNDOS, verify=True,
                                allow_redirects=False, stream=True)
            resp.raise_for_status()
            content = resp.raw.read(LIMITE_RESPOSTA_BYTES + 1, decode_content=True)
            if len(content) > LIMITE_RESPOSTA_BYTES:
                print(f"  [aviso] resposta muito grande em '{keyword}'"); break
        except requests.RequestException as e:
            print(f"  [aviso] '{keyword}' pg{pagina}: {e}"); break
        try:
            data = json.loads(content.decode("utf-8", errors="replace"))
        except (ValueError, UnicodeDecodeError):
            print(f"  [aviso] resposta nao-JSON em '{keyword}'"); break
        if not isinstance(data, dict): break
        items = data.get("items") or []
        if not items: break
        for it in items: it["_keyword"] = keyword
        coletados.extend(items)
        if len(items) < RESULTADOS_POR_PAGINA: break
        time.sleep(PAUSA_ENTRE_REQUESTS)
    return coletados


def coletar_tudo(somente_abertos):
    print(f"\n[1/3] Coletando ({len(PALAVRAS_CHAVE)} palavras-chave)...")
    todos = []
    for kw in PALAVRAS_CHAVE:
        print(f"  '{kw}' ... ", end="", flush=True)
        r = buscar_pncp(kw, somente_abertos)
        print(f"{len(r)} encontrados")
        todos.extend(r); time.sleep(PAUSA_ENTRE_REQUESTS)
    print(f"  total bruto: {len(todos)}")
    return todos


def chave_unica(item):
    return item.get("numero_controle_pncp") or item.get("id") or f"NA::{item.get('title','')}"


def deduplicar(items):
    print("\n[2/3] Deduplicando...")
    visto = {}
    for it in items:
        ch = chave_unica(it)
        if ch in visto:
            kws = visto[ch].setdefault("_matched_keywords", [visto[ch].get("_keyword")])
            if it.get("_keyword") not in kws: kws.append(it.get("_keyword"))
        else:
            it["_matched_keywords"] = [it.get("_keyword")]; visto[ch] = it
    print(f"  unicos: {len(visto)}")
    return list(visto.values())


def normalizar(item):
    item_url = item.get("item_url") or ""
    if item_url and not item_url.startswith("http"):
        url_montada = f"https://{PNCP_HOST}/app" + item_url
    else:
        url_montada = item_url or f"https://{PNCP_HOST}/app/editais"
    titulo_safe = texto_seguro(item.get("title"), 300) or "(sem titulo)"
    descricao_safe = texto_seguro(item.get("description"), 2000)
    return {
        "titulo": titulo_safe, "descricao": descricao_safe,
        "areas": classificar_areas(titulo_safe, descricao_safe),
        "orgao": texto_seguro(item.get("orgao_nome"), 200),
        "uf": texto_seguro(item.get("uf"), 4),
        "municipio": texto_seguro(item.get("municipio_nome"), 100),
        "esfera": texto_seguro(item.get("esfera_nome"), 30),
        "modalidade": texto_seguro(item.get("modalidade_licitacao_nome"), 100),
        "situacao": texto_seguro(item.get("situacao_nome"), 60),
        "valor": item.get("valor_global"),
        "data_publicacao": texto_seguro(item.get("data_publicacao_pncp"), 30),
        "data_fim_vigencia": texto_seguro(item.get("data_fim_vigencia"), 30),
        "numero_controle": texto_seguro(item.get("numero_controle_pncp"), 60),
        "url": url_segura(url_montada),
        "matched_keywords": [texto_seguro(k, 80) for k in (item.get("_matched_keywords") or [item.get("_keyword")]) if k],
    }


def fmt_data(s):
    if not s: return "-"
    s = str(s)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try: return datetime.strptime(s[:26 if "." in s[:30] else 19], fmt).strftime("%d/%m/%Y")
        except ValueError: continue
    return s[:10]


def fmt_valor(v):
    if v in (None, "", 0): return "-"
    try: return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError): return str(v)


COR_ESFERA = {"Federal": "#dc2626", "Estadual": "#0891b2", "Municipal": "#16a34a", "Distrital": "#7c3aed"}


def renderizar_html(items, somente_abertos):
    items_norm = sorted([normalizar(it) for it in items], key=lambda x: x["data_publicacao"] or "", reverse=True)
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    linhas_lista = []
    for it in items_norm:
        kws = ", ".join(it["matched_keywords"])
        cor_esfera = COR_ESFERA.get(it["esfera"], "#64748b")
        cidade_uf = f"{it['municipio']}/{it['uf']}" if it['uf'] else "-"
        areas_tags = "".join(f'<span class="area-tag" style="background:{AREAS_JURIDICAS.get(a, {}).get("cor", "#64748b")}">{escape(a)}</span>' for a in it["areas"])
        areas_data = "|".join(it["areas"])
        fim_html = f'<div><b>Fim:</b> {fmt_data(it["data_fim_vigencia"])}</div>' if it["data_fim_vigencia"] else ""
        desc_extra = "..." if len(it["descricao"]) > 240 else ""
        linha = (f'<tr data-esfera="{escape(it["esfera"])}" data-uf="{escape(it["uf"])}" data-areas="{escape(areas_data)}">'
                 f'<td><span class="tag" style="background:{cor_esfera}">{escape
