# Radar de Licitações

Robô que varre o **PNCP** (Portal Nacional de Contratações Públicas) diariamente em busca de editais com proposta aberta que casem com palavras-chave de um escritório de advocacia, e publica um dashboard navegável.

## Site público

O dashboard é atualizado automaticamente todo dia às 07:00 (horário de Brasília) e está em:

**https://USUARIO.github.io/REPO/**

(substitua `USUARIO` pelo seu nome de usuário do GitHub e `REPO` pelo nome do repositório)

## Como funciona

1. O GitHub Actions executa o script `radar_licitacoes.py` todo dia às 10:00 UTC.
2. O script consulta a API pública do PNCP filtrando por palavras-chave do escritório.
3. Gera `docs/index.html` com o dashboard atualizado.
4. O GitHub Pages serve o conteúdo da pasta `docs/` como site público.

## Personalizar palavras-chave

Edite o arquivo `radar_licitacoes.py`, procure por `PALAVRAS_CHAVE = [`, adicione/remova termos. Faça commit. O próximo run pega as novas palavras.

## Rodar manualmente (sem esperar 7h da manhã)

1. Vá na aba **Actions** do repositório
2. Clique no workflow **"Radar de Licitacoes (atualizacao diaria)"**
3. Clique em **"Run workflow"** → **"Run workflow"**
4. Em ~1 minuto, o site atualiza

## Segurança

Documentação detalhada em `SEGURANCA.md`. Resumo:

- Comunicação só com `pncp.gov.br` via HTTPS com verificação SSL
- Allowlist de URLs no dashboard (só links pra PNCP são renderizados)
- Content-Security-Policy estrita no HTML gerado
- Sem `eval`/`exec`/`shell`, sem acesso a dados sensíveis

## Stack

- Python 3.12 + biblioteca `requests`
- GitHub Actions (agendamento)
- GitHub Pages (hospedagem)
- Custo: zero
