import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import random

st.set_page_config(page_title="Calculadora ML - Turbo", page_icon="⚡", layout="wide")

# --- 1. AUTENTICAÇÃO OAUTH ---
@st.cache_data(ttl=18000) # Cache de 5h
def get_access_token():
    client_id = st.secrets.get("ML_CLIENT_ID")
    client_secret = st.secrets.get("ML_CLIENT_SECRET")
    if not client_id or not client_secret: return None

    url = "https://api.mercadolibre.com/oauth/token"
    data = {"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret}
    
    try:
        response = requests.post(url, headers={"accept": "application/json", "content-type": "application/x-www-form-urlencoded"}, data=data)
        if response.status_code == 200: return response.json().get("access_token")
    except: pass
    return None

APP_TOKEN = get_access_token()

# --- 2. SISTEMA ANTI-BLOCK ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
]

def get_headers(use_token=True):
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    if use_token and APP_TOKEN:
        headers["Authorization"] = f"Bearer {APP_TOKEN}"
    return headers

# --- 3. FUNÇÕES DE EXTRAÇÃO INTELIGENTE ---

def resolver_catalogo_para_item(catalog_id):
    """
    Retorna dados pré-carregados.
    ATUALIZAÇÃO: Agora puxa os ATRIBUTOS do Produto (Product ID) 
    para tentar descobrir o peso, já que a oferta não traz isso.
    """
    clean_id = catalog_id.replace("MLB", "").replace("-", "")
    product_id = f"MLB{clean_id}"
    headers = get_headers() 
    
    st.caption(f"🕵️ [API] Resolvendo Catálogo: {product_id}...")

    try:
        # 1. Busca dados do PRODUTO (Onde ficam os atributos técnicos)
        url_product = f"https://api.mercadolibre.com/products/{product_id}"
        resp_prod = requests.get(url_product, headers=headers)
        product_info = resp_prod.json() if resp_prod.status_code == 200 else {}
        
        base_title = product_info.get('name', 'Produto de Catálogo')
        pictures = product_info.get('pictures', [])
        base_img = pictures[0].get('url', '') if pictures else ''
        
        # [NOVO] Pega atributos do produto (Peso, etc)
        product_attributes = product_info.get('attributes', [])

        # 2. Busca OFERTAS (Preços)
        url_offers = f"https://api.mercadolibre.com/products/{product_id}/items"
        resp_offers = requests.get(url_offers, headers=headers)
        
        if resp_offers.status_code == 200:
            ofertas = resp_offers.json().get('results', [])
            
            if ofertas:
                winner = ofertas[0]
                st.success(f"✅ [API] Oferta capturada direto do catálogo!")
                
                link_item = winner.get('permalink')
                if not link_item:
                    link_item = f"https://produto.mercadolivre.com.br/{winner['item_id']}"

                return {
                    'id': winner['item_id'],
                    'title': base_title, 
                    'price': float(winner.get('price', 0)),
                    'thumbnail': base_img,
                    'permalink': link_item,
                    'source': 'API CATÁLOGO (Otimizada)',
                    'category_id': product_info.get('category_id'),
                    # AQUI O TRUQUE: Passamos os atributos do PRODUTO para o cálculo de peso
                    'attributes': product_attributes 
                }

    except Exception as e:
        print(f"Erro resolver catalogo: {e}")

    st.warning("⚠️ Não foi possível extrair dados do catálogo via API.")
    return None

def scrape_html_fallback(mlb_id):
    """
    Versão Heavy Metal: Tenta reconstruir a URL correta e usa múltiplos seletores
    para driblar mudanças de layout do ML.
    """
    # 1. Corrige a URL para o formato canônico (MLB-12345...)
    # Se tentar acessar /MLB12345 (sem hifen) o ML costuma bloquear ou redirecionar mal
    clean_id = mlb_id.replace("MLB", "").replace("-", "")
    url = f"https://produto.mercadolivre.com.br/MLB-{clean_id}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.google.com/"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # --- TENTATIVA DE TÍTULO (3 Estratégias) ---
            title = None
            # Estratégia 1: Classe padrão nova
            h1 = soup.find('h1', {'class': 'ui-pdp-title'})
            if h1: title = h1.text.strip()
            
            # Estratégia 2: Classe antiga/header
            if not title:
                h1 = soup.find('h1', {'class': 'ui-pdp-header__title'})
                if h1: title = h1.text.strip()

            # Estratégia 3: Meta tag (infalível se a página carregou)
            if not title:
                meta_title = soup.find('meta', {'name': 'twitter:title'})
                if meta_title: title = meta_title.get('content')

            if not title:
                # Se não achou título, provavelmente caiu no Captcha
                print("Scraping: Título não encontrado (Possível Captcha)")
                return None

            # --- TENTATIVA DE PREÇO (O mais chato de pegar) ---
            price = 0.0
            
            # Estratégia 1: Meta Tag (Mais limpa)
            meta_price = soup.find('meta', {'itemprop': 'price'})
            if meta_price:
                try: price = float(meta_price['content'])
                except: pass
            
            # Estratégia 2: Busca visual no HTML (andes-money-amount)
            if price == 0:
                price_tag = soup.find('div', {'class': 'ui-pdp-price__second-line'})
                if price_tag:
                    fraction = price_tag.find('span', {'class': 'andes-money-amount__fraction'})
                    if fraction:
                        price = float(fraction.text.replace('.', '').replace(',', '.'))

            # --- IMAGEM ---
            thumb = ""
            img_tag = soup.find('img', {'class': 'ui-pdp-image'})
            if img_tag:
                thumb = img_tag.get('src')
            
            return {
                'id': mlb_id,
                'title': title,
                'price': price,
                'thumbnail': thumb,
                'source': 'SCRAPING HTML (BLINDADO)',
                'attributes': [] # Scraping não pega peso detalhado, usará fallback
            }
            
    except Exception as e:
        print(f"Erro fatal no scraping: {e}")
        
    return None

