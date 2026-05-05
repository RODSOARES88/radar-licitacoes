# Segurança do Radar de Licitações

Este documento explica, em linguagem simples, **por que o Radar é seguro** e quais defesas estão integradas no código.

## Resumo de 1 linha

O Radar só conversa com **um único site público (pncp.gov.br)** e cria **dois arquivos** dentro da pasta `C:\RadarLicitacoes\`. Ele não tem acesso a banco, e-mail, navegador, senhas, câmera, ou qualquer outro dado seu.

## O que o Radar **NÃO PODE** fazer

| ❌ Não acessa | Por quê |
|---|---|
| Internet banking, e-CPF, e-CNPJ, contas bancárias | O script só fala com pncp.gov.br. Bancos exigem autenticação que o Radar nem tenta. |
| Senhas salvas no Chrome/Edge | O Radar nem abre o navegador. O Chrome separa em sandbox suas senhas — outro processo do Windows não vê. |
| Cookies, histórico de navegação, abas abertas | Idem acima. |
| E-mail, WhatsApp, Telegram | O Radar não tem credenciais nem APIs desses serviços. |
| Arquivos pessoais (Documentos, Fotos, Downloads) | O código só lê e escreve dentro da própria pasta `C:\RadarLicitacoes\`. |
| Câmera, microfone, webcam | Não importa nenhuma biblioteca que mexa nisso. |
| Outros computadores da rede | Só faz **uma** conexão de saída, para `pncp.gov.br`. |

## O que o Radar **FAZ**

1. Faz requisições HTTPS para `https://pncp.gov.br/api/search/` (mesma API que o site oficial usa).
2. Recebe a lista de editais em formato JSON.
3. Filtra por palavras-chave que **você define** no arquivo `radar_licitacoes.py`.
4. Cria/atualiza dois arquivos na própria pasta:
   - `radar_licitacoes.html` (o dashboard)
   - `radar_licitacoes.json` (os dados crus)

## Defesas integradas no código

Cada defesa tem um identificador (`S1`, `S2`...) que aparece como comentário no `radar_licitacoes.py` para você poder verificar.

| Id | Defesa | O que protege contra |
|---|---|---|
| **S1** | Verificação de certificado SSL/TLS | Ataque "man-in-the-middle" — alguém se passar pelo PNCP. |
| **S2** | Limite de tamanho de resposta (5 MB por chamada) | Resposta gigante que esgote memória do PC. |
| **S3** | Não segue redirecionamentos | Resposta tentando levar o script para outro site. |
| **S4** | Allowlist de URLs no dashboard | Mesmo se o PNCP fosse hackeado e devolvesse links maliciosos, o HTML só renderizaria links para `pncp.gov.br`. |
| **S5** | Limpeza de caracteres de controle | Strings com bytes "estranhos" que pudessem confundir o navegador. |
| **S6** | Escape HTML em todos os campos exibidos | Ataque "XSS" (script injetado em texto exibido). |
| **S7** | Content-Security-Policy estrita no HTML gerado | O dashboard, se aberto, NÃO consegue carregar nem executar scripts externos, conectar em outros servidores, nem ser embutido em outro site. |
| **S8** | Sem `eval`, `exec`, `shell=True`, ou execução dinâmica | Impede que dados externos virem código rodando. |
| **bonus** | Versão fixa do `requests` (2.32.3) baixada do PyPI oficial | Reduz risco de pacote substituído por versão maliciosa. |

## E se o próprio PNCP for hackeado?

O PNCP é um site do governo federal. Se for invadido, o pior cenário para o Radar é receber editais falsos / poluídos. Mesmo nesse caso:

- A defesa **S4** garante que os links no dashboard sempre apontam para `pncp.gov.br` (não levam você para sites de phishing).
- A defesa **S6** garante que nenhum texto recebido vire código executando no seu PC.
- A defesa **S7** garante que mesmo abrindo o HTML, nada externo é carregado.

O único impacto seria você **ver editais falsos** — mas você ia conferir antes de participar de qualquer um deles, certo?

## Boas práticas que dependem de você (não do Radar)

O Radar é seguro, mas a segurança total do escritório depende também de hábitos seus:

1. **Não baixe versões "modificadas" do Radar** de fontes que não sejam você mesmo. Mantenha cópia em pasta confiável.
2. **Mantenha o Windows atualizado** (atualizações de segurança).
3. **Use antivírus** (o Windows Defender que vem instalado já é bom).
4. **Cuidado com phishing por e-mail** — golpes que pedem dados bancários, links suspeitos.
5. **Use senhas fortes** + autenticação em 2 fatores nos sistemas do escritório (e-mail, sistema do tribunal, etc.).
6. **NÃO COLOQUE** dados bancários, senhas ou tokens dentro do `radar_licitacoes.py` — não tem motivo, ele não precisa de nada disso.

## Como auditar você mesmo

Tudo é texto puro. Você (ou um TI de confiança) pode abrir `radar_licitacoes.py` no Bloco de Notas e ler. Pesquise por:

- `requests.get` → todos os lugares onde o script faz conexões. Vai ver que TODOS apontam só pra `PNCP_SEARCH_URL` (que é `https://pncp.gov.br/api/search/`).
- `os.system`, `subprocess`, `eval`, `exec` → não existem. Não há execução dinâmica.
- `open(` → só usado para escrever os 2 arquivos de saída.

## Em caso de comportamento estranho

Se algum dia o Radar parecer fazer algo inesperado (criar arquivos diferentes, conexões com outros sites, antivírus reclamando), **PARE** de usar e me avise. É bem improvável, mas é assim que se faz. Você sempre pode deletar a pasta `C:\RadarLicitacoes\` inteira sem afetar nada do seu computador.
