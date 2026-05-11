#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Radar v4.1 - PNCP completo + IA + prompt editavel"""

import argparse, json, re, sys, time, webbrowser, unicodedata
from datetime import datetime, timezone
from html import escape
from pathlib import Path

try:
    import requests
except ImportError:
    print("Instale: pip install requests"); sys.exit(1)

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
PAUSA = 0.4
LIMITE_BYTES = 5_000_000
TIMEOUT = 30
OUTPUT_DIR = Path(__file__).resolve().parent / "docs"
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_HTML = OUTPUT_DIR / "index.html"
OUTPUT_JSON = OUTPUT_DIR / "radar_licitacoes.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (RadarLicitacoes/8)", "Accept": "application/json"}

LUCRO_VERDE = 5000; LUCRO_AMARELO = 0; HOTEL_DIARIA = 250
CUSTO_VIAGEM_UF = {"MG":200,"SP":800,"RJ":800,"ES":800,"GO":800,"DF":800,"PR":1500,"SC":1500,"RS":1500,"MT":1500,"MS":1500,"BA":1500,"PE":2500,"CE":2500,"AL":2500,"SE":2500,"PB":2500,"RN":2500,"MA":2500,"PI":2500,"TO":3000,"PA":3500,"AP":3500,"AM":3500,"RR":3500,"AC":3500,"RO":3500}
CIDADES_BATEVOLTA_BH = {"belo horizonte","contagem","betim","nova lima","sabara","santa luzia","ribeirao das neves","vespasiano","lagoa santa","pedro leopoldo","itauna","divinopolis","sete lagoas","para de minas","itabirito","ouro preto","mariana","conselheiro lafaiete","itabira","caete","brumadinho","bom despacho","lavras","sao joao del rei","barbacena","juiz de fora","ipatinga","coronel fabriciano","timoteo","ibirite"}
PRESENCA_REGEX = [("Intenso",r"diari[ao]|todos os dias|2x|3x|duas vezes por semana|tres vezes por semana"),("Semanal",r"semanal|uma vez por semana|1x.*semana|por semana"),("Imersivo",r"uma semana por m[eê]s|imers[aã]o|1 semana mensal"),("Esporadico",r"mensal|uma vez por m[eê]s|1x.*m[eê]s|presencial|comparec|in loco|sede d[oa] [oó]rg[aã]o")]
PRESENCA_VIAGENS = {"Remoto":0,"Esporadico":1,"Semanal":4,"Intenso":16,"Imersivo":1}
PRESENCA_NOITES = {"Remoto":0,"Esporadico":0,"Semanal":0,"Intenso":8,"Imersivo":6}
EVENTO_REGEX = r"palestra|treinamento|workshop|semin[aá]rio|curso de|evento de"
REEMBOLSO_REGEX = r"reembols|ressarci|indeniza[cç][aã]o de despesas|passagens.*fornecidas"
CLIENTES_TROFEU = [(r"caixa econ[oô]mica","Caixa"),(r"banco do brasil","BB"),(r"petrobras","Petrobras"),(r"bndes","BNDES"),(r"banco central","Bacen"),(r"banco do nordeste|bnb","BNB"),(r"eletrobras","Eletrobras"),(r"correios|ect","Correios"),(r"embrapa","Embrapa"),(r"fnde","FNDE"),(r"receita federal","Receita Federal"),(r"inss","INSS"),(r"aneel","ANEEL"),(r"anatel","ANATEL"),(r"agu","AGU"),(r"ibge","IBGE")]

# PROMPT TEMPLATE - edite aqui pra customizar o perfil do escritorio.
# Use {TITULO} {ORGAO} {CIDADE_UF} {VALOR} {MODALIDADE} {SITUACAO} {URL} {DESCRICAO}
PROMPT_TEMPLATE = """Sou advogado de escritorio em Belo Horizonte/MG (escritorio pequeno-medio, ~5 advogados). Analise este edital do PNCP e me responda:

1) Vale a pena participar? Considere logistica (BH), perfil do escritorio, custo-beneficio.
2) Quais documentos e qualificacoes sao tipicamente exigidos nesse tipo de edital?
3) Riscos e pontos de atencao que voce nota.
4) Recomendacao final: PARTICIPAR ou PASSAR, e por que.

DADOS DO EDITAL:
Titulo: {TITULO}
Orgao: {ORGAO}
Localidade: {CIDADE_UF}
Valor estimado: {VALOR}
Modalidade: {MODALIDADE}
Situacao: {SITUACAO}
URL no PNCP: {URL}

Descricao/objeto: {DESCRICAO}

Para analise mais completa, baixe o PDF do edital no PNCP (link acima) e anexe aqui em seguida."""

