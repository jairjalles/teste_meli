import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import random

# Configuração da Página
st.set_page_config(page_title="Calculadora ML - Pro", page_icon="📦", layout="wide")

# --- 1. AUTENTICAÇÃO OAUTH (TOKEN) ---
@st.cache_data(ttl=18000)
def get_access_token():
    client_id = st.secrets.get("ML_CLIENT_ID")
    client_secret = st.secrets.get("ML_CLIENT_SECRET")
    if not client_id or not client_secret: return None
    
    url = "https://api.mercadolibre.com/oauth/token"
    headers = {"accept": "application/json", "content-type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret}
    
    try:
        response = requests.post(url, headers=headers, data=data)
        if response.status_code == 200: return response.json().get("access_token")
    except: pass
    return None

APP_TOKEN = get_access_token()

# --- 2. HEADERS ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
]

def get_headers(use_token=True):
    headers = {"User-Agent": random.choice(USER_AGENTS), "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"}
    if use_token and APP_TOKEN: headers["Authorization"] = f"Bearer {APP_TOKEN}"
    return headers

# --- 3. FUNÇÕES AUXILIARES ---

def extrair_id_mlb(url):
    url = url.strip()
    if "/p/MLB" in url or "/up/MLB" in url:
        match = re.search(r"(MLB)[-]?(\d+)", url, re.IGNORECASE)
        return f"MLB{match.group(2)}" if match else "CATALOGO"
    match = re.search(r"(MLB)[-]?(\d+)", url, re.IGNORECASE)
    return f"MLB{match.group(2)}" if match else None

def consultar_taxas_reais(price, category_id):
    headers = get_headers()
    url = f"https://api.mercadolibre.com/sites/MLB/listing_prices?price={price}&category_id={category_id}"
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            taxas = {'classico': 0.0, 'premium': 0.0, 'classico_pct': 0, 'premium_pct': 0}
            for option in data:
                if option['listing_type_id'] == 'gold_special':
                    taxas['classico'] = float(option['sale_fee_amount'])
                    if price > 0: taxas['classico_pct'] = (taxas['classico'] / price) * 100
                elif option['listing_type_id'] == 'gold_pro':
                    taxas['premium'] = float(option['sale_fee_amount'])
                    if price > 0: taxas['premium_pct'] = (taxas['premium'] / price) * 100
            return taxas
    except: pass
    return None

def resolver_catalogo_para_item(catalog_id):
    clean_id = catalog_id.replace("MLB", "").replace("-", "")
    product_id = f"MLB{clean_id}"
    headers = get_headers() 
    st.caption(f"🕵️ [API] Resolvendo Catálogo: {product_id}...")
    try:
        url_prod = f"https://api.mercadolibre.com/products/{product_id}"
        resp_prod = requests.get(url_prod, headers=headers)
        p_info = resp_prod.json() if resp_prod.status_code == 200 else {}
        
        url_off = f"https://api.mercadolibre.com/products/{product_id}/items"
        resp_off = requests.get(url_off, headers=headers)
        
        if resp_off.status_code == 200:
            ofertas = resp_off.json().get('results', [])
            if ofertas:
                winner = ofertas[0]
                st.success(f"✅ [API] Oferta capturada direto do catálogo!")
                link = winner.get('permalink', f"https://produto.mercadolivre.com.br/{winner['item_id']}")
                cat_final = winner.get('category_id')
                if not cat_final or cat_final == "MLB1":
                    cat_final = p_info.get('category_id', 'MLB1')

                return {
                    'id': winner['item_id'],
                    'title': p_info.get('name', 'Produto Catálogo'),
                    'price': float(winner.get('price', 0)),
                    'thumbnail': p_info.get('pictures', [{}])[0].get('url', ''),
                    'permalink': link,
                    'source': 'API CATÁLOGO',
                    'category_id': cat_final,
                    'attributes': p_info.get('attributes', [])
                }
    except: pass
    st.warning("⚠️ Catálogo não resolvido via API.")
    return None

def get_item_data(item_id_or_data):
    if isinstance(item_id_or_data, dict): return item_id_or_data
    item_id = item_id_or_data
    try:
        url = f"https://api.mercadolibre.com/items/{item_id}"
        resp = requests.get(url, headers=get_headers())
        if resp.status_code == 200:
            d = resp.json()
            d['source'] = 'API OFICIAL'
            return d
    except: pass
    # Fallback HTML
    try:
        url = f"https://produto.mercadolivre.com.br/MLB-{item_id.replace('MLB','').replace('-','')}"
        r = requests.get(url, headers=get_headers(False))
        if r.status_code == 200:
            s = BeautifulSoup(r.text, 'html.parser')
            h1 = s.find('h1', {'class': 'ui-pdp-title'})
            meta_p = s.find('meta', {'itemprop': 'price'})
            img = s.find('img', {'class': 'ui-pdp-image'})
            return {
                'id': item_id, 
                'title': h1.text.strip() if h1 else "Título Indisponível", 
                'price': float(meta_p['content']) if meta_p else 0.0,
                'thumbnail': img.get('src') if img else "",
                'source': 'SCRAPING HTML', 'attributes': [], 'category_id': 'MLB1'
            }
    except: pass
    return None

