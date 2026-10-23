"""
Extrator de remunerações do eSocial (modo CDP)
===============================================
Pré-requisito:
    Abrir o Chrome manualmente com debugging remoto e logar com certificado:

    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" ^
      --remote-debugging-port=9222 ^
      --user-data-dir="C:\\esocial_perfil_chrome" ^
      --profile-directory="Default"

Uso:
    python extrair.py                 # roda todos os meses de MESES_A_EXECUTAR
    python extrair.py 4               # roda só abril/2026 (teste)
"""
import re
import sys
import time
from pathlib import Path
from datetime import datetime

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ═══════════════ CONFIG (nível de módulo) ═══════════════
BASE = "https://www.esocial.gov.br"
URL_GESTAO = (
    f"{BASE}/portal/FolhaPagamento/GestaoFolha"
    f"?Competencia=202604&AbaAtiva=tabFolhaComDARF"
)

ANO = 2026
MESES_A_EXECUTAR = [(ANO, 4), (ANO, 5), (ANO, 6)]

# None = todos os trabalhadores. Use um inteiro para testar rápido.
MAX_TRABALHADORES_POR_MES = None

# ⚠️ Constante de módulo — usada por conectar_chrome_existente() e main()
CDP_URL = "http://localhost:9222"

SAIDA = Path("saida")
SAIDA.mkdir(exist_ok=True)
LOG_FILE = SAIDA / "progresso.log"


# ═══════════════ HELPERS ═══════════════
def log(msg: str) -> None:
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} | {msg}\n")


def cpf_para_url(cpf: str) -> str:
    return str(int(re.sub(r"\D", "", cpf)))


def url_lista(ano: int, mes: int) -> str:
    return (
        f"{BASE}/portal/FolhaPagamento/ListaRemuneracao"
        f"?Competencia={ano}{mes:02d}&Tipo=1200&PossuiDae=False"
    )


def url_remuneracao(cpf: str, ano: int, mes: int) -> str:
    return (
        f"{BASE}/portal/FolhaPagamento/RemuneracaoCompleto"
        f"?cpf={cpf_para_url(cpf)}&competencia={ano}{mes:02d}"
        f"&possuiDae=False&tipo=1200&visualizar=true"
    )