AREAS_JURIDICAS = {
    "Tributario":{"cor":"#dc2626","termos":["tributari","fiscal","icms","iss","ipva","iptu","imposto","tributo","execucao fiscal","credito tributario","auto de infracao","isencao","refis"]},
    "Trabalhista":{"cor":"#ea580c","termos":["trabalhist","clt","verbas rescis","rescis","sindical","vinculo emprega","horas extras","fgts","estabilidade","negociacao coletiva","dissidio"]},
    "Previdenciario":{"cor":"#7c3aed","termos":["previdenciari","inss","aposentadoria","auxilio-doenca","beneficio previden","salario-maternidade","rgps","rpps"]},
    "Administrativo":{"cor":"#0891b2","termos":["administrativ","improbidade","lei 8429","concurso publico","servidor publico","tomada de contas","tcu","tribunal de contas"]},
    "Civel":{"cor":"#16a34a","termos":["indenizacao","danos morais","responsabilidade civil","obrigacao","execucao de titulo","cobranca","consignacao","usucapiao","despejo"]},
    "Empresarial":{"cor":"#1d4ed8","termos":["empresari","societari","falencia","recuperacao judicial","marca","patente","antitruste"]},
    "Penal":{"cor":"#9f1239","termos":["penal","criminal","habeas corpus","denuncia","acao penal","tribunal do juri","lavagem de dinheiro"]},
    "Ambiental":{"cor":"#15803d","termos":["ambient","licenciamento ambiental","ibama","compensacao ambiental"]},
    "Consumidor":{"cor":"#be185d","termos":["consumidor","cdc","codigo de defesa","procon","vicio do produto","vicio do servico"]},
}


def url_segura(url):
    if not isinstance(url, str): return f"https://{PNCP_HOST}/app"
    u = url.strip()
    if u.startswith(("https://pncp.gov.br/", "https://www.pncp.gov.br/")): return u
    return f"https://{PNCP_HOST}/app"


def texto_seguro(s, limite=5000):
    if s is None: return ""
    s = str(s)[:limite]
    return "".join(c for c in s if c == "\n" or c == "\t" or (ord(c) >= 32 and ord(c) != 127))


def normalizar_str(s):
    s = (s or "").lower()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def classificar_areas(titulo, descricao):
    texto = f"{titulo} {descricao}".lower()
    achadas = [a for a, c in AREAS_JURIDICAS.items() if any(t in texto for t in c["termos"])]
    return achadas or ["Geral"]


def e_servico_juridico(titulo, descricao):
    texto = (str(titulo or "") + " " + str(descricao or "")).lower()
    tem_jur = any(t in texto for t in ["advocac","advogad","juridic","consultoria juridica","consultoria jurídica","assessoria juridica","assessoria jurídica","servicos advocaticios","serviços advocatícios","servicos de advocacia","serviços de advocacia","escritorio de advocacia","escritório de advocacia","sociedade de advogados","patrocinio judicial","patrocínio judicial","representacao judicial","representação judicial","parecer juridico","parecer jurídico"])
    if not tem_jur: return False
    negativos = ["material de escritorio","material de escritório","veiculos","veículos","moveis","móveis","equipamentos de informatica","equipamentos de informática","impressao","impressão","limpeza","alimentacao","alimentação","uniformes","fardamento","papelaria","manutencao predial","manutenção predial","obras de construcao","obras de construção","merenda escolar","transporte escolar"]
    if any(neg in texto for neg in negativos): return False
    return True


def parse_data(s):
    if not s: return None
    s = str(s)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f","%Y-%m-%dT%H:%M:%S","%Y-%m-%dT%H:%M","%Y-%m-%d"):
        try: return datetime.strptime(s[:26 if "." in s[:30] else 19], fmt)
        except ValueError: continue
    return None