# --- 4. INTERFACE ---

st.title("🚀 Calculadora Sourcing ML")
status_api = "🟢 Conectado" if APP_TOKEN else "🟡 Limitado"
st.caption(f"Status API: {status_api}")

# --- SIDEBAR COM CORES OFICIAIS ---
with st.sidebar:
    st.header("⚙️ Configuração de Custos")
    
    # Input de Reputação
    # Opções alinhadas com os benefícios reais de frete
    opcao_rep = st.selectbox(
        "Nível de Reputação (Cor)", 
        ["Sem Reputação / Amarelo", "MercadoLíder (Verde)", "Gold / Platinum (Verde)", "Loja Oficial (Azul)"]
    )
    
    # Lógica de Cores Exatas (HEX Oficial ML) e Descontos
    cor_barra = "#cccccc" 
    fator_desconto_sidebar = 0.0
    texto_desc = ""
    
    if "Sem Reputação" in opcao_rep:
        cor_barra = "#bfbfbf" # Cinza
        fator_desconto_sidebar = 0.0
        texto_desc = "Sem desconto no frete"
        
    elif "MercadoLíder" in opcao_rep or "Gold" in opcao_rep:
        cor_barra = "#00a650" # VERDE OFICIAL ML
        fator_desconto_sidebar = 0.5 # 50% de desconto
        texto_desc = "50% OFF no Frete"
        
    elif "Loja Oficial" in opcao_rep:
        cor_barra = "#3483fa" # AZUL OFICIAL ML
        fator_desconto_sidebar = 0.6 # Até 60% (varia contrato)
        texto_desc = "Até 60% OFF no Frete"

    # Renderiza a Barra Colorida Visual
    st.markdown(f"""
    <div style="background-color: #f5f5f5; padding: 10px; border-radius: 5px; border-left: 5px solid {cor_barra}; margin-bottom: 20px;">
        <strong style="color: {cor_barra};">{texto_desc}</strong>
    </div>
    """, unsafe_allow_html=True)

    imposto = st.number_input("Seu Imposto (%)", value=4.0, step=0.5, help="DAS/Simples Nacional")
    custo_fixo = st.number_input("Custo Fixo/Pedido (R$)", value=1.50, step=0.50, help="Embalagem, fita, etiqueta...")

# --- CORPO PRINCIPAL ---
url_input = st.text_input("Cole a URL do produto:", placeholder="https://...")

