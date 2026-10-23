BASE = "https://www.esocial.gov.br"
URL_GESTAO = f"{BASE}/portal/FolhaPagamento/GestaoFolha?Competencia=202604&AbaAtiva=tabFolhaComDARF"

ANOS = [2021, 2022, 2023, 2024, 2025, 2026]
MESES_POR_ANO = {
    2021: range(1, 13), 2022: range(1, 13), 2023: range(1, 13),
    2024: range(1, 13), 2025: range(1, 13),
    2026: range(1, 11),   # Jan–Out
}