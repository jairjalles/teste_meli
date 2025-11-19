import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import random
import pandas as pd
from datetime import datetime

# Configuração da Página
st.set_page_config(page_title="Calculadora ML - Hub Master", page_icon="⚡", layout="wide")

# --- 0. INICIALIZAÇÃO ---
if 'historico' not in st.session_state: st.session_state['historico'] = []

# --- 1. HELPERS VISUAIS ---
def format_brl(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- 2. AUTH & HEADERS ---
@st.cache_data(ttl=18000)
def get_access_token():
    cid = st.secrets.get("ML_CLIENT_ID")
    sec = st.secrets.get("ML_CLIENT_SECRET")
    if not cid or not sec: return None
    try:
        r = requests.post("https://api.mercadolibre.com/oauth/token", 
                          headers={"content-type": "application/x-www-form-urlencoded"}, 
                          data={"grant_type": "client_credentials", "client_id": cid, "client_secret": sec})
        return r.json().get("access_token") if r.status_code == 200 else None
    except: return None

APP_TOKEN = get_access_token()
USER_AGENTS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"]

def get_headers(use_token=True):
    h = {"User-Agent": random.choice(USER_AGENTS)}
    if use_token and APP_TOKEN: h["Authorization"] = f"Bearer {APP_TOKEN}"
    return h

# --- 3. LÓGICA E EXTRAÇÃO ---
def extrair_id_mlb(url):
    if not isinstance(url, str): return None
    url = url.strip()
    if "/p/MLB" in url or "/up/MLB" in url:
        m = re.search(r"(MLB)[-]?(\d+)", url, re.IGNORECASE)
        return f"MLB{m.group(2)}" if m else "CATALOGO"
    m = re.search(r"(MLB)[-]?(\d+)", url, re.IGNORECASE)
    return f"MLB{m.group(2)}" if m else None

def calcular_financeiro(preco, peso_kg, category_id, tipo_anuncio, reputacao_fator, imposto_pct, custo_fixo):
    taxas = consultar_taxas_reais(preco, category_id)
    if taxas:
        taxa_ml = taxas['classico'] if tipo_anuncio == "Clássico" else taxas['premium']
        pct_real = taxas['classico_pct'] if tipo_anuncio == "Clássico" else taxas['premium_pct']
    else:
        pct_real = 11.5 if tipo_anuncio == "Clássico" else 16.5
        taxa_ml = (preco * (pct_real/100)) + (6.00 if preco < 79 else 0)

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
    
    frete_seller = 0.0
    if preco >= 79.00:
        frete_seller = frete_full * (1 - reputacao_fator) if reputacao_fator > 0 else frete_full

    impostos = preco * (imposto_pct/100)
    recebivel = preco - taxa_ml - frete_seller
    sobra = recebivel - impostos - custo_fixo
    margem = (sobra/preco)*100 if preco > 0 else 0
    
    return {
        "taxa_ml": taxa_ml, "pct_taxa": pct_real, "frete_seller": frete_seller,
        "recebivel_ml": recebivel, "lucro_liquido": sobra, "margem": margem
    }

# --- API CALLS ---
@st.cache_data(ttl=36000)
def get_category_tree(cid):
    if not cid or cid == "MLB1": return "Raiz"
    try:
        r = requests.get(f"https://api.mercadolibre.com/categories/{cid}", headers=get_headers())
        return " > ".join([n['name'] for n in r.json().get('path_from_root', [])]) if r.status_code == 200 else cid
    except: return cid

def consultar_taxas_reais(price, cid):
    try:
        r = requests.get(f"https://api.mercadolibre.com/sites/MLB/listing_prices?price={price}&category_id={cid}", headers=get_headers())
        if r.status_code == 200:
            d = r.json()
            t = {'classico': 0.0, 'premium': 0.0, 'classico_pct': 0, 'premium_pct': 0}
            for o in d:
                if o['listing_type_id'] == 'gold_special':
                    t['classico'] = float(o['sale_fee_amount'])
                    if price>0: t['classico_pct'] = (t['classico']/price)*100
                elif o['listing_type_id'] == 'gold_pro':
                    t['premium'] = float(o['sale_fee_amount'])
                    if price>0: t['premium_pct'] = (t['premium']/price)*100
            return t
    except: pass
    return None

def resolver_catalogo(cat_id):
    clean = cat_id.replace("MLB", "").replace("-", "")
    pid = f"MLB{clean}"
    h = get_headers()
    try:
        p = requests.get(f"https://api.mercadolibre.com/products/{pid}", headers=h).json()
        items = requests.get(f"https://api.mercadolibre.com/products/{pid}/items", headers=h).json().get('results', [])
        
        if items:
            w = items[0]
            cat = w.get('category_id') or p.get('category_id', 'MLB1')
            return {
                'id': w['item_id'], 'title': p.get('name', 'Catálogo'),
                'price': float(w.get('price', 0)),
                'thumbnail': p.get('pictures', [{}])[0].get('url', ''),
                'permalink': w.get('permalink'),
                'source': 'CATÁLOGO', 'category_id': cat,
                'attributes': p.get('attributes', [])
            }
    except: pass
    return None

def get_item(mid):
    # 1. Tenta API Oficial
    try:
        r = requests.get(f"https://api.mercadolibre.com/items/{mid}", headers=get_headers())
        if r.status_code == 200:
            d = r.json()
            d['source'] = 'API'
            return d
    except: pass
    
    # 2. Fallback Scraping HTML (Dados Básicos apenas)
    try:
        url = f"https://produto.mercadolivre.com.br/MLB-{mid.replace('MLB','').replace('-','')}"
        req = requests.get(url, headers=get_headers(False))
        
        if req.status_code == 200:
            s = BeautifulSoup(req.text, 'html.parser')
            h1 = s.find('h1', {'class': 'ui-pdp-title'})
            title = h1.text.strip() if h1 else "Título Indisponível"
            price = 0.0
            meta = s.find('meta', {'itemprop': 'price'})
            if meta: price = float(meta['content'])
            img = s.find('img', {'class': 'ui-pdp-image'})
            thumb = img.get('src') if img else ""

            return {
                'id': mid, 'title': title, 'price': price, 'thumbnail': thumb,
                'source': 'SCRAPING HTML', 'attributes': [], 'category_id': 'MLB1'
            }
    except: pass
    return None

# --- 4. INTERFACE ---
st.title("⚡ Hub Sourcing Master")
st.caption(f"API Status: {'🟢 Online' if APP_TOKEN else '🟡 Limitada'}")

with st.sidebar:
    st.header("⚙️ Configuração")
    rep = st.selectbox("Reputação", ["Sem Reputação", "MercadoLíder (Verde)", "Gold/Platinum (Verde)", "Loja Oficial (Azul)"])
    
    c_bar, f_desc = "#ccc", 0.0
    if "Sem" in rep: c_bar, f_desc = "#bfbfbf", 0.0
    elif "Verde" in rep: c_bar, f_desc = "#00a650", 0.5
    elif "Azul" in rep: c_bar, f_desc = "#3483fa", 0.6
    
    st.markdown(f'<div style="height:5px;background:{c_bar};margin-bottom:10px;border-radius:2px;"></div>', unsafe_allow_html=True)
    
    imp_pct = st.number_input("Imposto (%)", 4.0, step=0.5)
    custo_fixo = st.number_input("Custo Fixo (R$)", 1.50, step=0.5)

tab1, tab2, tab3 = st.tabs(["🧮 Individual", "📝 Lista Rápida / Excel", "📊 Relatórios"])

# --- ABA 1: INDIVIDUAL ---
with tab1:
    url_in = st.text_input("Cole a URL:", key="indiv_url")
    if url_in:
        mid = extrair_id_mlb(url_in)
        dados = None
        is_cat = "/p/" in url_in or "/up/" in url_in or (mid and not mid.startswith("MLB"))
        
        if is_cat or mid == "CATALOGO":
            m = re.search(r"(\d{7,})", url_in)
            if m: dados = resolver_catalogo(f"MLB{m.group(1)}")
        
        if not dados and mid and mid != "CATALOGO":
            with st.spinner("Analisando..."): dados = get_item(mid)
            
        if dados:
            peso_det = 0.0
            for a in dados.get('attributes', []):
                if a['id'] in ['PACKAGE_WEIGHT', 'WEIGHT', 'NET_WEIGHT', 'GROSS_WEIGHT']:
                    try:
                        n = float(re.findall(r"[\d\.]+", str(a['value_name']))[0])
                        p = n/1000 if 'g' in str(a['value_name']).lower() and 'kg' not in str(a['value_name']).lower() else n
                        if p>0: peso_det=p; break
                    except: pass
            peso_sug = peso_det if peso_det > 0 else 0.5

            c1, c2 = st.columns([1, 3])
            with c1: st.image(dados.get('thumbnail', '').replace("-I.jpg", "-O.jpg"), width=250)
            with c2:
                st.subheader(dados.get('title'))
                st.caption(f"📂 {get_category_tree(dados.get('category_id'))}")
                st.caption(f"Fonte: {dados.get('source', 'API')}")
                
                cc1, cc2 = st.columns([2,3])
                kg = cc1.number_input("Peso (kg)", value=float(peso_sug), step=0.1, format="%.3f")
                tipo = cc2.radio("Cenário", ["Clássico", "Premium"], horizontal=True, index=1)
                
                fin = calcular_financeiro(dados['price'], kg, dados.get('category_id'), tipo, f_desc, imp_pct, custo_fixo)
                fin_op = calcular_financeiro(dados['price'], kg, dados.get('category_id'), "Clássico" if tipo=="Premium" else "Premium", f_desc, imp_pct, custo_fixo)

                st.markdown("---")
                k1, k2, k3, k4, k5 = st.columns(5)
                k1.metric("Venda", format_brl(dados['price']))
                k2.metric(f"Taxa ({fin['pct_taxa']:.1f}%)", format_brl(fin['taxa_ml']))
                if dados['price'] < 79: k3.metric("Frete", "R$ 0,00", delta="Cliente Paga", delta_color="off")
                else: k3.metric("Frete", format_brl(fin['frete_seller']))
                k4.metric("Recebe ML", format_brl(fin['recebivel_ml']))
                k5.metric("Lucro", format_brl(fin['lucro_liquido']), delta=f"{fin['margem']:.1f}%")

                st.markdown("##### ⚖️ Comparativo")
                cp1, cp2 = st.columns(2)
                with cp1:
                    luc, mar = (fin['lucro_liquido'], fin['margem']) if tipo == 'Clássico' else (fin_op['lucro_liquido'], fin_op['margem'])
                    st.info(f"**CLÁSSICO** | Lucro: **{format_brl(luc)}** | Margem: {mar:.1f}%")
                with cp2:
                    luc, mar = (fin['lucro_liquido'], fin['margem']) if tipo == 'Premium' else (fin_op['lucro_liquido'], fin_op['margem'])
                    st.warning(f"**PREMIUM** | Lucro: **{format_brl(luc)}** | Margem: {mar:.1f}%")

                if st.button("💾 Salvar", type="primary"):
                    st.session_state['historico'].append({
                        "Data": datetime.now().strftime("%d/%m %H:%M"),
                        "Produto": dados['title'], "Preço": dados['price'],
                        "Lucro": fin['lucro_liquido'], "Margem %": fin['margem'],
                        "Link": url_in
                    })
                    st.success("Salvo!")

# --- ABA 2: LISTA RÁPIDA & EXCEL ---
with tab2:
    st.markdown("### 📝 Processamento em Lote")
    modo = st.radio("Origem", ["Colar Lista", "Subir Excel/CSV"], horizontal=True)
    lista_urls = []
    
    if modo == "Colar Lista":
        texto = st.text_area("Links (um por linha):", height=150)
        if texto: lista_urls = [L.strip() for L in texto.split('\n') if len(L.strip()) > 10]
    else:
        file = st.file_uploader("Arquivo", type=['xlsx', 'csv'])
        if file:
            df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
            col = next((c for c in ['URL', 'url', 'Link', 'ID'] if c in df.columns), None)
            if col: lista_urls = df[col].dropna().astype(str).tolist()

    if lista_urls:
        if st.button(f"⚡ Processar {len(lista_urls)} itens"):
            res = []
            prog = st.progress(0)
            
            for i, link in enumerate(lista_urls):
                mid = extrair_id_mlb(link)
                d = None
                if "CATALOGO" in str(mid) or "/p/" in link:
                    m = re.search(r"(\d{7,})", link)
                    if m: d = resolver_catalogo(f"MLB{m.group(1)}")
                elif mid: d = get_item(mid)
                
                if d:
                    fc = calcular_financeiro(d['price'], 0.5, d.get('category_id'), "Clássico", f_desc, imp_pct, custo_fixo)
                    fp = calcular_financeiro(d['price'], 0.5, d.get('category_id'), "Premium", f_desc, imp_pct, custo_fixo)
                    
                    res.append({
                        "Input": link, "Título": d['title'],
                        "Preço": d['price'], 
                        "Lucro Clássico": fc['lucro_liquido'], "Mg Clássico %": round(fc['margem'],1),
                        "Lucro Premium": fp['lucro_liquido'], "Mg Premium %": round(fp['margem'],1)
                    })
                    # Salva histórico (Premium padrão)
                    st.session_state['historico'].append({
                        "Data": datetime.now().strftime("%d/%m"), "Produto": d['title'],
                        "Preço": d['price'], "Lucro": fp['lucro_liquido'], "Margem %": fp['margem'],
                        "Link": link
                    })
                prog.progress((i+1)/len(lista_urls))
            
            st.success("Pronto!")
            # [CORRIGIDO AQUI]
            st.dataframe(pd.DataFrame(res), width="stretch")

# --- ABA 3: RELATÓRIOS ---
with tab3:
    if len(st.session_state['historico']) > 0:
        dfh = pd.DataFrame(st.session_state['historico'])
        # [CORRIGIDO AQUI]
        st.dataframe(dfh, width="stretch")
        st.download_button("📥 CSV", dfh.to_csv(index=False).encode('utf-8'), "report.csv", "text/csv")
        if st.button("Limpar"): st.session_state['historico'] = []; st.rerun()
    else: st.info("Vazio.")