def fmt_brl(v):
    if v is None or v == 0: return "—"
    try: return f"R$ {float(v):,.0f}".replace(",","X").replace(".",",").replace("X",".")
    except: return "—"


def fmt_valor(v):
    if v in (None,"",0): return "—"
    try: return f"R$ {float(v):,.2f}".replace(",","X").replace(".",",").replace("X",".")
    except: return str(v)


def detectar_presenca(texto):
    t = normalizar_str(texto)
    for cat, regex in PRESENCA_REGEX:
        if re.search(regex, t): return cat
    return "Remoto"


def detectar_trofeu(orgao):
    o = normalizar_str(orgao)
    for regex, label in CLIENTES_TROFEU:
        if re.search(regex, o): return label
    return None


def analisar(item, titulo, descricao, orgao, uf, municipio, valor):
    texto = normalizar_str(f"{titulo} {descricao}")
    e_evento = bool(re.search(EVENTO_REGEX, texto))
    tem_reembolso = bool(re.search(REEMBOLSO_REGEX, texto))
    presenca = "Esporadico" if e_evento else detectar_presenca(texto)
    trofeu = detectar_trofeu(orgao)
    di = parse_data(item.get("data_inicio_vigencia"))
    df = parse_data(item.get("data_fim_vigencia"))
    if e_evento: meses = 0.1
    elif di and df: meses = max(1.0, (df-di).days/30.0)
    else: meses = 12.0
    vt = valor or 0
    vm = vt/meses if meses>0 and vt else 0
    mn = normalizar_str(municipio)
    if uf=="MG" and mn in CIDADES_BATEVOLTA_BH: cv = 100
    elif uf=="MG": cv = 350
    else: cv = CUSTO_VIAGEM_UF.get(uf, 1500)
    viagens = PRESENCA_VIAGENS.get(presenca, 0)
    noites = PRESENCA_NOITES.get(presenca, 0)
    cl = viagens*cv + noites*HOTEL_DIARIA
    ce = 0 if tem_reembolso else cl
    if not vt:
        lucro = None; bandeira = "cinza"
    elif e_evento:
        lucro = vt - (0 if tem_reembolso else cl)
        bandeira = "verde" if lucro>=LUCRO_VERDE else ("amarelo" if lucro>=LUCRO_AMARELO else "vermelho")
    else:
        lucro = vm - ce
        bandeira = "verde" if lucro>=LUCRO_VERDE else ("amarelo" if lucro>=LUCRO_AMARELO else "vermelho")
    if trofeu and bandeira=="vermelho": bandeira="amarelo"
    p = []
    p.append(f"{'Evento unico' if e_evento else f'Contrato {int(meses)}m'} em {municipio or '?'}/{uf or '?'}")
    if vt: p.append(f"valor {fmt_brl(vt)}" + (f" (~{fmt_brl(vm)}/mes)" if not e_evento and vm else ""))
    else: p.append("valor nao informado na busca")
    if presenca!="Remoto": p.append(f"presenca {presenca.lower()} ({viagens}x/mes)")
    else: p.append("sem presencial detectado")
    if tem_reembolso: p.append("despesas reembolsaveis")
    elif cl: p.append(f"logistica ~{fmt_brl(cl)}/mes")
    if trofeu: p.append(f"trofeu: {trofeu}")
    if lucro is not None:
        suf = "/mes" if not e_evento else ""
        p.append(f"<b>lucro ~{fmt_brl(lucro)}{suf}</b> (otimista)")
    return {"bandeira":bandeira,"resumo":". ".join(p)+".","lucro":lucro,"trofeu":trofeu}


