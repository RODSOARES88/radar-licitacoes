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

    return {
        "titulo": texto_seguro(item.get("title"), 300) or "(sem título)",
        "descricao": texto_seguro(item.get("description"), 2000),
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
        linhas.append(f"""
        <tr data-esfera="{escape(it['esfera'])}" data-uf="{escape(it['uf'])}" data-situacao="{escape(it['situacao'])}">
          <td><span class="tag" style="background:{cor_esfera}">{escape(it['esfera'] or '?')}</span></td>
          <td>
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
              padding: 12px 16px; margin-bottom: 16px; display: flex; gap: 16px; flex-wrap: wrap; }}
  .filters label {{ font-size: 13px; color: #374151; }}
  .filters input, .filters select {{
    padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 13px;
  }}
  table {{ width: 100%; background: white; border: 1px solid #e5e7eb;
           border-radius: 8px; border-collapse: separate; border-spacing: 0; overflow: hidden; }}
  th, td {{ padding: 12px; text-align: left; vertical-align: top;
            border-bottom: 1px solid #f3f4f6; font-size: 13px; }}
  th {{ background: #f9fafb; font-weight: 600; color: #374151;
        font-size: 12px; text-transform: uppercase; }}
  tr:last-child td {{ border-bottom: none; }}
  .titulo {{ color: #1d4ed8; text-decoration: none; font-weight: 600; }}
  .titulo:hover {{ text-decoration: underline; }}
  .desc {{ color: #4b5563; font-size: 12px; margin-top: 4px; line-height: 1.4; }}
  .meta {{ color: #6b7280; font-size: 12px; margin-top: 6px;
           display: flex; gap: 12px; flex-wrap: wrap; }}
  .tag {{ display: inline-block; color: white; padding: 2px 8px;
          border-radius: 4px; font-size: 11px; font-weight: 500; }}
  .situacao {{ font-size: 11px; color: #6b7280; margin-top: 4px; }}
  .valor {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
  .btn {{ display: inline-block; background: #1d4ed8; color: white;
          padding: 6px 12px; border-radius: 6px; text-decoration: none;
          font-size: 12px; white-space: nowrap; }}
  .btn:hover {{ background: #1e40af; }}
  .empty {{ text-align: center; padding: 40px; color: #6b7280; }}
</style>
</head>
<body>

<header>
  <div>
    <h1>📡 Radar de Licitações</h1>
    <div class="sub">Última atualização: {agora} • Fonte: PNCP • {titulo_filtro}</div>
  </div>
  <div class="stats">
    <div class="stat"><div class="num">{len(items_norm)}</div><div class="lbl">Total</div></div>
    {blocos_stats}
  </div>
</header>

<div class="filters">
  <label>🔍 Buscar: <input type="text" id="filter-text" placeholder="palavra, órgão, cidade..."></label>
  <label>Esfera:
    <select id="filter-esfera">
      <option value="">Todas</option>
      <option value="Federal">Federal</option>
      <option value="Estadual">Estadual</option>
      <option value="Municipal">Municipal</option>
      <option value="Distrital">Distrital</option>
    </select>
  </label>
  <label>UF:
    <select id="filter-uf">
      <option value="">Todas</option>
    </select>
  </label>
</div>

<table id="tbl">
  <thead>
    <tr>
      <th>Esfera</th>
      <th>Objeto / Órgão</th>
      <th>Modalidade</th>
      <th>Valor</th>
      <th>Datas</th>
      <th>Ação</th>
    </tr>
  </thead>
  <tbody>
    {''.join(linhas) if linhas else '<tr><td colspan="6" class="empty">Nenhum edital encontrado com as palavras-chave atuais.</td></tr>'}
  </tbody>
</table>

<script>
  const ufs = new Set();
  document.querySelectorAll('tr[data-uf]').forEach(tr => {{
    const uf = tr.dataset.uf;
    if (uf) ufs.add(uf);
  }});
  const selUf = document.getElementById('filter-uf');
  Array.from(ufs).sort().forEach(uf => {{
    const opt = document.createElement('option');
    opt.value = uf; opt.textContent = uf;
    selUf.appendChild(opt);
  }});

  function filtrar() {{
    const txt = document.getElementById('filter-text').value.toLowerCase();
    const esfera = document.getElementById('filter-esfera').value;
    const uf = document.getElementById('filter-uf').value;
    document.querySelectorAll('tbody tr').forEach(tr => {{
      const linha = tr.textContent.toLowerCase();
      const okTxt = !txt || linha.includes(txt);
      const okEsfera = !esfera || tr.dataset.esfera === esfera;
      const okUf = !uf || tr.dataset.uf === uf;
      tr.style.display = (okTxt && okEsfera && okUf) ? '' : 'none';
    }});
  }}
  document.getElementById('filter-text').addEventListener('input', filtrar);
  document.getElementById('filter-esfera').addEventListener('change', filtrar);
  document.getElementById('filter-uf').addEventListener('change', filtrar);
</script>

</body>
</html>
"""
    return html


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    ap = argparse.ArgumentParser(description="Radar de Licitações - PNCP")
    ap.add_argument("--abrir", action="store_true", help="Abre o HTML no browser ao terminar")
    ap.add_argument("--tudo", action="store_true",
                    help="Inclui editais sem proposta aberta também (default: só abertos)")
    args = ap.parse_args()

    somente_abertos = not args.tudo
    inicio = datetime.now(timezone.utc)
    brutos = coletar_tudo(somente_abertos)
    unicos = deduplicar(brutos)

    print(f"\n[3/3] Gerando saídas...")
    OUTPUT_JSON.write_text(
        json.dumps(
            {
                "gerado_em": inicio.isoformat(),
                "fonte": "PNCP",
                "filtro": "recebendo_proposta" if somente_abertos else "todos",
                "palavras_chave": PALAVRAS_CHAVE,
                "total": len(unicos),
                "items": [normalizar(it) for it in unicos],
            },
            ensure_ascii=False, indent=2, default=str,
        ),
        encoding="utf-8",
    )
    OUTPUT_HTML.write_text(renderizar_html(unicos, somente_abertos), encoding="utf-8")

    print(f"\n✓ Concluído.")
    print(f"  HTML: {OUTPUT_HTML}")
    print(f"  JSON: {OUTPUT_JSON}")
    print(f"  Total de editais únicos: {len(unicos)}")

    if args.abrir:
        webbrowser.open(OUTPUT_HTML.as_uri())


