from playwright.sync_api import sync_playwright

# O perfil fica salvo em ./perfil_esocial
with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir="./perfil_esocial",
        headless=False,  # False na 1ª vez para você logar manualmente
        slow_mo=100,     # deixa os cliques visíveis
    )
    page = context.new_page()
    page.goto("https://www.esocial.gov.br/")  # ajuste para a URL real
    # Faça o login manualmente agora. Depois feche.
    input("Faça login e pressione ENTER para continuar...")
    context.close()