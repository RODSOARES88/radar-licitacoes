#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Radar de Licitações - PNCP
==========================
Varre o Portal Nacional de Contratações Públicas (PNCP) buscando editais
com proposta ABERTA (recebendo proposta) que casem com palavras-chave
do escritório de advocacia.

Por que PNCP?
  - É o portal oficial centralizado, obrigatório por lei (Lei 14.133/2021)
  - Cobre União, estados, municípios e entes vinculados — Brasil todo
  - API pública e estável, retorna JSON limpo

Saída:
  - radar_licitacoes.html  (dashboard interativo)
  - radar_licitacoes.json  (dados estruturados, histórico)

Uso:
  python radar_licitacoes.py
  python radar_licitacoes.py --abrir       (abre o HTML no browser ao final)
  python radar_licitacoes.py --tudo        (inclui editais SEM proposta aberta também,
                                            útil para mapear histórico/concorrência)

Dependências:
  pip install requests
"""

import argparse
import json
import sys
import time
import webbrowser
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlencode

try:
    import requests
except ImportError:
    print("ERRO: o módulo 'requests' não está instalado.")
    print("Instale com:  pip install requests")
    sys.exit(1)

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO
# ---------------------------------------------------------------------------

# Palavras-chave do escritório - EDITE AQUI conforme novas demandas.
PALAVRAS_CHAVE = [
    # Núcleo
    "consultoria tributária",
    "consultoria jurídica",
    "escritório de advocacia",
    "sociedade de advogados",
    # Variações de prestação
    "assessoria jurídica",
    "serviços advocatícios",
    "serviços de advocacia",
    "patrocínio judicial",
    "representação judicial",
    # Áreas
    "contencioso administrativo",
    "contencioso tributário",
    "contencioso trabalhista",
    "parecer jurídico",
    "recuperação de créditos tributários",
]

# =============== SEGURANÇA ================================================
# Defesas integradas:
#   (S1) Comunicação SOMENTE com pncp.gov.br via HTTPS, com verificação de
#        certificado SSL (padrão do 'requests', explicitado abaixo).
#   (S2) Limite de tamanho de resposta para evitar resposta maliciosa enorme.
#   (S3) Não seguir redirecionamentos para fora do PNCP.
#   (S4) Allowlist de URLs renderizadas no HTML (só pncp.gov.br aparece como link).
#   (S5) Sanitização de caracteres de controle nas strings vindas da API.
#   (S6) Escape HTML em TODOS os campos exibidos (já feito via html.escape).
#   (S7) CSP estrito no HTML gerado (impede scripts externos rodarem).
#   (S8) Não usa eval/exec/shell. Não acessa arquivos fora da própria pasta.
# ==========================================================================

# Endpoint público (mesmo usado pelo site pncp.gov.br/app)
PNCP_HOST = "pncp.gov.br"
PNCP_SEARCH_URL = f"https://{PNCP_HOST}/api/search/"

PAGINAS_POR_KEYWORD = 3            # quantas páginas pegar por palavra-chave
RESULTADOS_POR_PAGINA = 20         # tamanho da página
PAUSA_ENTRE_REQUESTS = 0.4         # segundos, para ser educado com a API
LIMITE_RESPOSTA_BYTES = 5_000_000  # (S2) máximo de 5 MB por requisição
TIMEOUT_SEGUNDOS = 30

# Output em docs/ — GitHub Pages serve essa pasta como site público
OUTPUT_DIR = Path(__file__).resolve().parent / "docs"
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_HTML = OUTPUT_DIR / "index.html"   # 'index.html' fica na raiz do site
OUTPUT_JSON = OUTPUT_DIR / "radar_licitacoes.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (RadarLicitacoes/3.0)",
    "Accept": "application/json",
}


# ---------------------------------------------------------------------------
# Helpers de segurança
# ---------------------------------------------------------------------------

def url_segura(url: str) -> str:
    """(S4) Devolve a URL APENAS se ela apontar para pncp.gov.br via https.
    Caso contrário, devolve uma URL neutra (página inicial do PNCP).
    Isso impede que uma resposta adulterada da API insira links maliciosos
    no HTML do dashboard."""
    if not isinstance(url, str):
        return f"https://{PNCP_HOST}/app"
    u = url.strip()
    if u.startswith(("https://pncp.gov.br/", "https://www.pncp.gov.br/")):
        return u
    return f"https://{PNCP_HOST}/app"


def texto_seguro(s, limite: int = 5000) -> str:
    """(S5) Remove caracteres de controle e limita o tamanho de qualquer
    string vinda da API antes de renderizar no HTML."""
    if s is None:
        return ""
    s = str(s)[:limite]
    # Remove caracteres de controle (exceto \n e \t comuns em descrições)
    return "".join(c for c in s if c == "\n" or c == "\t" or (ord(c) >= 32 and ord(c) != 127))


# ===========================================================================
# CLASSIFICAÇÃO POR ÁREA JURÍDICA
# ===========================================================================
# Cada área tem um conjunto de "termos-gatilho". Se o título OU a descrição
# de um edital contiver QUALQUER um desses termos, recebe a tag da área.
# Um mesmo edital pode receber múltiplas áreas (ex: "consultoria tributária
# e trabalhista" -> Tributário + Trabalhista).
#
# EDITE AQUI para refinar conforme novas demandas do escritório.
# As cores são usadas como tags coloridas no dashboard.

AREAS_JURIDICAS = {
    "Tributário": {
        "cor": "#dc2626",
        "termos": [
            "tributári", "fiscal", "icms", "iss", "ipva", "iptu", "ipi", "pis",
            "cofins", "imposto", "tributo", "execução fiscal", "execucao fiscal",
            "recuperação de crédito", "recuperacao de credito", "credito tributário",
            "credito tributario", "auto de infração", "auto de infracao",
            "isenção", "isencao", "refis", "parcelamento tributário", "parcelamento tributario",
        ],
    },
    "Trabalhista": {
        "cor": "#ea580c",
        "termos": [
            "trabalhist", "clt", "verbas rescis", "rescis", "sindical",
            "vínculo emprega", "vinculo emprega", "horas extras", "fgts",
            "previdenciário do trabalho", "estabilidade", "reintegra",
            "negociação coletiva", "negociacao coletiva", "dissídio", "dissidio",
            "convenção coletiva", "convencao coletiva",
        ],
    },
    "Previdenciário": {
        "cor": "#7c3aed",
        "termos": [
            "previdenciári", "inss", "aposentadoria", "auxílio-doença",
            "auxilio-doenca", "benefício previden", "beneficio previden",
            "pensão por morte", "pensao por morte", "salário-maternidade",
            "salario-maternidade", "lei 8213", "lei 8.213", "rgps", "rpps",
        ],
    },
    "Administrativo": {
        "cor": "#0891b2",
        "termos": [
            "administrativ", "processo administrativo", "ato administrativo",
            "improbidade", "lei 8429", "lei 8.429", "responsabilidade do estado",
            "concurso público", "concurso publico", "servidor público", "servidor publico",
            "tomada de contas", "controle externo", "tcu", "tribunal de contas",
            "regime jurídico único", "regime juridico unico", "rju",
        ],
    },
    "Cível": {
        "cor": "#16a34a",
        "termos": [
            "indenização", "indenizacao", "danos morais", "danos materiais",
            "responsabilidade civil", "obrigação", "obrigacao", "contrato civil",
            "ação ordinária", "acao ordinaria", "execução de título", "execucao de titulo",
            "cobrança", "cobranca", "consignação", "consignacao",
            "usucapião", "usucapiao", "ação de despejo", "acao de despejo",
        ],
    },
    "Empresarial": {
        "cor": "#1d4ed8",
        "termos": [
            "empresari", "societári", "societario", "falência", "falencia",
            "recuperação judicial", "recuperacao judicial", "dissolução de sociedade",
            "dissolucao de sociedade", "marca", "patente", "propriedade industrial",
            "concorrência desleal", "concorrencia desleal", "antitruste",
        ],
    },
    "Penal": {
        "cor": "#9f1239",
        "termos": [
            "penal", "criminal", "habeas corpus", "denúncia", "denuncia",
            "ação penal", "acao penal", "tribunal do júri", "tribunal do juri",
            "lavagem de dinheiro", "improbidade administrativa", "crime contra",
        ],
    },
    "Ambiental": {
        "cor": "#15803d",
        "termos": [
            "ambient", "licenciamento ambiental", "tac ambiental",
            "área de preservação", "area de preservacao", "ibama",
            "auto de infração ambiental", "auto de infracao ambiental",
            "compensação ambiental", "compensacao ambiental",
        ],
    },
    "Consumidor": {
        "cor": "#be185d",
        "termos": [
            "consumidor", "cdc", "código de defesa", "codigo de defesa",
            "procon", "vício do produto", "vicio do produto", "vício do serviço",
            "vicio do servico", "ação coletiva de consumo", "acao coletiva de consumo",
        ],
    },
}


def classificar_areas(titulo: str, descricao: str) -> list[str]:
    """Devolve lista de áreas jurídicas que o edital toca, com base em
    palavras-gatilho no título e na descrição. Pode devolver 0, 1 ou várias.
    Áreas vêm na ordem do dicionário AREAS_JURIDICAS."""
    texto = f"{titulo} {descricao}".lower()
    achadas = []
    for area, conf in AREAS_JURIDICAS.items():
        if any(termo.lower() in texto for termo in conf["termos"]):
            achadas.append(area)
    return achadas or ["Geral"]


# ===========================================================================
# COLETA
# ===========================================================================

def buscar_pncp(keyword: str, somente_abertos: bool) -> list[dict]:
    """
    Pagina a busca do PNCP por uma palavra-chave.

    Por padrão filtra editais com proposta aberta (status=recebendo_proposta).
    Se 'somente_abertos' for False, traz tudo (inclui já encerrados).
    """
    coletados: list[dict] = []
    for pagina in range(1, PAGINAS_POR_KEYWORD + 1):
        params = {
            "q": keyword,
            "tipos_documento": "edital",
            "ordenacao": "-data",
            "pagina": pagina,
            "tam_pagina": RESULTADOS_POR_PAGINA,
        }
        if somente_abertos:
            params["status"] = "recebendo_proposta"

        try:
            resp = requests.get(
                PNCP_SEARCH_URL,
                params=params,
                headers=HEADERS,
                timeout=TIMEOUT_SEGUNDOS,
                verify=True,         # (S1) verifica certificado SSL
                allow_redirects=False,  # (S3) não segue redirects
                stream=True,         # permite checar tamanho antes de carregar tudo
            )
            resp.raise_for_status()
            # (S2) lê limitado a LIMITE_RESPOSTA_BYTES bytes
            content = resp.raw.read(LIMITE_RESPOSTA_BYTES + 1, decode_content=True)
            if len(content) > LIMITE_RESPOSTA_BYTES:
                print(f"  [aviso] resposta excedeu {LIMITE_RESPOSTA_BYTES} bytes em '{keyword}' - ignorando")
                break
        except requests.RequestException as e:
            print(f"  [aviso] '{keyword}' pg{pagina}: {e}")
            break

        try:
            data = json.loads(content.decode("utf-8", errors="replace"))
        except (ValueError, UnicodeDecodeError):
            print(f"  [aviso] resposta não-JSON em '{keyword}'")
            break

        # validação básica da estrutura esperada
        if not isinstance(data, dict):
            print(f"  [aviso] resposta com estrutura inesperada em '{keyword}'")
            break

        items = data.get("items") or []
        if not items:
            break
        for it in items:
            it["_keyword"] = keyword
        coletados.extend(items)

        # se a página veio incompleta, não há próxima
        if len(items) < RESULTADOS_POR_PAGINA:
            break
        time.sleep(PAUSA_ENTRE_REQUESTS)
    return coletados


def coletar_tudo(somente_abertos: bool) -> list[dict]:
    print(f"\n[1/3] Coletando ({len(PALAVRAS_CHAVE)} palavras-chave) "
          f"{'[somente propostas abertas]' if somente_abertos else '[TUDO, incluindo encerrados]'}...")
    todos: list[dict] = []
    for kw in PALAVRAS_CHAVE:
        print(f"  '{kw}' ... ", end="", flush=True)
        r = buscar_pncp(kw, somente_abertos)
        print(f"{len(r)} encontrados")
        todos.extend(r)
        time.sleep(PAUSA_ENTRE_REQUESTS)
    print(f"  total bruto: {len(todos)}")
    return todos


# ===========================================================================
# DEDUPLICAÇÃO + NORMALIZAÇÃO
# ===========================================================================

def chave_unica(item: dict) -> str:
    return item.get("numero_controle_pncp") or item.get("id") or f"NA::{item.get('title','')}"


def deduplicar(items: list[dict]) -> list[dict]:
    print("\n[2/3] Deduplicando...")
    visto: dict[str, dict] = {}
    for it in items:
        ch = chave_unica(it)
        if ch in visto:
            kws = visto[ch].setdefault("_matched_keywords", [visto[ch].get("_keyword")])
            if it.get("_keyword") not in kws:
                kws.append(it.get("_keyword"))
        else:
            it["_matched_keywords"] = [it.get("_keyword")]
            visto[ch] = it
    print(f"  únicos: {len(visto)}")
    return list(visto.values())


def normalizar(item: dict) -> dict:
    """Padroniza campos para o dashboard, com base na resposta real do PNCP.
    Aplica sanitização (S5) e allowlist de URL (S4)."""
    item_url = item.get("item_url") or ""
    if item_url and not item_url.startswith("http"):
        url_montada = f"https://{PNCP_HOST}/app" + item_url
    else:
        url_montada = item_url or f"https://{PNCP_HOST}/app/editais"

    titulo_safe = texto_seguro(item.get("title"), 300) or "(sem título)"
    descricao_safe = texto_seguro(item.get("description"), 2000)
    return {
        "titulo": titulo_safe,
        "descricao": descricao_safe,
        "orgao": texto_seguro(item.get("orgao_nome"), 200),
        "unidade": texto_seguro(item.get("unidade_nome"), 200),
        "uf": texto_seguro(item.get("uf"), 4),
        "municipio": texto_seguro(item.get("municipio_nome"), 100),
        "esfera": texto_seguro(item.get("esfera_nome"), 30),
        "poder": texto_seguro(item.get("poder_nome"), 50),
        "modalidade": texto_seguro(item.get("modalidade_licitacao_nome"), 100),
        "situacao": texto_seguro(item.get("situacao_nome"), 60),
        "valor": item.get("valor_global"),
        "data_publicacao": texto_seguro(item.get("data_publicacao_pncp"), 30),
        "data_atualizacao": texto_seguro(item.get("data_atualizacao_pncp"), 30),
        "data_inicio_vigencia": texto_seguro(item.get("data_inicio_vigencia"), 30),
        "data_fim_vigencia": texto_seguro(item.get("data_fim_vigencia"), 30),
        "numero_controle": texto_seguro(item.get("numero_controle_pncp"), 60),
        "url": url_segura(url_montada),  # (S4)
        "matched_keywords": [texto_seguro(k, 80) for k in (item.get("_matched_keywords") or [item.get("_keyword")]) if k],
        "areas": classificar_areas(titulo_safe, descricao_safe),  # NOVO
    }


# ===========================================================================
# DASHBOARD HTML
# ===========================================================================

def fmt_data(s: str) -> str:
    if not s:
        return "—"
    s = str(s)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:26 if "." in s[:30] else 19], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return s[:10]


def fmt_valor(v) -> str:
    if v in (None, "", 0):
        return "—"
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return str(v)


COR_ESFERA = {
    "Federal": "#dc2626",
    "Estadual": "#0891b2",
    "Municipal": "#16a34a",
    "Distrital": "#7c3aed",
}


def renderizar_html(items: list[dict], somente_abertos: bool) -> str:
    items_norm = sorted(
        [normalizar(it) for it in items],
        key=lambda x: x["data_publicacao"] or "",
        reverse=True,
    )
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    linhas = []
    for it in items_norm:
        kws = ", ".join(it["matched_keywords"])
        cor_esfera = COR_ESFERA.get(it["esfera"], "#64748b")
        cidade_uf = f"{it['municipio']}/{it['uf']}" if it['uf'] else "—"
        # Tags de área jurídica (várias por edital, separadas por espaço)
        areas_tags = "".join(
            f'<span class="area-tag" style="background:{AREAS_JURIDICAS.get(a, {}).get("cor", "#64748b")}">{escape(a)}</span>'
            for a in it["areas"]
        )
        # data attribute para o filtro JS
        areas_data = "|".join(it["areas"])
        linhas.append(f"""
        <tr data-esfera="{escape(it['esfera'])}" data-uf="{escape(it['uf'])}" data-situacao="{escape(it['situacao'])}" data-areas="{escape(areas_data)}">
          <td><span class="tag" style="background:{cor_esfera}">{escape(it['esfera'] or '?')}</span></td>
          <td>
            <div class="areas-row">{areas_tags}</div>
            <a href="{escape(it['url'])}" target="_blank" rel="noopener noreferrer" class="titulo">
              {escape(it['titulo'][:200])}
            </a>
            <div class="desc">{escape(it['descricao'][:240])}{'...' if len(it['descricao'])>240 else ''}</div>
            <div class="meta">
              <span>🏛 {escape(it['orgao'][:80])}</span>
              <span>📍 {escape(cidade_uf)}</span>
              <span>🔑 {escape(kws)}</span>
            </div>
          </td>
          <td>{escape(it['modalidade'])}<div class="situacao">{escape(it['situacao'])}</div></td>
          <td class="valor">{fmt_valor(it['valor'])}</td>
          <td>
            <div><b>Pub:</b> {fmt_data(it['data_publicacao'])}</div>
            {('<div><b>Fim:</b> ' + fmt_data(it['data_fim_vigencia']) + '</div>') if it['data_fim_vigencia'] else ''}
          </td>
          <td><a href="{escape(it['url'])}" target="_blank" rel="noopener noreferrer" class="btn">Ver edital ↗</a></td>
        </tr>""")

    por_esfera = {}
    for i in items_norm:
        e = i["esfera"] or "?"
        por_esfera[e] = por_esfera.get(e, 0) + 1

    blocos_stats = "".join(
        f'<div class="stat"><div class="num" style="color:{COR_ESFERA.get(e, "#64748b")}">{n}</div>'
        f'<div class="lbl">{escape(e)}</div></div>'
        for e, n in sorted(por_esfera.items(), key=lambda x: -x[1])
    )

    titulo_filtro = "editais com proposta ABERTA" if somente_abertos else "todos os editais (abertos + encerrados)"

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Radar de Licitações</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<!-- (S7) Content Security Policy: bloqueia carregar/executar qualquer
     recurso externo. Apenas estilos/scripts inline (do próprio arquivo).
     Links navegam só para pncp.gov.br. -->
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'none';">
<meta http-equiv="X-Content-Type-Options" content="nosniff">
<meta name="referrer" content="no-referrer">
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #f7f8fa; color: #1a1a1a; margin: 0; padding: 24px; }}
  header {{ display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 24px; flex-wrap: wrap; gap: 12px; }}
  h1 {{ margin: 0; font-size: 24px; }}
  .sub {{ color: #6b7280; font-size: 13px; margin-top: 4px; }}
  .stats {{ display: flex; gap: 12px; flex-wrap: wrap; }}
  .stat {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px;
           padding: 10px 16px; min-width: 110px; }}
  .stat .num {{ font-size: 22px; font-weight: 600; }}
  .stat .lbl {{ font-size: 11px; color: #6b7280; text-transform: uppercase; }}
  .filters {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px;
              padding: 12px
