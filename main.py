import pandas as pd
from jinja2 import Environment, FileSystemLoader
from datetime import datetime
import pytz
import warnings
import numpy as np 
import time 

# Ignora avisos informativos do Pandas para uma saída limpa no terminal.
warnings.filterwarnings(
    "ignore",
    category=FutureWarning,
    message="Downcasting object dtype arrays on .fillna"
)

# --- Configuração ---
URL_BASE = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vTP2LvRBgCHWvoGeguayoAX5BBYyJVqjrpX9mddDzXJ7_BlhcLlcEJkQGDn4i99K7ZQTcxaR65zoQbu/pub?output=csv'
URL_SHEETS = f"{URL_BASE}&cache_bust={int(time.time())}"


# --- ### INÍCIO DA NOVA FUNÇÃO HELPER ### ---
def parse_time_score(score_str):
    """
    Converte um resultado de WOD de tempo em um número para ordenação.
    Tempos (ex: "10:30") são convertidos para segundos.
    CAP+ (ex: "CAP +5") são convertidos para um número alto + reps restantes.
    Quanto menor o número, melhor o rank.
    """
    score_str = str(score_str).strip()
    
    # 1. Checa se é um score 'CAP +X'
    if score_str.upper().startswith('CAP'):
        try:
            # Tenta pegar o número de reps restantes (ex: 'CAP +5' -> 5)
            reps_remaining = int(score_str.split('+')[-1])
            # O score é um número base alto (pior que qualquer tempo) + reps restantes
            # Quanto mais reps restantes, pior (maior) o score.
            return 1000000 + reps_remaining
        except:
            # Se for só 'CAP' ou formato inválido, retorna uma penalidade alta
            return 2000000
    
    # 2. Tenta converter para tempo (MM:SS)
    try:
        parts = score_str.split(':')
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = int(parts[1])
            return (minutes * 60) + seconds
        # Tenta converter para um número simples (caso de tempo em segundos)
        else:
            return float(score_str)
    except:
        # 3. Se não for nada disso (ex: '--', 'nan', texto vazio), retorna o pior score
        return 9999999
# --- ### FIM DA NOVA FUNÇÃO HELPER ### ---


# --- LÓGICA DO CAMPEONATO ---
try:
    df_raw = pd.read_csv(URL_SHEETS)
    df_raw.replace(r'^\s*$', np.nan, regex=True, inplace=True)
except Exception as e:
    print(f"Erro ao ler dados da planilha: {e}")
    exit()

wod_base_names = sorted(list(set([col.replace('_Resultado', '') for col in df_raw.columns if col.endswith('_Resultado')])))

all_categories_data = {}

# 1. Agrupa os dados pela coluna 'Categoria'.
for category_name, df_category_raw in df_raw.groupby('Categoria'):
    
    df_leaderboard = pd.DataFrame({
        'Time': df_category_raw['Time'],
        'Integrantes': df_category_raw['Integrantes'] 
    })
    
    # 2. Itera sobre cada WOD para calcular os pontos.
    for wod_base in wod_base_names:
        resultado_col = f'{wod_base}_Resultado'
        pontos_col = f'{wod_base}_Pontos'

        df_wod_full = df_category_raw[['Time', resultado_col]].copy()
        df_wod_participantes = df_wod_full.dropna(subset=[resultado_col]).copy()

        if df_wod_participantes.empty:
            penalty_score = 0
            df_wod_ranked = pd.DataFrame(columns=['Time', 'Resultado', pontos_col])
        else:
            penalty_score = len(df_wod_participantes) + 1
            
            df_wod_participantes.rename(columns={resultado_col: 'Resultado'}, inplace=True)
            
            metrica = wod_base.split('_')[-1].lower()
            is_time = (metrica == 'tempo')

            if not is_time:
                # Lógica normal para Reps, Peso, etc.
                df_wod_participantes['Resultado_Num'] = pd.to_numeric(df_wod_participantes['Resultado'], errors='coerce')
            else:
                # --- ### MODIFICAÇÃO APLICADA AQUI ### ---
                # Usa a nova função para criar um score numérico para Tempos e CAP+
                df_wod_participantes['Resultado_Num'] = df_wod_participantes['Resultado'].apply(parse_time_score)

            # A lógica de ranking continua a mesma, pois 'is_time' é True (ascending=True)
            # e nossos números (630 vs 1000005) são classificados corretamente.
            df_wod_participantes[pontos_col] = df_wod_participantes['Resultado_Num'].rank(method='min', ascending=is_time)
            df_wod_ranked = df_wod_participantes

        # Junta os dados rankeados de volta na lista COMPLETA de times.
        df_leaderboard = pd.merge(df_leaderboard, df_wod_ranked[['Time', 'Resultado', pontos_col]], on='Time', how='left')
        
        df_leaderboard[pontos_col] = df_leaderboard[pontos_col].fillna(penalty_score).astype(int)
        df_leaderboard.rename(columns={'Resultado': resultado_col}, inplace=True)
        df_leaderboard[resultado_col].fillna("--", inplace=True)
        
    # Calcula o total de pontos.
    pontos_cols = [f'{wod}_Pontos' for wod in wod_base_names]
    df_leaderboard['Total Pontos'] = df_leaderboard[pontos_cols].sum(axis=1)
    
    # Lógica de desempate em cascata.
    max_placements = len(df_leaderboard)
    placement_cols = [] 
    for i in range(1, max_placements + 1):
        placement_col_name = f'placements_{i}'
        df_leaderboard[placement_col_name] = (df_leaderboard[pontos_cols] == i).sum(axis=1)
        placement_cols.append(placement_col_name)

    tie_breaking_columns = ['Total Pontos'] + placement_cols
    
    sort_by_columns = tie_breaking_columns + ['Time']
    sort_ascending_order = [True] + [False] * len(placement_cols) + [True]

    df_classificado = df_leaderboard.sort_values(
        by=sort_by_columns,
        ascending=sort_ascending_order
    ).reset_index(drop=True)

    # Lógica de Ranking Compartilhado.
    ranks = []
    current_rank = 0
    tie_count = 0
    previous_tie_values = None

    for index, row in df_classificado.iterrows():
        current_tie_values = tuple(row[tie_breaking_columns])

        if previous_tie_values is None or current_tie_values != previous_tie_values:
            current_rank += tie_count + 1
            tie_count = 0
        else:
            tie_count += 1
        
        ranks.append(current_rank)
        previous_tie_values = current_tie_values

    df_classificado['Rank'] = ranks
    
    all_categories_data[category_name] = df_classificado.to_dict('records')

# --- Geração do HTML ---
env = Environment(loader=FileSystemLoader('.'))
template = env.get_template('template.html')
fuso_horario_sp = pytz.timezone('America/Sao_Paulo')
data_atualizacao = datetime.now(fuso_horario_sp).strftime('%d/%m/%Y %H:%M:%S')

html_gerado = template.render(
    categories_data=all_categories_data,
    wods_base_names=wod_base_names,
    data_atualizacao=data_atualizacao
)

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html_gerado)

print(f"Tabela gerada com sucesso!")