def valor_para_float(txt: str):
    if not txt or txt.strip() in ("-", "_", ""):
        return None
    try:
        return float(txt.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def sessao_ok(page) -> bool:
    u = page.url.lower()
    return not ("login" in u or "acesso.gov" in u or "/sso/" in u)


# ═══════════════ CONEXÃO AO CHROME VIA CDP ═══════════════
def conectar_chrome_existente(p):
    """Conecta ao Chrome já aberto (que você logou manualmente)."""
    try:
        browser = p.chromium.connect_over_cdp(CDP_URL)
    except Exception as e:
        raise SystemExit(
            f"❌ Não consegui conectar em {CDP_URL}.\n"
            f"   Abra o Chrome com --remote-debugging-port=9222 e faça login.\n"
            f"   Erro: {e}"
        )
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return browser, ctx, page


# ═══════════════ COLETA DE TRABALHADORES ═══════════════
def coletar_trabalhadores(page, ano: int, mes: int) -> list[dict]:
    page.goto(url_lista(ano, mes))
    page.wait_for_load_state("networkidle")
    time.sleep(1)

    if not sessao_ok(page):
        raise RuntimeError("Sessão expirada ao carregar a lista.")

    trabalhadores, pagina = [], 1

    while True:
        try:
            page.wait_for_selector('td[data-col="CPF"]', timeout=8000)
        except PWTimeout:
            break

        linhas = page.locator('tr:has(td[data-col="CPF"])').all()
        for linha in linhas:
            try:
                cpf = linha.locator('td[data-col="CPF"]').first.inner_text().strip()
                nome = linha.locator('td[data-col="Nome"]').first.inner_text().strip()
                if cpf:
                    trabalhadores.append({"cpf": cpf, "nome": nome})
            except Exception:
                pass

        log(
            f"    página {pagina}: +{len(linhas)} linhas "
            f"({len(trabalhadores)} acumulados)"
        )

        try:
            prox = page.locator("#proxima-pagina")
            if prox.count() == 0 or not prox.is_visible():
                break
            prox.click()
            page.wait_for_load_state("networkidle")
            time.sleep(0.8)
            pagina += 1
        except Exception:
            break

    return trabalhadores


# ═══════════════ EXTRAÇÃO DE RUBRICAS ═══════════════
def extrair_metadata(painel) -> dict:
    def txt(sel: str) -> str:
        try:
            loc = painel.locator(sel)
            return loc.first.inner_text().strip() if loc.count() else ""
        except Exception:
            return ""

    return {
        "Demonstrativo":   txt(".identificador-demonstrativo .valor"),
        "Categoria":       txt(".categoria .valor"),
        "Estabelecimento": txt(".estabelecimento .valor"),
        "Lotação":         txt(".lotacao .valor"),
        "Matrícula":       txt(".matricula .valor"),
    }


def extrair_rubricas(page) -> list[dict]:
    page.wait_for_load_state("networkidle")

    if page.locator("div.painel-remuneracao").count() == 0:
        return []

    resultados = []
    paineis = page.locator("div.painel-remuneracao").all()
    log(f"    {len(paineis)} demonstrativo(s)")

    for painel in paineis:
        meta = extrair_metadata(painel)

        try:
            info = painel.locator(
                "xpath=following-sibling::div[contains(@class,'informacao-demonstrativo')][1]"
            )
            if info.count() == 0:
                continue
            info = info.first

            tabela = info.locator("table").first
            if tabela.count() == 0:
                log(f"      ⚠️ Sem tabela em {meta['Demonstrativo']}")
                continue

            for linha in tabela.locator("tbody tr").all():
                def cel(col: str) -> str:
                    try:
                        td = linha.locator(f'td[data-col="{col}"]')
                        return td.first.inner_text().strip() if td.count() else ""
                    except Exception:
                        return ""

                registro = {
                    **meta,
                    "Tabela":           cel("Tabela"),
                    "Código":           cel("Código"),
                    "Tipo":             cel("Tipo"),
                    "Descrição":        cel("Descrição"),
                    "Natureza Rubrica": cel("Natureza Rubrica"),
                    "InCp":             cel("InCp"),
                    "InFGTS":           cel("InFGTS"),
                    "InPis":            cel("InPis"),
                    "Quantidade":       cel("Quantidade"),
                    "Número contrato":  cel("Número contrato"),
                    "Fator":            cel("Fator"),
                    "Valor Unitário":   cel("Valor Unitário"),
                    "Valor":            cel("Valor"),
                    "IndIR":            cel("IndIR"),
                }
                registro["ValorNum"] = valor_para_float(registro["Valor"])
                registro["QuantidadeNum"] = valor_para_float(registro["Quantidade"])
                resultados.append(registro)

        except Exception as e:
            log(f"      ⚠️ Erro no demonstrativo: {e}")

    return resultados


# ═══════════════ MAIN (única) ═══════════════
def main():
    meses = MESES_A_EXECUTAR
    if len(sys.argv) > 1:
        meses = [(ANO, int(sys.argv[1]))]

    log(f"▶️ Conectando ao Chrome em {CDP_URL}...")

    todos = []
    with sync_playwright() as p:
        browser, ctx, page = conectar_chrome_existente(p)

        page.goto(URL_GESTAO)
        page.wait_for_load_state("networkidle")

        if not sessao_ok(page):
            input(
                "👉 Você não está logado. Faça login com o certificado no Chrome aberto "
                "e pressione ENTER aqui no terminal..."
            )
            page.goto(URL_GESTAO)
            page.wait_for_load_state("networkidle")
            if not sessao_ok(page):
                raise SystemExit("❌ Ainda sem sessão. Abortando.")

        log("✅ Sessão detectada. Começando extração...")

        for ano, mes in meses:
            log(f"\n══════ {mes:02d}/{ano} ══════")
            try:
                trabalhadores = coletar_trabalhadores(page, ano, mes)
            except Exception as e:
                log(f"  ❌ Falha ao coletar: {e}")
                continue

            if not trabalhadores:
                log("  (sem trabalhadores)")
                continue

            if MAX_TRABALHADORES_POR_MES:
                trabalhadores = trabalhadores[:MAX_TRABALHADORES_POR_MES]
                log(f"  ⚠️ Modo teste: {len(trabalhadores)} trabalhadores")

            for i, t in enumerate(trabalhadores, 1):
                log(f"  [{i}/{len(trabalhadores)}] {t['nome']} ({t['cpf']})")
                try:
                    page.goto(url_remuneracao(t["cpf"], ano, mes))
                    page.wait_for_load_state("networkidle")
                    time.sleep(0.4)

                    rubricas = extrair_rubricas(page)
                    for r in rubricas:
                        todos.append(
                            {"Ano": ano, "Mês": mes, "Nome": t["nome"], "CPF": t["cpf"], **r}
                        )
                    log(f"    ✓ {len(rubricas)} rubrica(s)")

                except Exception as e:
                    log(f"    ⚠️ Erro: {e}")

                pd.DataFrame(todos).to_excel(SAIDA / "checkpoint.xlsx", index=False)

        # NÃO feche o Chrome manual — só desconecta
        log("💡 Chrome continua aberto — feche manualmente quando quiser.")

    df = pd.DataFrame(todos)
    df.to_excel(SAIDA / "remuneracoes_esocial.xlsx", index=False)
    log(f"\n✅ {len(df)} rubricas em {SAIDA / 'remuneracoes_esocial.xlsx'}")


if __name__ == "__main__":
    main()