def buscar_pncp(keyword, somente_abertos):
    coletados = []
    for pagina in range(1, PAGINAS_POR_KEYWORD+1):
        params = {"q":keyword,"tipos_documento":"edital","ordenacao":"-data","pagina":pagina,"tam_pagina":RESULTADOS_POR_PAGINA}
        if somente_abertos: params["status"]="recebendo_proposta"
        try:
            resp = requests.get(PNCP_SEARCH_URL, params=params, headers=HEADERS, timeout=TIMEOUT, verify=True, allow_redirects=False, stream=True)
            resp.raise_for_status()
            content = resp.raw.read(LIMITE_BYTES+1, decode_content=True)
            if len(content) > LIMITE_BYTES: break
        except requests.RequestException: break
        try: data = json.loads(content.decode("utf-8", errors="replace"))
        except (ValueError, UnicodeDecodeError): break
        if not isinstance(data, dict): break
        items = data.get("items") or []
        if not items: break
        for it in items: it["_keyword"] = keyword
        coletados.extend(items)
        if len(items) < RESULTADOS_POR_PAGINA: break
        time.sleep(PAUSA)
    return coletados


def coletar_tudo(somente_abertos):
    print(f"\n[1/3] Coletando ({len(PALAVRAS_CHAVE)} palavras)...")
    todos = []
    for kw in PALAVRAS_CHAVE:
        print(f"  '{kw}' ... ", end="", flush=True)
        r = buscar_pncp(kw, somente_abertos)
        print(f"{len(r)}")
        todos.extend(r); time.sleep(PAUSA)
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
        url_montada = f"https://{PNCP_HOST}/app" + item_url.replace("/compras/","/editais/")
    else: url_montada = item_url or f"https://{PNCP_HOST}/app/editais"
    titulo = texto_seguro(item.get("title"), 300) or "(sem titulo)"
    descricao = texto_seguro(item.get("description"), 2000)
    orgao = texto_seguro(item.get("orgao_nome"), 200)
    uf = texto_seguro(item.get("uf"), 4)
    municipio = texto_seguro(item.get("municipio_nome"), 100)
    valor = item.get("valor_global")
    a = analisar(item, titulo, descricao, orgao, uf, municipio, valor)
    return {"titulo":titulo,"descricao":descricao,"areas":classificar_areas(titulo, descricao),
        "orgao":orgao,"uf":uf,"municipio":municipio,
        "esfera":texto_seguro(item.get("esfera_nome"),30),
        "modalidade":texto_seguro(item.get("modalidade_licitacao_nome"),100),
        "situacao":texto_seguro(item.get("situacao_nome"),60),"valor":valor,
        "data_publicacao":texto_seguro(item.get("data_publicacao_pncp"),30),
        "data_fim_vigencia":texto_seguro(item.get("data_fim_vigencia"),30),
        "url":url_segura(url_montada),
        "matched_keywords":[texto_seguro(k,80) for k in (item.get("_matched_keywords") or [item.get("_keyword")]) if k],
        **a}


def fmt_data(s):
    if not s: return "—"
    d = parse_data(s)
    return d.strftime("%d/%m/%Y") if d else str(s)[:10]


COR_ESFERA = {"Federal":"#dc2626","Estadual":"#0891b2","Municipal":"#16a34a","Distrital":"#7c3aed"}
COR_BANDEIRA = {"verde":"#16a34a","amarelo":"#eab308","vermelho":"#dc2626","cinza":"#6b7280"}
EMOJI_BANDEIRA = {"verde":"🟢","amarelo":"🟡","vermelho":"🔴","cinza":"⚪"}