if url_input:
    mlb_id = extrair_id_mlb(url_input)
    dados_finais = None
    item_id_exibicao = mlb_id
    
    is_catalog = "/p/" in url_input or "/up/" in url_input or (mlb_id and not mlb_id.startswith("MLB"))
    if is_catalog or mlb_id == "CATALOGO":
        st.info("🔄 Resolvendo catálogo...")
        match = re.search(r"(\d{7,})", url_input)
        cat_id = f"MLB{match.group(1)}" if match else mlb_id
        if cat_id:
            res = resolver_catalogo_para_item(cat_id)
            if isinstance(res, dict): dados_finais = res; item_id_exibicao = dados_finais.get('id')
            elif isinstance(res, str): mlb_id = res
            else: st.error("❌ Catálogo sem vendedor ativo.")

    if not dados_finais and mlb_id and mlb_id != "CATALOGO":
        with st.spinner("Consultando item..."):
            dados_finais = get_item_data(mlb_id)

    if dados_finais:
        titulo = dados_finais.get('title', 'Título Indisponível')
        preco = float(dados_finais.get('price', 0))
        thumb = dados_finais.get('thumbnail', '').replace("-I.jpg", "-O.jpg")
        cat_id = dados_finais.get('category_id', 'MLB1')
        
        # Scan Peso
        peso_det = 0.0
        cand = ['PACKAGE_WEIGHT', 'WEIGHT', 'NET_WEIGHT', 'GROSS_WEIGHT', 'PRODUCT_WEIGHT']
        for attr in dados_finais.get('attributes', []):
            if attr['id'] in cand and attr.get('value_name'):
                v = str(attr['value_name']).lower()
                try:
                    n = float(re.findall(r"[\d\.]+", v.replace(',', '.'))[0])
                    p = n * 1000 if 'kg' in v else n
                    p = p / 1000
                    if p > 0: peso_det = p; break
                except: pass
        peso_sug = peso_det if peso_det > 0 else 0.5

        st.divider()
        c1, c2 = st.columns([1, 3])
        with c1:
            if thumb: st.image(thumb, width=250)
        
        with c2:
            st.subheader(titulo)
            st.caption(f"ID: {item_id_exibicao} | Categoria: {cat_id}")
            
            col_c = st.columns([2, 3])
            with col_c[0]: peso_kg = st.number_input("⚖️ Peso Frete (kg)", value=float(peso_sug), step=0.100, format="%.3f")
            with col_c[1]: tipo_anuncio = st.radio("Tipo Anúncio", ["Clássico", "Premium"], index=0, horizontal=True)

            # --- CÁLCULOS ---
            # 1. Taxa
            taxas_reais = consultar_taxas_reais(preco, cat_id)
            if taxas_reais:
                taxa_ml = taxas_reais['classico'] if tipo_anuncio == "Clássico" else taxas_reais['premium']
                pct_real = taxas_reais['classico_pct'] if tipo_anuncio == "Clássico" else taxas_reais['premium_pct']
            else:
                pct_real = 11.5 if tipo_anuncio == "Clássico" else 16.5
                taxa_ml = (preco * (pct_real/100)) + (6.00 if preco < 79 else 0)
            
            # 2. Frete (Tabela 2025 Ajustada)
            frete_full = 210.00 
            if peso_kg <= 0.3: frete_full = 41.90 
            elif peso_kg <= 0.5: frete_full = 44.90 
            elif peso_kg <= 1.0: frete_full = 49.90
            elif peso_kg <= 2.0: frete_full = 53.90
            elif peso_kg <= 5.0: frete_full = 68.90
            elif peso_kg <= 9.0: frete_full = 92.90
            elif peso_kg <= 13.0: frete_full = 125.90
            elif peso_kg <= 17.0: frete_full = 155.90
            elif peso_kg <= 23.0: frete_full = 185.90
            
            # USA O FATOR DE DESCONTO DA SIDEBAR
            frete_seller = 0.0
            if preco >= 79.00:
                 if fator_desconto_sidebar > 0: 
                     frete_seller = frete_full * (1 - fator_desconto_sidebar)
                 else: 
                     frete_seller = frete_full

            # 3. Totais
            impostos_reais = preco * (imposto/100)
            recebivel_ml = preco - taxa_ml - frete_seller
            sobra = recebivel_ml - impostos_reais - custo_fixo
            margem = (sobra/preco)*100 if preco > 0 else 0

            # --- EXIBIÇÃO ---
            st.markdown("---")
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Preço Venda", f"R$ {preco:.2f}")
            k2.metric(f"Taxa ML ({pct_real:.1f}%)", f"R$ {taxa_ml:.2f}")
            
            if preco < 79.00: k3.metric("Frete", "R$ 0.00", delta="Cliente Paga", delta_color="off")
            else: k3.metric("Frete Estimado", f"R$ {frete_seller:.2f}")
            
            # Métrica Igual ao Simulador Oficial
            k4.metric("Recebe do ML", f"R$ {recebivel_ml:.2f}", help="Valor que cai no Mercado Pago")
            
            # CARD FINAL
            cor_bg = "#d1e7dd" if sobra > 0 else "#f8d7da"
            cor_txt = "#0f5132" if sobra > 0 else "#842029"
            
            st.markdown(f"""
            <div style="background-color: {cor_bg}; color: {cor_txt}; padding: 15px; border-radius: 8px; margin-top: 10px; border: 1px solid {cor_txt};">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="font-size: 14px; font-weight: bold;">LUCRO LÍQUIDO REAL</span><br>
                        <span style="font-size: 12px;">(Após Impostos R$ {impostos_reais:.2f} + Fixo R$ {custo_fixo:.2f})</span>
                    </div>
                    <div style="text-align: right;">
                        <span style="font-size: 24px; font-weight: bold;">R$ {sobra:.2f}</span><br>
                        <span style="font-size: 14px;">Margem: {margem:.1f}%</span>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # --- CALCULADORA REVERSA ---
            st.markdown("### 🎯 Target Price (Negociação)")
            
            col_t1, col_t2 = st.columns([3, 2])
            with col_t1:
                margem_alvo = st.slider("Margem Líquida Desejada (%)", 5, 50, 20)
            
            with col_t2:
                lucro_desejado = preco * (margem_alvo / 100)
                custo_maximo = recebivel_ml - impostos_reais - custo_fixo - lucro_desejado
                cor_target = "green" if custo_maximo > 0 else "red"
                
                st.markdown(f"""
                <div style="border: 2px dashed #ccc; padding: 10px; border-radius: 8px; text-align: center;">
                    <small style="color: #666;">Seu Teto de Compra</small>
                    <h2 style="color: {cor_target}; margin: 0;">R$ {custo_maximo:.2f}</h2>
                </div>
                """, unsafe_allow_html=True)

    else:
        if mlb_id: st.error("❌ Erro ao carregar dados.")