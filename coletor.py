#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coletor diário do relatório vivo — Agência Prince · Menina Vest.

Busca métricas DIÁRIAS e grava data.json ao lado do index.html:
  - Meta Ads: direto na Marketing API (token de System User, escopo ads_read).
  - Google Ads e GA4: via Windsor.ai (exige WINDSOR_API_KEY e contas conectadas
    em onboard.windsor.ai). Enquanto não houver chave, a fonte fica "pendente".
  - Bagy: aguardando BAGY_API_TOKEN — integração será ativada quando o token existir.

Também re-embute um fallback compacto (últimos 30 dias, sem imagens) dentro do
index.html, entre os marcadores FALLBACK_INICIO/FALLBACK_FIM, para o relatório
abrir mesmo como arquivo local sem servidor.

Sem dependências externas (somente biblioteca padrão do Python 3.9+).
Segredos: apenas em .env local ou variáveis de ambiente (GitHub Actions Secrets).
"""

import base64
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.abspath(__file__))
JANELA_DIAS = 95            # cobre mês anterior completo + intervalos customizados
FATIA_DIAS = 32             # tamanho de cada chamada de insights (evita respostas gigantes)
TOP_CRIATIVOS_ASSETS = 20   # anúncios cujo criativo (imagem + link) é baixado
FALLBACK_DIAS = 30          # janela do fallback embutido no index.html
FALLBACK_TOP_ADS = 10       # anúncios mantidos no fallback
GA4_TOP_PAGINAS_DIA = 120   # páginas mantidas por dia (controla o tamanho do data.json)
FALLBACK_TOP_PAGINAS = 40   # páginas por dia no fallback embutido
TZ_SP = timezone(timedelta(hours=-3))

CLIENTE = "Menina Vest"
RESPONSAVEL = "Equipe Prince"

LOG = []


def log(msg):
    linha = f"[{datetime.now(TZ_SP).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(linha, flush=True)
    LOG.append(linha)


def carrega_env():
    caminho = os.path.join(RAIZ, ".env")
    if os.path.exists(caminho):
        for linha in open(caminho, encoding="utf-8"):
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def http_json(url, tentativas=3):
    ultimo = None
    for _ in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PrinceColetor/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:
            corpo = ""
            if hasattr(e, "read"):
                try:
                    corpo = e.read().decode(errors="replace")[:400]
                except Exception:
                    pass
            ultimo = f"{e} {corpo}"
    raise RuntimeError(f"Falha em {url.split('?')[0]}: {ultimo}")


def r2(x):
    return round(float(x) + 1e-9, 2)


# ============================================================
# META ADS (Marketing API, direto)
# ============================================================

def graph(caminho, params, pagina_tudo=False):
    ver = os.environ.get("META_API_VERSION", "v25.0")
    params = dict(params)
    params["access_token"] = os.environ["META_ACCESS_TOKEN"]
    url = f"https://graph.facebook.com/{ver}/{caminho}?" + urllib.parse.urlencode(params)
    if not pagina_tudo:
        return http_json(url)
    dados = []
    while url:
        resp = http_json(url)
        dados.extend(resp.get("data", []))
        url = resp.get("paging", {}).get("next")
    return dados


def acao(linha, tipos, campo="actions"):
    mapa = {a["action_type"]: a["value"] for a in (linha.get(campo) or [])}
    for t in tipos:
        if t in mapa:
            return float(mapa[t])
    return 0.0


def resultado_meta(linha):
    """Campo `results` da API (resultado padrão do objetivo de cada campanha)."""
    for r in linha.get("results") or []:
        for v in r.get("values") or []:
            try:
                return float(v.get("value", 0))
            except (TypeError, ValueError):
                return 0.0
    return None


def fatias(desde, ate):
    d1 = datetime.fromisoformat(desde).date()
    fim = datetime.fromisoformat(ate).date()
    while d1 <= fim:
        d2 = min(d1 + timedelta(days=FATIA_DIAS - 1), fim)
        yield d1.isoformat(), d2.isoformat()
        d1 = d2 + timedelta(days=1)


def insights_meta(nivel, campos_extra, desde, ate):
    act = os.environ["META_ACCOUNT_ID"]
    comuns = "spend,impressions,inline_link_clicks,actions,action_values"
    linhas = []
    com_results = True
    for f1, f2 in fatias(desde, ate):
        params = {
            "level": nivel,
            "time_increment": "1",
            "time_range": json.dumps({"since": f1, "until": f2}),
            "limit": "300",
        }
        campos = f"date_start,{campos_extra},{comuns}"
        try:
            params["fields"] = campos + (",results" if com_results else "")
            linhas.extend(graph(f"{act}/insights", params, pagina_tudo=True))
        except RuntimeError as e:
            if com_results and "results" in str(e).lower():
                # nível não aceita o campo `results`: refaz sem ele (fallback = compras)
                com_results = False
                params["fields"] = campos
                linhas.extend(graph(f"{act}/insights", params, pagina_tudo=True))
            else:
                raise
    return linhas


def coleta_meta(desde, ate):
    diario = {}
    campanhas = []
    for l in insights_meta("campaign", "campaign_name", desde, ate):
        d = l["date_start"]
        spend = float(l.get("spend") or 0)
        impress = int(float(l.get("impressions") or 0))
        cliques = int(float(l.get("inline_link_clicks") or 0))
        compras = acao(l, ["omni_purchase", "purchase"])
        receita = acao(l, ["omni_purchase", "purchase"], "action_values")
        res = resultado_meta(l)
        res = compras if res is None else res
        campanhas.append({
            "date": d,
            "nome": l.get("campaign_name", "—"),
            "valorUsado": r2(spend),
            "resultados": r2(res),
            "cliquesLink": cliques,
            "impressoes": impress,
            "receita": r2(receita),
        })
        agg = diario.setdefault(d, {
            "spend": 0.0, "impressoes": 0, "cliquesLink": 0, "lpv": 0,
            "atc": 0, "checkout": 0, "compras": 0, "receita": 0.0, "resultados": 0.0,
        })
        agg["spend"] = r2(agg["spend"] + spend)
        agg["impressoes"] += impress
        agg["cliquesLink"] += cliques
        agg["lpv"] += int(acao(l, ["landing_page_view", "omni_landing_page_view"]))
        agg["atc"] += int(acao(l, ["omni_add_to_cart", "add_to_cart"]))
        agg["checkout"] += int(acao(l, ["initiate_checkout", "omni_initiated_checkout"]))
        agg["compras"] += int(compras)
        agg["receita"] = r2(agg["receita"] + receita)
        agg["resultados"] = r2(agg["resultados"] + res)

    criativos = []
    for l in insights_meta("ad", "ad_id,ad_name", desde, ate):
        compras = acao(l, ["omni_purchase", "purchase"])
        res = resultado_meta(l)
        criativos.append({
            "date": l["date_start"],
            "ad_id": l.get("ad_id", ""),
            "nome": l.get("ad_name", "—"),
            "valorUsado": r2(float(l.get("spend") or 0)),
            "resultados": r2(compras if res is None else res),
            "cliquesLink": int(float(l.get("inline_link_clicks") or 0)),
            "impressoes": int(float(l.get("impressions") or 0)),
            "receita": r2(acao(l, ["omni_purchase", "purchase"], "action_values")),
        })

    log(f"Meta OK: {len(diario)} dias, {len(campanhas)} linhas de campanha, {len(criativos)} linhas de anúncio")
    return diario, campanhas, criativos


def coleta_assets_criativos(criativos):
    """Imagem (base64, ~600px) e link do anúncio para os top anúncios da janela."""
    total = {}
    for c in criativos:
        t = total.setdefault(c["ad_id"], {"resultados": 0.0})
        t["resultados"] += c["resultados"]
    top = sorted(total, key=lambda k: -total[k]["resultados"])[:TOP_CRIATIVOS_ASSETS]

    assets = {}
    for ad_id in top:
        if not ad_id:
            continue
        try:
            ad = graph(ad_id, {"fields": "preview_shareable_link,creative{id,effective_object_story_id}"})
            link = ad.get("preview_shareable_link")
            creative = ad.get("creative") or {}
            story = creative.get("effective_object_story_id") or ""
            if not link and "_" in story:
                pagina, post = story.split("_", 1)
                link = f"https://www.facebook.com/{pagina}/posts/{post}"
            img = None
            if creative.get("id"):
                cr = graph(creative["id"], {
                    "fields": "image_url,thumbnail_url",
                    "thumbnail_width": "600", "thumbnail_height": "600",
                })
                url_img = cr.get("image_url") or cr.get("thumbnail_url")
                if url_img:
                    req = urllib.request.Request(url_img, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=90) as r:
                        bruto = r.read()
                        mime = (r.headers.get("Content-Type") or "image/jpeg").split(";")[0]
                    if 0 < len(bruto) < 900_000:
                        img = f"data:{mime};base64," + base64.b64encode(bruto).decode()
            assets[ad_id] = {"img": img, "link": link}
        except Exception as e:
            log(f"AVISO criativo {ad_id}: {e}")
            assets[ad_id] = {"img": None, "link": None}
    log(f"Criativos: assets de {len(assets)} anúncios baixados")
    return assets


# ============================================================
# GOOGLE ADS e GA4 (via Windsor.ai)
# ============================================================

def windsor(conector, chave_env, conjuntos_de_campos, desde, ate, conta):
    # uma conta Windsor (e portanto uma chave) por conector; WINDSOR_API_KEY é fallback comum
    chave = os.environ.get(chave_env, "") or os.environ.get("WINDSOR_API_KEY", "")
    if not chave:
        return None
    erro = None
    for campos in conjuntos_de_campos:
        # tenta restrito à conta; se o formato do id divergir do esperado pelo
        # Windsor, repete sem select_accounts (a chave só enxerga a conta certa)
        for com_conta in ([True, False] if conta else [False]):
            try:
                params = {
                    "api_key": chave,
                    "date_from": desde,
                    "date_to": ate,
                    "fields": ",".join(campos),
                }
                if com_conta:
                    params["select_accounts"] = conta
                url = f"https://connectors.windsor.ai/{conector}?" + urllib.parse.urlencode(params)
                resp = http_json(url)
                dados = resp.get("data") if isinstance(resp, dict) else resp
                if isinstance(dados, list):
                    if conta and not com_conta:
                        log(f"AVISO {conector}: select_accounts={conta} não bateu; usando todas as contas da chave")
                    return dados
                erro = f"resposta inesperada: {str(resp)[:200]}"
            except RuntimeError as e:
                erro = str(e)
    raise RuntimeError(f"Windsor {conector}: {erro}")


def coleta_google(desde, ate):
    conjuntos = [
        ["date", "campaign", "clicks", "spend", "impressions", "conversions", "conversion_value"],
        ["date", "campaign", "clicks", "spend", "impressions", "conversions", "totalconversionvalue"],
    ]
    linhas = windsor("google_ads", "WINDSOR_API_KEY_GOOGLE_ADS", conjuntos, desde, ate,
                     os.environ.get("GOOGLE_ADS_CUSTOMER_ID", ""))
    if linhas is None:
        log("PENDENTE Google Ads: defina WINDSOR_API_KEY_GOOGLE_ADS e conecte a conta em onboard.windsor.ai")
        return None, []
    diario = {}
    campanhas = []
    for l in linhas:
        d = str(l.get("date", ""))[:10]
        custo = float(l.get("spend") or 0)
        cliques = int(float(l.get("clicks") or 0))
        impress = int(float(l.get("impressions") or 0))
        conv = float(l.get("conversions") or 0)
        valor = float(l.get("conversion_value") or l.get("totalconversionvalue") or 0)
        campanhas.append({
            "date": d, "nome": l.get("campaign", "—"), "custo": r2(custo),
            "cliques": cliques, "conversoes": r2(conv), "valorConversao": r2(valor),
            "impressoes": impress,
        })
        agg = diario.setdefault(d, {"custo": 0.0, "cliques": 0, "impressoes": 0,
                                    "conversoes": 0.0, "valorConversao": 0.0})
        agg["custo"] = r2(agg["custo"] + custo)
        agg["cliques"] += cliques
        agg["impressoes"] += impress
        agg["conversoes"] = r2(agg["conversoes"] + conv)
        agg["valorConversao"] = r2(agg["valorConversao"] + valor)
    log(f"Google Ads OK (Windsor): {len(diario)} dias, {len(campanhas)} linhas de campanha")
    return diario, campanhas


def coleta_ga4(desde, ate):
    # "conversoes" = transactions (compras): o campo conversions bruto desta
    # propriedade conta todos os key events e supera as sessões (taxa > 100%)
    conjuntos = [
        ["date", "landing_page", "sessions", "transactions"],
    ]
    linhas = windsor("googleanalytics4", "WINDSOR_API_KEY_GA4", conjuntos, desde, ate,
                     os.environ.get("GA4_PROPERTY_ID", ""))
    if linhas is None:
        log("PENDENTE GA4: defina WINDSOR_API_KEY_GA4 e conecte a propriedade em onboard.windsor.ai")
        return None
    paginas = []
    for l in linhas:
        paginas.append({
            "date": str(l.get("date", ""))[:10],
            "pagina": l.get("landing_page") or "—",
            "sessoes": int(float(l.get("sessions") or 0)),
            "conversoes": int(float(l.get("transactions") or 0)),
        })
    log(f"GA4 OK (Windsor): {len(paginas)} linhas de página")
    return enxuga_ga4(paginas, GA4_TOP_PAGINAS_DIA)


def enxuga_ga4(paginas, top_por_dia):
    """Mantém só as top páginas por sessões de cada dia — a cauda longa de
    páginas com 1-2 sessões não aparece no relatório e triplicava o data.json."""
    por_dia = {}
    for p in paginas:
        por_dia.setdefault(p["date"], []).append(p)
    enxuto = []
    for d in sorted(por_dia):
        enxuto.extend(sorted(por_dia[d], key=lambda p: -p["sessoes"])[:top_por_dia])
    if len(enxuto) < len(paginas):
        log(f"GA4: {len(paginas)} linhas reduzidas a {len(enxuto)} (top {top_por_dia} páginas/dia)")
    return enxuto


# ============================================================
# BAGY — aguardando token da API (não implementado de propósito:
# endpoints serão validados com o token real antes de entrar no ar)
# ============================================================

def coleta_bagy(desde, ate):
    if not os.environ.get("BAGY_API_TOKEN"):
        log("PENDENTE Bagy: defina BAGY_API_TOKEN (painel Bagy > Integrações > API)")
        return None
    log("AVISO Bagy: token presente, mas a integração ainda não foi implementada/validada")
    return None


# ============================================================
# MONTAGEM DO data.json + fallback embutido no index.html
# ============================================================

def monta_dados():
    hoje = datetime.now(TZ_SP).date()
    ate = (hoje - timedelta(days=1)).isoformat()          # até ontem (último dia completo)
    desde = (hoje - timedelta(days=JANELA_DIAS)).isoformat()
    log(f"Janela de coleta: {desde} a {ate}")

    meta_diario, meta_campanhas, criativos = coleta_meta(desde, ate)
    assets = coleta_assets_criativos(criativos)

    google_diario, google_campanhas = None, []
    try:
        google_diario, google_campanhas = coleta_google(desde, ate)
    except Exception as e:
        log(f"ERRO Google Ads: {e}")

    ga4_paginas = None
    try:
        ga4_paginas = coleta_ga4(desde, ate)
    except Exception as e:
        log(f"ERRO GA4: {e}")

    bagy = coleta_bagy(desde, ate)

    datas = sorted(set(meta_diario) | set(google_diario or {}))
    daily = [{
        "date": d,
        "meta": meta_diario.get(d),
        "google": (google_diario or {}).get(d),
        "bagy": None if bagy is None else bagy.get(d),
    } for d in datas]

    analises = {}
    caminho_analises = os.path.join(RAIZ, "analises.json")
    if os.path.exists(caminho_analises):
        analises = json.load(open(caminho_analises, encoding="utf-8"))

    return {
        "updated_at": datetime.now(TZ_SP).isoformat(timespec="minutes"),
        "cliente": CLIENTE,
        "responsavel": RESPONSAVEL,
        "fontes": {
            "meta": {"estado": "ok"},
            "google": {"estado": "ok" if google_diario else "pendente",
                       "motivo": None if google_diario else "Conectar Google Ads no Windsor.ai (chave WINDSOR_API_KEY_GOOGLE_ADS)"},
            "ga4": {"estado": "ok" if ga4_paginas else "pendente",
                    "motivo": None if ga4_paginas else "Conectar GA4 no Windsor.ai (chave WINDSOR_API_KEY_GA4)"},
            "bagy": {"estado": "pendente",
                     "motivo": "Integração Bagy aguardando BAGY_API_TOKEN"},
        },
        "daily": daily,
        "meta_campanhas": meta_campanhas,
        "google_campanhas": google_campanhas,
        "criativos": criativos,
        "criativos_assets": assets,
        "ga4_paginas": ga4_paginas or [],
        "analises": analises,
    }


def monta_fallback(dados):
    """Versão compacta (30 dias, sem imagens, top 10 anúncios) embutida no HTML."""
    if not dados["daily"]:
        return dados
    corte = (datetime.fromisoformat(dados["daily"][-1]["date"]) -
             timedelta(days=FALLBACK_DIAS - 1)).date().isoformat()
    recorta = lambda linhas: [l for l in linhas if l["date"] >= corte]
    criativos = recorta(dados["criativos"])
    total = {}
    for c in criativos:
        total[c["ad_id"]] = total.get(c["ad_id"], 0) + c["resultados"]
    top_ads = set(sorted(total, key=lambda k: -total[k])[:FALLBACK_TOP_ADS])
    fb = dict(dados)
    fb["daily"] = [d for d in dados["daily"] if d["date"] >= corte]
    fb["meta_campanhas"] = recorta(dados["meta_campanhas"])
    fb["google_campanhas"] = recorta(dados["google_campanhas"])
    fb["criativos"] = [c for c in criativos if c["ad_id"] in top_ads]
    fb["criativos_assets"] = {k: {"img": None, "link": v.get("link")}
                              for k, v in dados["criativos_assets"].items() if k in top_ads}
    fb["ga4_paginas"] = enxuga_ga4(recorta(dados["ga4_paginas"]), FALLBACK_TOP_PAGINAS)
    fb["fallback"] = True
    return fb


def embute_fallback(dados):
    caminho = os.path.join(RAIZ, "index.html")
    if not os.path.exists(caminho):
        log("AVISO: index.html não encontrado, fallback não embutido")
        return
    html = open(caminho, encoding="utf-8").read()
    bloco = ("/*FALLBACK_INICIO*/const DADOS_FALLBACK=" +
             json.dumps(monta_fallback(dados), ensure_ascii=False, separators=(",", ":")) +
             ";/*FALLBACK_FIM*/")
    novo, n = re.subn(r"/\*FALLBACK_INICIO\*/.*?/\*FALLBACK_FIM\*/", lambda _: bloco, html, flags=re.S)
    if n == 1:
        open(caminho, "w", encoding="utf-8").write(novo)
        log("Fallback embutido no index.html")
    else:
        log(f"AVISO: marcadores de fallback não encontrados (n={n}); index.html intocado")


def grava_log():
    caminho = os.path.join(RAIZ, "coleta.log")
    antigas = []
    if os.path.exists(caminho):
        antigas = open(caminho, encoding="utf-8").read().splitlines()
    linhas = (antigas + LOG)[-500:]
    open(caminho, "w", encoding="utf-8").write("\n".join(linhas) + "\n")


def principal():
    carrega_env()
    try:
        dados = monta_dados()
        caminho = os.path.join(RAIZ, "data.json")
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
        log(f"data.json gravado ({os.path.getsize(caminho) // 1024} KB)")
        embute_fallback(dados)
        log("SUCESSO")
    except Exception as e:
        log(f"ERRO FATAL: {e}")
        raise
    finally:
        grava_log()


if __name__ == "__main__":
    principal()