def get_item_data(item_id_or_data):
    """
    Se receber um dicionário, usa ele. Se receber ID, consulta.
    """
    # Se já veio resolvido do catálogo, retorna direto!
    if isinstance(item_id_or_data, dict):
        return item_id_or_data

    item_id = item_id_or_data
    headers = get_headers()
    
    # Tenta API Oficial para itens normais
    url = f"https://api.mercadolibre.com/items/{item_id}"
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            data['source'] = 'API OFICIAL'
            return data
    except: pass
    
    return None

def extrair_id(url):
    url = url.strip()
    if "/p/MLB" in url or "/up/MLB" in url:
        m = re.search(r"(MLB)[-]?(\d+)", url, re.IGNORECASE)
        return f"MLB{m.group(2)}" if m else "CATALOGO"
    m = re.search(r"(MLB)[-]?(\d+)", url, re.IGNORECASE)
    return f"MLB{m.group(2)}" if m else None

# --- 4. INTERFACE ---

st.title("🚀 Calculadora Sourcing (Modo Rápido)")
status_api = "🟢 Conectado (OAuth)" if APP_TOKEN else "🟡 Modo Público (Limitado)"
st.caption(f"Status API: {status_api}")

with st.sidebar:
    st.header("⚙️ Parâmetros")
    reputacao = st.selectbox("Reputação", ["Sem Reputação", "MercadoLíder (40%)", "Gold/Platinum (50%)", "Loja Oficial (60%)"])
    imposto = st.number_input("Imposto (%)", 4.0)
    custo_fixo = st.number_input("Custo Fixo (R$)", 1.50)

url_input = st.text_input("Cole a URL:", placeholder="https://...")