def renderizar_html(items, somente_abertos):
    items_norm = sorted([normalizar(it) for it in items],
        key=lambda x:({"verde":0,"amarelo":1,"cinza":2,"vermelho":3}[x["bandeira"]], -(x["lucro"] or -1e9)))
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    linhas = []
    for it in items_norm:
        kws = ", ".join(it["matched_keywords"])
        ce = COR_ESFERA.get(it["esfera"],"#64748b")
        cb = COR_BANDEIRA[it["bandeira"]]
        cidade_uf = f"{it['municipio']}/{it['uf']}" if it['uf'] else "—"
        at = "".join(f'<span class="area-tag" style="background:{AREAS_JURIDICAS.get(a,{}).get("cor","#64748b")}">{escape(a)}</span>' for a in it["areas"])
        ad = "|".join(it["areas"])
        th = f'<span class="trofeu">🏆 {escape(it["trofeu"])}</span>' if it["trofeu"] else ""
        fh = f'<div><b>Fim:</b> {fmt_data(it["data_fim_vigencia"])}</div>' if it["data_fim_vigencia"] else ""
        de = "..." if len(it["descricao"])>240 else ""
        ia_data = {"TITULO":it["titulo"][:200],"ORGAO":it["orgao"][:120],"CIDADE_UF":cidade_uf,
                   "VALOR":fmt_valor(it["valor"]),"URL":it["url"],"DESCRICAO":it["descricao"][:1500],
                   "MODALIDADE":it["modalidade"],"SITUACAO":it["situacao"]}
        ia_json = escape(json.dumps(ia_data, ensure_ascii=False))
        linha = (f'<tr data-esfera="{escape(it["esfera"])}" data-uf="{escape(it["uf"])}" data-areas="{escape(ad)}" data-bandeira="{it["bandeira"]}">'
                 f'<td><span class="tag" style="background:{ce}">{escape(it["esfera"] or "?")}</span></td>'
                 f'<td><div class="areas-row">{at}{th}</div>'
                 f'<a href="{escape(it["url"])}" target="_blank" rel="noopener noreferrer" class="titulo">{escape(it["titulo"][:200])}</a>'
                 f'<div class="desc">{escape(it["descricao"][:240])}{de}</div>'
                 f'<div class="meta"><span>🏛 {escape(it["orgao"][:80])}</span><span>📍 {escape(cidade_uf)}</span><span>🔑 {escape(kws)}</span></div></td>'
                 f'<td>{escape(it["modalidade"])}<div class="situacao">{escape(it["situacao"])}</div></td>'
                 f'<td class="valor">{fmt_valor(it["valor"])}</td>'
                 f'<td><div><b>Pub:</b> {fmt_data(it["data_publicacao"])}</div>{fh}</td>'
                 f'<td class="analise" style="border-left:4px solid {cb}">'
                 f'<div class="band-row"><span class="band-icon" style="background:{cb}">{EMOJI_BANDEIRA[it["bandeira"]]}</span></div>'
                 f'<div class="resumo">{it["resumo"]}</div></td>'
                 f'<td><a href="{escape(it["url"])}" target="_blank" rel="noopener noreferrer" class="btn">Ver edital</a>'
                 f'<button class="btn-ia" data-ia="{ia_json}" onclick="analisarIA(this)">🤖 Analisar IA</button></td></tr>')
        linhas.append(linha)
    linhas_html = "".join(linhas) if linhas else '<tr><td colspan="7" class="empty">Nenhum edital.</td></tr>'

    pe = {}
    for i in items_norm:
        e = i["esfera"] or "?"
        pe[e] = pe.get(e,0)+1
    blocos_e = "".join(f'<div class="stat"><div class="num" style="color:{COR_ESFERA.get(e,"#64748b")}">{n}</div><div class="lbl">{escape(e)}</div></div>' for e,n in sorted(pe.items(),key=lambda x:-x[1]))
    cbn = {"verde":0,"amarelo":0,"vermelho":0,"cinza":0}
    for i in items_norm: cbn[i["bandeira"]] += 1
    blocos_b = "".join(f'<div class="stat"><div class="num" style="color:{COR_BANDEIRA[k]}">{v}</div><div class="lbl">{EMOJI_BANDEIRA[k]} {k}</div></div>' for k,v in cbn.items())
    opcoes_areas = "".join(f'<option value="{escape(a)}">{escape(a)}</option>' for a in list(AREAS_JURIDICAS.keys())+["Geral"])
    tf = "editais ABERTOS - servicos juridicos" if somente_abertos else "todos"
    total = len(items_norm)
    prompt_safe = escape(PROMPT_TEMPLATE)

    css = "*{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f7f8fa;color:#1a1a1a;margin:0;padding:24px}header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px;flex-wrap:wrap;gap:12px}h1{margin:0;font-size:24px}.sub{color:#6b7280;font-size:13px;margin-top:4px}.stats{display:flex;gap:12px;flex-wrap:wrap}.stat{background:white;border:1px solid #e5e7eb;border-radius:8px;padding:10px 16px;min-width:90px}.stat .num{font-size:20px;font-weight:600}.stat .lbl{font-size:11px;color:#6b7280;text-transform:uppercase}.prompt-box{background:#fef3c7;border:1px solid #fbbf24;border-radius:8px;padding:12px 16px;margin-bottom:16px}.prompt-box summary{cursor:pointer;font-weight:600;color:#92400e}.prompt-box textarea{width:100%;min-height:200px;font-family:monospace;font-size:12px;padding:8px;border:1px solid #d1d5db;border-radius:6px;margin-top:8px;resize:vertical}.prompt-box .btns{margin-top:8px;display:flex;gap:8px;flex-wrap:wrap}.prompt-box button{padding:6px 12px;border:none;border-radius:6px;cursor:pointer;font-size:12px;font-weight:500}.filters{background:white;border:1px solid #e5e7eb;border-radius:8px;padding:12px 16px;margin-bottom:16px;display:flex;gap:16px;flex-wrap:wrap}.filters label{font-size:13px;color:#374151}.filters input,.filters select{padding:6px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px}table{width:100%;background:white;border:1px solid #e5e7eb;border-radius:8px;border-collapse:separate;border-spacing:0;overflow:hidden}th,td{padding:12px;text-align:left;vertical-align:top;border-bottom:1px solid #f3f4f6;font-size:13px}th{background:#f9fafb;font-weight:600;color:#374151;font-size:12px;text-transform:uppercase}tr:last-child td{border-bottom:none}.titulo{color:#1d4ed8;text-decoration:none;font-weight:600}.titulo:hover{text-decoration:underline}.desc{color:#4b5563;font-size:12px;margin-top:4px;line-height:1.4}.meta{color:#6b7280;font-size:12px;margin-top:6px;display:flex;gap:12px;flex-wrap:wrap}.tag{display:inline-block;color:white;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:500}.area-tag{display:inline-block;color:white;padding:1px 7px;border-radius:3px;font-size:10px;font-weight:600;margin-right:4px;margin-bottom:4px}.areas-row{margin-bottom:6px}.trofeu{display:inline-block;background:#fbbf24;color:#78350f;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:700;margin-left:4px}.situacao{font-size:11px;color:#6b7280;margin-top:4px}.valor{font-variant-numeric:tabular-nums;white-space:nowrap}.btn{display:inline-block;background:#1d4ed8;color:white;padding:6px 12px;border-radius:6px;text-decoration:none;font-size:12px;white-space:nowrap;margin-bottom:6px}.btn:hover{background:#1e40af}.btn-ia{display:block;background:#7c3aed;color:white;padding:6px 12px;border-radius:6px;border:none;font-size:12px;cursor:pointer;white-space:nowrap;font-weight:500;width:100%}.btn-ia:hover{background:#6d28d9}.empty{text-align:center;padding:40px;color:#6b7280}.analise{max-width:300px}.band-row{margin-bottom:6px}.band-icon{display:inline-block;width:28px;height:28px;border-radius:50%;text-align:center;line-height:28px;font-size:14px}.resumo{font-size:11.5px;color:#374151;line-height:1.5}"

    js = r"""
const PROMPT_DEFAULT = document.getElementById('prompt-template').value;
window.addEventListener('load', () => {
  const saved = localStorage.getItem('radarPrompt');
  if (saved) document.getElementById('prompt-template').value = saved;
});
function salvarPrompt(){
  localStorage.setItem('radarPrompt', document.getElementById('prompt-template').value);
  alert('Prompt salvo (so neste navegador).');
}
function resetarPrompt(){
  document.getElementById('prompt-template').value = PROMPT_DEFAULT;
  localStorage.removeItem('radarPrompt');
  alert('Prompt restaurado ao padrao.');
}
function copiarTemplate(){
  navigator.clipboard.writeText(document.getElementById('prompt-template').value).then(()=>alert('Template copiado!'));
}
function analisarIA(btn){
  const d = JSON.parse(btn.dataset.ia);
  let p = document.getElementById('prompt-template').value;
  Object.keys(d).forEach(k => { p = p.split('{' + k + '}').join(d[k]); });
  navigator.clipboard.writeText(p).then(()=>{
    alert('Prompt copiado! Abrindo Claude.ai - cole com Ctrl+V.');
    window.open('https://claude.ai/new', '_blank');
  });
}
const ufs=new Set();
document.querySelectorAll('tr[data-uf]').forEach(t=>{const u=t.dataset.uf;if(u)ufs.add(u)});
const sU=document.getElementById('filter-uf');
Array.from(ufs).sort().forEach(u=>{const o=document.createElement('option');o.value=u;o.textContent=u;sU.appendChild(o)});
function filtrar(){
  const txt=document.getElementById('filter-text').value.toLowerCase();
  const ba=document.getElementById('filter-band').value;
  const ar=document.getElementById('filter-area').value;
  const es=document.getElementById('filter-esfera').value;
  const uf=document.getElementById('filter-uf').value;
  document.querySelectorAll('tbody tr').forEach(t=>{
    const ln=t.textContent.toLowerCase();
    const ars=(t.dataset.areas||'').split('|');
    const a=!txt||ln.includes(txt);
    const b=!ba||t.dataset.bandeira===ba;
    const c=!ar||ars.includes(ar);
    const d=!es||t.dataset.esfera===es;
    const e=!uf||t.dataset.uf===uf;
    t.style.display=(a&&b&&c&&d&&e)?'':'none';
  });
}
['filter-text','filter-band','filter-area','filter-esfera','filter-uf'].forEach(i=>document.getElementById(i).addEventListener(i==='filter-text'?'input':'change',filtrar));
"""

    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>Radar de Licitacoes</title><meta name="viewport" content="width=device-width,initial-scale=1"><style>{css}</style></head><body><header><div><h1>📡 Radar de Licitacoes</h1><div class="sub">Atualizado: {agora} - PNCP - {tf}</div></div><div class="stats"><div class="stat"><div class="num">{total}</div><div class="lbl">Total</div></div>{blocos_e}{blocos_b}</div></header><details class="prompt-box"><summary>🤖 Prompt usado nas analises IA (clique para ver/editar)</summary><textarea id="prompt-template">{prompt_safe}</textarea><div class="btns"><button onclick="salvarPrompt()" style="background:#16a34a;color:white">Salvar minha versao</button><button onclick="resetarPrompt()" style="background:#6b7280;color:white">Restaurar padrao</button><button onclick="copiarTemplate()" style="background:#1d4ed8;color:white">Copiar template limpo</button></div><div style="font-size:11px;color:#92400e;margin-top:8px">Use {{TITULO}}, {{ORGAO}}, {{CIDADE_UF}}, {{VALOR}}, {{MODALIDADE}}, {{SITUACAO}}, {{URL}}, {{DESCRICAO}} - serao substituidos.</div></details><div class="filters"><label>🔍 Buscar: <input type="text" id="filter-text" placeholder="palavra, orgao..."></label><label>Bandeira: <select id="filter-band"><option value="">Todas</option><option value="verde">🟢 Verde</option><option value="amarelo">🟡 Amarelo</option><option value="vermelho">🔴 Vermelho</option><option value="cinza">⚪ Sem dados</option></select></label><label>Area: <select id="filter-area"><option value="">Todas</option>{opcoes_areas}</select></label><label>Esfera: <select id="filter-esfera"><option value="">Todas</option><option value="Federal">Federal</option><option value="Estadual">Estadual</option><option value="Municipal">Municipal</option><option value="Distrital">Distrital</option></select></label><label>UF: <select id="filter-uf"><option value="">Todas</option></select></label></div><table><thead><tr><th>Esfera</th><th>Objeto / Orgao</th><th>Modalidade</th><th>Valor</th><th>Datas</th><th>Analise</th><th>Acoes</th></tr></thead><tbody>{linhas_html}</tbody></table><script>{js}</script></body></html>"""


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
    print(f"  juridicos: {len(unicos)} (de {antes})")
    print(f"\n[3/3] Gerando saidas...")
    OUTPUT_JSON.write_text(json.dumps({
        "gerado_em": inicio.isoformat(), "fonte": "PNCP",
        "filtro": "juridico" if somente_abertos else "todos",
        "palavras_chave": PALAVRAS_CHAVE, "total": len(unicos),
        "items": [normalizar(it) for it in unicos],
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    OUTPUT_HTML.write_text(renderizar_html(unicos, somente_abertos), encoding="utf-8")
    print(f"\nConcluido. Total: {len(unicos)} editais.")
    if args.abrir: webbrowser.open(OUTPUT_HTML.as_uri())


if __name__ == "__main__":
    main()
