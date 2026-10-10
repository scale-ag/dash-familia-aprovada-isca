# Dashboard de Captação de Leads · Nubia Oliveira

Dashboard **100% na nuvem** da **isca gratuita** (funil **raio-x**) de
**Nubia Oliveira**. Cruza a planilha de **Leads** (inscrições na isca, com
parâmetros UTM) com o investimento de mídia paga (**Meta Ads**) e calcula
**CPL, CTR, CPM, ConvLP** e a atribuição de leads por **campanha / conjunto /
anúncio**. Publicada no **GitHub Pages**, reconstrói sozinha a cada ~30 min,
disparada pelo **cron-job.org** — sem depender de nenhum PC ligado.

> **Isca gratuita:** não há critério de MQL, nem vendas/faturamento. O funil vai
> até o **Lead** (Gasto → Impressões → Cliques → Page Views → Leads).

**URL pública:** `https://scale-ag.github.io/dash-familia-aprovada-isca/`

---

## O que ela mostra

- **KPIs**: Gasto Total, Impressões, Cliques, Page Views, Leads, CPL, CPM, CTR, CPC, CPV, ConvLP.
- **Evolução diária**: gasto/dia, leads/dia, CPL/dia (barras de leads + linhas de gasto e CPL).
- **Distribuição de leads**: por origem (pago × orgânico), por posicionamento (utm_term),
  por plataforma (Instagram/Facebook/orgânico) e por anúncio (utm_content).
- **Cruzamento por campanha**: gasto (Meta Ads) × leads (planilha) → CPL por
  Campanha → Conjunto → Anúncio (tabelas hierárquicas com filtro cruzado).
- **Tabela de leads capturados** (e-mail e telefone **mascarados**, pois a página é pública).
- **Toggle de imposto da mídia paga** (opcional) e **modo claro/escuro**.
- **Aba Relatório**: painel de metas editável (Meta CPL) + Top Anúncios (ranqueados
  por volume de leads e menor CPL) + Insights de Tráfego (texto, opcional — ver
  `build/GUIA-RELATORIOS.md`).

## Atribuição de leads

Cada lead é atribuído a campanha/conjunto/anúncio pelos parâmetros UTM da landing
page: `utm_campaign` → **Campanha**, `utm_medium` → **Conjunto**, `utm_content` →
**Anúncio** (nomes idênticos ao Meta Ads). Leads sem UTM entram como **orgânico**
(`(sem campanha)`). Lógica em `build.py` → `process()`.

## Fontes de dados (somente leitura)

Duas planilhas independentes, lidas via **export CSV público**
(`.../export?format=csv&gid=...`). **Nada é escrito de volta.**

| Planilha | Spreadsheet ID | Aba (gid) | Uso |
|-----|-----|-----|-----|
| **Leads** | `1_pBhH2m3R1BR11kRdgq2cn_j3L2JaifO3ui3xFbnd28` | Leads (`0`) | fonte **principal** de leads: `data_inscricao`, `nome`, `email`, `telefone`, `utm_*` |
| **Meta Ads** (Extração Dashboard - Isca Out26) | `1BL0Lz6d5mDPhT77qEtBbIeN6oMyVN1fEmEQlTgLSSLY` | Página1 (`0`) | `Day`, `Campaign/Ad Set/Ad Name`, `Impressions`, `Link Clicks`, `Landing Page Views`, `Amount Spent` |

> ⚠️ Ambas as planilhas precisam estar compartilhadas como **"Qualquer pessoa com
> o link → Leitor"** — é assim que o GitHub Actions lê os CSVs.

---

## Arquitetura

```
cron-job.org  ──(POST workflow_dispatch a cada 30 min)──▶  GitHub Actions
                                                              │
                          build/build.py  lê os CSVs ◀────────┘
                                 │  cruza Leads × Meta Ads + calcula CPL
                                 ▼
                          dist/index.html  ──▶  deploy  ──▶  GitHub Pages (URL pública)
```

- `build/build.py` — baixa os 2 CSVs, cruza os dados, gera `dist/index.html`.
- `build/template.html` + `build/app.js` + `build/estilos.css` + `build/identidade-visual.css` — layout/gráficos/tema (Chart.js via CDN).
- `.github/workflows/deploy.yml` — roda o build e publica no Pages.

**Cache-bust:** a página usa `Cache-Control: no-cache`, mostra o horário do último
build, tem botão **Atualizar** e se recarrega sozinha (`?t=timestamp`) ~30 min após
aberta — sempre pegando a versão mais nova.

## Rodar localmente (opcional)

```bash
python build/build.py --out dist/index.html            # busca os CSVs ao vivo
# ou, com arquivos locais para teste:
python build/build.py --leads-file leads.csv --meta-file meta.csv --out dist/index.html
```

---

## Ativação (uma vez) e cron-job.org

O disparo por `workflow_dispatch` só funciona quando o workflow está na branch
**`main`**. Veja **`SETUP-CRON.md`** para o passo a passo e os valores exatos
(URL, headers e body) a colar no cron-job.org.

> ⚠️ **Segurança:** nunca comite tokens no repositório. Gere um token
> *fine-grained*, só com **Actions: read/write** neste repositório, e use-o
> apenas no cron-job.org.