if url_input:
    mlb_id = extrair_id(url_input) # Certifique-se de usar o nome da sua função (extrair_id ou extrair_id_mlb)
    
    # Variáveis de controle
    dados_finais = None
    item_id_exibicao = mlb_id
    
    # --- 1. LÓGICA DE CATÁLOGO (OTIMIZADA) ---
    is_catalog = "/p/" in url_input or "/up/" in url_input or (mlb_id and not mlb_id.startswith("MLB"))
    
    if is_catalog or mlb_id == "CATALOGO":
        st.info("🔄 Resolvendo catálogo...")
        match = re.search(r"(\d{7,})", url_input)
        cat_id = f"MLB{match.group(1)}" if match else mlb_id
        
        if cat_id:
            # Chama a função que tenta trazer o DADO COMPLETO para evitar nova chamada
            resultado_resolucao = resolver_catalogo_para_item(cat_id)
            
            if isinstance(resultado_resolucao, dict):
                # SUCESSO: Já temos os dados (preço, titulo, foto) direto do resolver
                dados_finais = resultado_resolucao
                item_id_exibicao = dados_finais.get('id')
            elif isinstance(resultado_resolucao, str):
                # MEIO-SUCESSO: Temos só o ID, vamos precisar consultar detalhes abaixo
                mlb_id = resultado_resolucao
                item_id_exibicao = mlb_id
            else:
                st.error("❌ Nenhum vendedor ativo encontrado.")

    # --- 2. BUSCA DE DADOS (Se ainda não temos o objeto completo) ---
    # Se não veio preenchido do catálogo, ou se é um link direto de item
    if not dados_finais and mlb_id and mlb_id != "CATALOGO":
        with st.spinner(f"Consultando dados de {mlb_id}..."):
            # Aqui ele vai tentar API -> Se falhar -> Vai pro Scraping (se sua função get_item_data tiver o fallback)
            dados_finais = get_item_data(mlb_id)

    # --- 3. PROCESSAMENTO E EXIBIÇÃO ---
    if dados_finais:
        # Extração segura dos dados
        titulo = dados_finais.get('title', 'Título Indisponível')
        preco = float(dados_finais.get('price', 0))
        thumb = dados_finais.get('thumbnail', '').replace("-I.jpg", "-O.jpg")
        origem = dados_finais.get('source', 'Desconhecida')
        item_id_real = dados_finais.get('id', item_id_exibicao)
        
        # --- 1. LÓGICA DE PESO MELHORADA (DEEP SCAN) ---
        peso_detectado = 0.0
        
        # Lista de prioridade de atributos para buscar peso
        # O ML usa vários nomes diferentes para a mesma coisa
        attr_candidates = [
            'PACKAGE_WEIGHT', 'WEIGHT', 'NET_WEIGHT', 'GROSS_WEIGHT', 
            'PRODUCT_WEIGHT', 'item_package_weight'
        ]
        
        for attr in dados_finais.get('attributes', []):
            if attr['id'] in attr_candidates and attr.get('value_name'):
                val_str = str(attr['value_name']).lower()
                try:
                    # Extrai apenas números (ex: "300 g" -> 300.0)
                    nums = re.findall(r"[\d\.]+", val_str.replace(',', '.'))
                    if nums:
                        num = float(nums[0])
                        # Converte tudo para KG
                        peso_temp = num / 1000 if ('g' in val_str and 'kg' not in val_str) else num
                        
                        # Se achou um peso válido, salva e para
                        if peso_temp > 0:
                            peso_detectado = peso_temp
                            break # Para no primeiro que achar (respeitando a ordem da lista)
                except: pass
        
        # Se a varredura falhar, sugere 0.5, mas o usuário poderá mudar
        peso_sugerido = peso_detectado if peso_detectado > 0 else 0.5

        # --- LAYOUT INTERATIVO ---
        st.divider()
        c_img, c_dados = st.columns([1, 3])
        
        with c_img:
            if thumb: st.image(thumb, width=250)
            else: st.markdown("🖼️ *Sem Imagem*")
            
            # Mostra a origem dos dados discretamente
            if 'SCRAPING' in origem:
                st.warning("⚠️ Dados via HTML")
            elif 'CATÁLOGO' in origem:
                 st.success("⚡ Dados via Catálogo")
        
        with c_dados:
            st.subheader(titulo)
            st.caption(f"MLB ID: {item_id_real}")
            
            # --- AQUI ESTÁ A MÁGICA: INPUT DE PESO EDITÁVEL ---
            # Em vez de só mostrar, permitimos que o usuário altere
            col_inputs = st.columns([2, 2, 2])
            with col_inputs[0]:
                peso_kg = st.number_input(
                    "⚖️ Peso (kg) para Frete", 
                    value=float(peso_sugerido), 
                    step=0.100, 
                    format="%.3f",
                    help="O script tenta detectar. Se estiver errado (0.500), ajuste aqui manualmente."
                )
            
            # Recalcula tudo com base no peso que está na tela (seja automático ou manual)
            
            # 1. Taxa ML
            taxa = preco * 0.115
            if preco < 79.00: taxa += 6.00
            
            # 2. Frete (Tabela Base Simplificada)
            frete_full = 190.00 
            if peso_kg <= 0.3: frete_full = 32.90 # Adicionado faixa de 300g
            elif peso_kg <= 0.5: frete_full = 34.90
            elif peso_kg <= 1.0: frete_full = 38.90
            elif peso_kg <= 2.0: frete_full = 42.90
            elif peso_kg <= 5.0: frete_full = 55.90
            elif peso_kg <= 9.0: frete_full = 75.90
            elif peso_kg <= 13.0: frete_full = 95.90
            elif peso_kg <= 17.0: frete_full = 115.90
            elif peso_kg <= 23.0: frete_full = 145.90
            elif peso_kg <= 30.0: frete_full = 175.90
            
            # Desconto Reputação
            fator = 0.0
            if "40%" in reputacao: fator = 0.6
            elif "50%" in reputacao: fator = 0.5
            elif "60%" in reputacao: fator = 0.4
            
            frete_seller = 0.0
            if preco >= 79.00:
                frete_seller = frete_full * fator if fator > 0 else frete_full

            # 3. Resultado
            impostos = preco * (imposto/100)
            sobra = preco - taxa - frete_seller - impostos - custo_fixo
            margem = (sobra/preco)*100 if preco > 0 else 0
            
            # --- EXIBIÇÃO DOS KPI's ---
            st.markdown("---")
            k1, k2, k3, k4 = st.columns(4)
            
            k1.metric("Preço Venda", f"R$ {preco:.2f}")
            k2.metric("Taxa ML", f"R$ {taxa:.2f}")
            
            if preco < 79.00:
                k3.metric("Frete", "R$ 0.00", delta="Pago pelo Cliente", delta_color="off")
            else:
                k3.metric("Frete Estimado", f"R$ {frete_seller:.2f}")
                
            k4.metric("Lucro Líquido", f"R$ {sobra:.2f}", delta=f"{margem:.1f}%")
            
            # Barra de Progresso Visual da Margem
            if margem > 0:
                st.progress(min(int(margem), 100), text=f"Margem de {margem:.1f}%")
            else:
                st.error("Prejuízo Estimado")

    else:
        if mlb_id:
            st.error("❌ Não foi possível obter dados deste produto. Tente outro link.")