#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Radar de Licitacoes v2.1 - PNCP, classificacao por area + filtro juridico"""

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

OUTPUT_DIR = Path(__file__).resolve().parent / "docs"
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_HTML = OUTPUT_DIR / "index.html"
OUTPUT_JSON = OUTPUT_DIR / "radar_licitacoes.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (RadarLicitacoes/4.1)", "Accept": "application/json"}


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
    "Tributario": {"cor": "#dc2626", "termos": ["tributari", "fiscal", "icms", "iss", "ipva", "iptu", "ipi", "pis", "cofins", "imposto", "tributo", "execucao fiscal", "execução fiscal", "credito tributario", "credito tributário", "auto de infracao", "auto de infração", "isencao", "isenção", "refis", "recuperacao de credito", "recuperação de crédito"]},
    "Trabalhista": {"cor": "#ea580c", "termos": ["trabalhist", "clt", "verbas rescis", "rescis", "sindical", "vinculo emprega", "vínculo emprega", "horas extras", "fgts", "estabilidade", "reintegra", "negociacao coletiva", "negociação coletiva", "dissidio", "dissídio", "convencao coletiva", "convenção coletiva"]},
    "Previdenciario": {"cor": "#7c3aed", "termos": ["previdenciari", "inss", "aposentadoria", "auxilio-doenca", "auxílio-doença", "beneficio previden", "benefício previden", "pensao por morte", "pensão por morte", "salario-maternidade", "salário-maternidade", "rgps", "rpps"]},
    "Administrativo": {"cor": "#0891b2", "termos": ["administrativ", "improbidade", "lei 8429", "lei 8.429", "responsabilidade do estado", "concurso publico", "concurso público", "servidor publico", "servidor público", "tomada de contas", "controle externo", "tcu", "tribunal de contas"]},
    "Civel": {"cor": "#16a34a", "termos": ["indenizacao", "indenização", "danos morais", "danos materiais", "responsabilidade civil", "obrigacao", "contrato civil", "execucao de titulo", "execução de título", "cobranca", "consignacao", "usucapiao", "ação de despejo"]},
    "Empresarial": {"cor": "#1d4ed8", "termos": ["empresari", "societari", "societário", "falencia", "falência", "recuperacao judicial", "recuperação judicial", "marca", "patente", "propriedade industrial", "antitruste"]},
    "Penal": {"cor": "#9f1239", "termos": ["penal", "criminal", "habeas corpus", "denuncia", "denúncia", "acao penal", "ação penal", "tribunal do juri", "lavagem de dinheiro", "improbidade administrativa", "crime contra"]},
    "Ambiental": {"cor": "#15803d", "termos": ["ambient", "licenciamento ambiental", "tac ambiental", "ibama", "compensacao ambiental", "compensação ambiental"]},
    "Consumidor": {"cor": "#be185d", "termos": ["consumidor", "cdc", "codigo de defesa", "código de defesa", "procon", "vicio do produto", "vício do produto", "vicio do servico", "vício do serviço"]},
}


def classificar_areas(titulo, descricao):
    texto = f"{titulo} {descricao}".lower()
    achadas = [a for a, conf in AREAS_JURIDICAS.items() if any(t.lower() in texto for t in conf["termos"])]
    return achadas or ["Geral"]


def e_servico_juridico(titulo, descricao):
    """Retorna True apenas se o edital eh para contratar servicos juridicos."""
    texto = (str(titulo or "") + " " + str(descricao or "")).lower()
    tem_juridico = any(t in texto for t in [
        "advocac", "advogad", "juridic",
        "consultoria juridica", "consultoria jurídica",
        "assessoria juridica", "assessoria jurídica",
        "servicos advocaticios", "serviços advocatícios",
        "servicos de advocacia", "serviços de advocacia",
        "escritorio de advocacia", "escritório de advocacia",
        "sociedade de advogados", "patrocinio judicial",
        "patrocínio judicial", "representacao judicial",
        "representação judicial", "parecer juridico", "parecer jurídico",
    ])
    if not tem_juridico:
        return False
    sinais_negativos = [
        "material de escritorio", "material de escritório",
        "veiculos", "veículos", "moveis", "móveis",
        "equipamentos de informatica", "equipamentos de informática",
        "impressao", "impressão", "limpeza", "alimentacao", "alimentação",
        "uniformes", "fardamento", "papelaria",
        "manutencao predial", "manutenção predial",
        "obras de construcao", "obras de construção",
        "merenda escolar", "transporte escolar",
    ]
    if any(neg in texto for neg in sinais_negativos):
        return False
    return True


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
                print(f"  [aviso] muito grande em '{keyword}'"); break
        except requests.RequestException as e:
            print(f"  [aviso] '{keyword}' pg{pagina}: {e}"); break
        try: data = json.loads(content.decode("utf-8", errors="replace"))
        except (ValueError, UnicodeDecodeError):
            print(f"  [aviso] nao-JSON em '{keyword}'"); break
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


