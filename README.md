# Relatório vivo — Prince · Menina Vest

Relatório de mídia paga com dados atualizados diariamente. O `coletor.py` busca
métricas diárias das APIs e grava `data.json`; o `index.html` (autocontido,
Chart.js embutido) carrega o `data.json` e permite ao cliente escolher o período.

## Arquivos

| Arquivo | Função |
|---|---|
| `index.html` | O relatório. Carrega `data.json`; sem servidor, usa fallback embutido (30 dias, sem imagens). |
| `coletor.py` | Coleta diária: Meta Ads (Marketing API), Google Ads + GA4 (Windsor.ai), Bagy (pendente). Sem dependências externas. |
| `data.json` | Dados diários gerados pelo coletor (95 dias). Não editar à mão. |
| `analises.json` | Textos "Leitura da Prince" — **é aqui que a equipe edita as análises**. Entram no relatório na coleta seguinte (ou rode `python3 coletor.py`). |
| `.env` | Segredos locais (nunca vai para o git). Modelo em `.env.example`. |
| `.github/workflows/atualiza-dados.yml` | Job diário no GitHub Actions (06:00 São Paulo) que roda o coletor e commita o `data.json`. |
| `coleta.log` | Log das últimas execuções (não versionado). |

## Rodar localmente

```bash
cd ~/relatorio-prince
python3 coletor.py
python3 -m http.server 8123   # abrir http://localhost:8123
```

## Publicar no GitHub (uma vez)

1. Crie o repositório em https://github.com/new (sugestão de nome: `relatorio-menina-vest`).
   **Atenção:** GitHub Pages no plano gratuito exige repositório público — o relatório
   (com números do cliente) fica acessível a quem tiver o link. Para repositório
   privado com Pages é preciso GitHub Pro/Team.
2. No terminal:
   ```bash
   cd ~/relatorio-prince
   git remote add origin git@github.com:SEU_USUARIO/relatorio-menina-vest.git
   git push -u origin main
   ```
3. Secrets (Settings > Secrets and variables > Actions > New repository secret):
   - `META_ACCESS_TOKEN` — token de System User (ads_read), o mesmo do `.env`
   - `META_ACCOUNT_ID` — `act_1392587507727555`
   - `WINDSOR_API_KEY_GOOGLE_ADS` — chave da conta Windsor onde o Google Ads está conectado
   - `WINDSOR_API_KEY_GA4` — chave da conta Windsor onde o GA4 está conectado
   - `GOOGLE_ADS_CUSTOMER_ID` — `545-236-6470` (com hífens)
   - `GA4_PROPERTY_ID` — `416231535` (propriedade do www.meninavest.com.br; nome legado "Guia-se - Menina Veneno Jeans")
   - `BAGY_API_TOKEN` — quando a integração Bagy for ativada
4. Ative o Pages: Settings > Pages > Source: `Deploy from a branch` > `main` / `/ (root)`.
   O relatório fica em `https://SEU_USUARIO.github.io/relatorio-menina-vest/`.
5. Teste o job: aba Actions > "Atualiza dados do relatório" > Run workflow.

## Fontes pendentes

- **Google Ads e GA4**: conectar as contas no Windsor.ai (links de autorização
  gerados na configuração) e preencher `WINDSOR_API_KEY`. Na primeira execução
  com a chave, conferir o `coleta.log` — os nomes de campos do Windsor serão
  validados nessa primeira chamada real.
- **Bagy**: gerar token da API no painel da Bagy e preencher `BAGY_API_TOKEN`.
  A integração (faturamento, pedidos, pedidos aprovados) será implementada e
  validada quando o token existir — os cards da loja aparecem no relatório
  automaticamente quando os dados chegarem.

## Segurança

- Tokens só em `.env` (local) e Secrets (GitHub Actions). Nunca no HTML, no
  `data.json` nem em commits.
- O token Meta atual foi transmitido em chat — recomenda-se gerar um novo token
  de System User no Business Manager e substituí-lo no `.env` e nos Secrets.