def deduplicar(items):
    print("\n[2/3] Deduplicando...")
    visto = {}
    for it in items:
        ch = it.get("numero_controle_pncp") or it.get("id") or f"NA::{it.get('title','')}"
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
        url_montada = f"https://{PNCP_HOST}/app" + item_url.replace("/compras/", "/editais/")
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
        "url": url_segura(url_montada),
        "matched_keywords": [texto_seguro(k, 80) for k in (item.get("_matched_keywords") or [item.get("_keyword")]) if k],
    }


def fmt_data(s):
    if not s: return "—"
    s = str(s)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try: return datetime.strptime(s[:26 if "." in s[:30] else 19], fmt).strftime("%d/%m/%Y")
        except ValueError: continue
    return s[:10]


def fmt_valor(v):
    if v in (None, "", 0): return "—"
    try: return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(v)


COR_ESFERA = {"Federal": "#dc2626", "Estadual": "#0891b2", "Municipal": "#16a34a", "Distrital": "#7c3aed"}


def renderizar_html(items, somente_abertos):
    items_norm = sorted([normalizar(it) for it in items], key=lambda x: x["data_publicacao"] or "", reverse=True)
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    linhas_lista = []
    for it in items_norm:
        kws = ", ".join(it["matched_keywords"])
        cor_esfera = COR_ESFERA.get(it["esfera"], "#64748b")
        cidade_uf = f"{it['municipio']}/{it['uf']}" if it['uf'] else "—"
        areas_tags = "".join(f'<span class="area-tag" style="background:{AREAS_JURIDICAS.get(a, {}).get("cor", "#64748b")}">{escape(a)}</span>' for a in it["areas"])
        areas_data = "|".join(it["areas"])
        fim_html = f'<div><b>Fim:</b> {fmt_data(it["data_fim_vigencia"])}</div>' if it["data_fim_vigencia"] else ""
        desc_extra = "..." if len(it["descricao"]) > 240 else ""
        linha = (
            f'<tr data-esfera="{escape(it["esfera"])}" data-uf="{escape(it["uf"])}" data-areas="{escape(areas_data)}">'
            f'<td><span class="tag" style="background:{cor_esfera}">{escape(it["esfera"] or "?")}</span></td>'
            f'<td><div class="areas-row">{areas_tags}</div>'
            f'<a href="{escape(it["url"])}" target="_blank" rel="noopener noreferrer" class="titulo">{escape(it["titulo"][:200])}</a>'
            f'<div class="desc">{escape(it["descricao"][:240])}{desc_extra}</div>'
            f'<div class="meta"><span>🏛 {escape(it["orgao"][:80])}</span>'
            f'<span>📍 {escape(cidade_uf)}</span><span>🔑 {escape(kws)}</span></div></td>'
            f'<td>{escape(it["modalidade"])}<div class="situacao">{escape(it["situacao"])}</div></td>'
            f'<td class="valor">{fmt_valor(it["valor"])}</td>'
            f'<td><div><b>Pub:</b> {fmt_data(it["data_publicacao"])}</div>{fim_html}</td>'
            f'<td><a href="{escape(it["url"])}" target="_blank" rel="noopener noreferrer" class="btn">Ver edital</a></td></tr>'
        )
        linhas_lista.append(linha)
    linhas = "".join(linhas_lista) if linhas_lista else '<tr><td colspan="6" class="empty">Nenhum edital encontrado.</td></tr>'

    por_esfera = {}
    for i in items_norm:
        e = i["esfera"] or "?"
        por_esfera[e] = por_esfera.get(e, 0) + 1
    blocos_stats = "".join(f'<div class="stat"><div class="num" style="color:{COR_ESFERA.get(e, "#64748b")}">{n}</div><div class="lbl">{escape(e)}</div></div>' for e, n in sorted(por_esfera.items(), key=lambda x: -x[1]))
    opcoes_areas = "".join(f'<option value="{escape(a)}">{escape(a)}</option>' for a in list(AREAS_JURIDICAS.keys()) + ["Geral"])
    titulo_filtro = "editais com proposta ABERTA - apenas servicos juridicos" if somente_abertos else "todos os editais"
    total = len(items_norm)

    css = "*{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f7f8fa;color:#1a1a1a;margin:0;padding:24px}header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;flex-wrap:wrap;gap:12px}h1{margin:0;font-size:24px}.sub{color:#6b7280;font-size:13px;margin-top:4px}.stats{display:flex;gap:12px;flex-wrap:wrap}.stat{background:white;border:1px solid #e5e7eb;border-radius:8px;padding:10px 16px;min-width:110px}.stat .num{font-size:22px;font-weight:600}.stat .lbl{font-size:11px;color:#6b7280;text-transform:uppercase}.filters{background:white;border:1px solid #e5e7eb;border-radius:8px;padding:12px 16px;margin-bottom:16px;display:flex;gap:16px;flex-wrap:wrap}.filters label{font-size:13px;color:#374151}.filters input,.filters select{padding:6px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px}table{width:100%;background:white;border:1px solid #e5e7eb;border-radius:8px;border-collapse:separate;border-spacing:0;overflow:hidden}th,td{padding:12px;text-align:left;vertical-align:top;border-bottom:1px solid #f3f4f6;font-size:13px}th{background:#f9fafb;font-weight:600;color:#374151;font-size:12px;text-transform:uppercase}tr:last-child td{border-bottom:none}.titulo{color:#1d4ed8;text-decoration:none;font-weight:600}.titulo:hover{text-decoration:underline}.desc{color:#4b5563;font-size:12px;margin-top:4px;line-height:1.4}.meta{color:#6b7280;font-size:12px;margin-top:6px;display:flex;gap:12px;flex-wrap:wrap}.tag{display:inline-block;color:white;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:500}.area-tag{display:inline-block;color:white;padding:1px 7px;border-radius:3px;font-size:10px;font-weight:600;margin-right:4px;margin-bottom:4px}.areas-row{margin-bottom:6px}.situacao{font-size:11px;color:#6b7280;margin-top:4px}.valor{font-variant-numeric:tabular-nums;white-space:nowrap}.btn{display:inline-block;background:#1d4ed8;color:white;padding:6px 12px;border-radius:6px;text-decoration:none;font-size:12px;white-space:nowrap}.btn:hover{background:#1e40af}.empty{text-align:center;padding:40px;color:#6b7280}"

    js = "const ufs=new Set();document.querySelectorAll('tr[data-uf]').forEach(t=>{const u=t.dataset.uf;if(u)ufs.add(u)});const sU=document.getElementById('filter-uf');Array.from(ufs).sort().forEach(u=>{const o=document.createElement('option');o.value=u;o.textContent=u;sU.appendChild(o)});function filtrar(){const txt=document.getElementById('filter-text').value.toLowerCase();const ar=document.getElementById('filter-area').value;const es=document.getElementById('filter-esfera').value;const uf=document.getElementById('filter-uf').value;document.querySelectorAll('tbody tr').forEach(t=>{const ln=t.textContent.toLowerCase();const ars=(t.dataset.areas||'').split('|');const a=!txt||ln.includes(txt);const b=!ar||ars.includes(ar);const c=!es||t.dataset.esfera===es;const d=!uf||t.dataset.uf===uf;t.style.display=(a&&b&&c&&d)?'':'none'})}['filter-text','filter-area','filter-esfera','filter-uf'].forEach(i=>document.getElementById(i).addEventListener(i==='filter-text'?'input':'change',filtrar));"

    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>Radar de Licitacoes</title><meta name="viewport" content="width=device-width,initial-scale=1"><style>{css}</style></head><body><header><div><h1>📡 Radar de Licitacoes</h1><div class="sub">Atualizado: {agora} - PNCP - {titulo_filtro}</div></div><div class="stats"><div class="stat"><div class="num">{total}</div><div class="lbl">Total</div></div>{blocos_stats}</div></header><div class="filters"><label>🔍 Buscar: <input type="text" id="filter-text" placeholder="palavra, orgao..."></label><label>Area: <select id="filter-area"><option value="">Todas</option>{opcoes_areas}</select></label><label>Esfera: <select id="filter-esfera"><option value="">Todas</option><option value="Federal">Federal</option><option value="Estadual">Estadual</option><option value="Municipal">Municipal</option><option value="Distrital">Distrital</option></select></label><label>UF: <select id="filter-uf"><option value="">Todas</option></select></label></div><table><thead><tr><th>Esfera</th><th>Objeto / Orgao</th><th>Modalidade</th><th>Valor</th><th>Datas</th><th>Acao</th></tr></thead><tbody>{linhas}</tbody></table><script>{js}</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--abrir", action="store_true")
    ap.add_argument("--tudo", action="store_true")
    args = ap.parse_args()
    somente_abertos = not args.tudo
    inicio = datetime.now(timezone.utc)
    brutos = coletar_tudo(somente_abertos)
    unicos = deduplicar(brutos)
    antes = len(unicos)
    unicos = [it for it in unicos if e_servico_juridico(it.get("title",""), it.get("description",""))]
    print(f"  filtrados como servico juridico: {len(unicos)} (de {antes})")
    print(f"\n[3/3] Gerando saidas...")
    OUTPUT_JSON.write_text(json.dumps({
        "gerado_em": inicio.isoformat(), "fonte": "PNCP",
        "filtro": "recebendo_proposta + servicos_juridicos" if somente_abertos else "todos",
        "palavras_chave": PALAVRAS_CHAVE, "total": len(unicos),
        "items": [normalizar(it) for it in unicos],
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    OUTPUT_HTML.write_text(renderizar_html(unicos, somente_abertos), encoding="utf-8")
    print(f"\nConcluido. Total: {len(unicos)} editais.")
    if args.abrir: webbrowser.open(OUTPUT_HTML.as_uri())


if __name__ == "__main__":
    main()
