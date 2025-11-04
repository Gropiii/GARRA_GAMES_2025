import pandas as pd
from jinja2 import Environment, FileSystemLoader
from datetime import datetime
import pytz
import warnings
import numpy as np # Biblioteca para limpeza de dados
import time # Biblioteca para o "cache buster"

# Ignora avisos informativos do Pandas para uma saída limpa no terminal.
warnings.filterwarnings(
    "ignore",
    category=FutureWarning,
    message="Downcasting object dtype arrays on .fillna"
)

# --- ### PONTO DE MODIFICAÇÃO PRINCIPAL ### ---
#
# URL_BASE: É o link da sua planilha.
# Para um novo campeonato, você só precisa trocar esta linha.
# (Vá em Arquivo > Compartilhar > Publicar na web > .csv)
#
URL_BASE = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vTP2LvRBgCHWvoGeguayoAX5BBYyJVqjrpX9mddDzXJ7_BlhcLlcEJkQGDn4i99K7ZQTcxaR65zoQbu/pub?gid=0&single=true&output=csv'

# Adiciona um "cache buster" à URL para forçar o download de dados novos a cada execução.
URL_SHEETS = f"{URL_BASE}&cache_bust={int(time.time())}"


# --- LÓGICA DO CAMPEONATO (Normalmente não precisa de alteração) ---
try:
    df_raw = pd.read_csv(URL_SHEETS)
    # Limpa as células vazias ou com apenas espaços.
    df_raw.replace(r'^\s*$', np.nan, regex=True, inplace=True)
except Exception as e:
    print(f"Erro ao ler dados da planilha: {e}")
    exit()

# Identifica os nomes base dos WODs de forma dinâmica (procurando por "_Resultado").
wod_base_names = sorted(list(set([col.replace('_Resultado', '') for col in df_raw.columns if col.endswith('_Resultado')])))

all_categories_data = {}

# 1. Agrupa os dados pela coluna 'Categoria' (ex: "Iniciante Feminino", "Scaled Masculino", etc.).
for category_name, df_category_raw in df_raw.groupby('Categoria'):
    
    df_leaderboard = pd.DataFrame({'Time': df_category_raw['Time']})
    
    # 2. Itera sobre cada WOD para calcular os pontos.
    for wod_base in wod_base_names:
        resultado_col = f'{wod_base}_Resultado' 
        pontos_col = f'{wod_base}_Pontos'

        df_wod_full = df_category_raw[['Time', resultado_col]].copy()
        
        # Filtra apenas os Times que TÊM um resultado preenchido.
        df_wod_participantes = df_wod_full.dropna(subset=[resultado_col]).copy()

        # Lógica de pontuação dinâmica para Times ausentes.
        if df_wod_participantes.empty:
            penalty_score = 0
            df_wod_ranked = pd.DataFrame(columns=['Time', 'Resultado', pontos_col])
        else:
            penalty_score = len(df_wod_participantes) + 1
            
            df_wod_participantes.rename(columns={resultado_col: 'Resultado'}, inplace=True)
            
            # Determina a métrica (Tempo, Reps, etc.) pelo nome da coluna.
            metrica = wod_base.split('_')[-1].lower()
            is_time = (metrica == 'tempo')

            if not is_time:
                df_wod_participantes['Resultado_Num'] = pd.to_numeric(df_wod_participantes['Resultado'], errors='coerce')
            else:
                df_wod_participantes['Resultado_Num'] = df_wod_participantes['Resultado']

            # --- LÓGICA DE RANKING SIMPLIFICADA ---
            # Calcula o rank (pontos) simples DENTRO da categoria.
            df_wod_participantes[pontos_col] = df_wod_participantes['Resultado_Num'].rank(method='min', ascending=is_time)
            df_wod_ranked = df_wod_participantes

        # Junta os dados rankeados de volta na lista COMPLETA de Times.
        df_leaderboard = pd.merge(df_leaderboard, df_wod_ranked[['Time', 'Resultado', pontos_col]], on='Time', how='left')
        
        # Aplica a pontuação de penalidade e converte a coluna para inteiro.
        df_leaderboard[pontos_col] = df_leaderboard[pontos_col].fillna(penalty_score).astype(int)

        # Preenche os resultados vazios com "--".
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

    # Define as colunas que definem um EMPATE REAL.
    tie_breaking_columns = ['Total Pontos'] + placement_cols
    
    # Cria a lista completa de critérios para a ORDENAÇÃO (incluindo o nome para desempate final).
    sort_by_columns = tie_breaking_columns + ['Time']
    sort_ascending_order = [True] + [False] * len(placement_cols) + [True]

    # Aplica a ordenação multi-critério.
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
    
    # Guarda os dados processados da categoria no dicionário principal.
    all_categories_data[category_name] = df_classificado.to_dict('records')

# --- Geração do HTML ---
env = Environment(loader=FileSystemLoader('.'))
template = env.get_template('template.html')
fuso_horario_sp = pytz.timezone('America/Sao_Paulo') # Fuso horário
data_atualizacao = datetime.now(fuso_horario_sp).strftime('%d/%m/%Y %H:%M:%S')

html_gerado = template.render(
    categories_data=all_categories_data,
    wods_base_names=wod_base_names,
    data_atualizacao=data_atualizacao
)

# Salva o resultado no arquivo final.
with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html_gerado)

print(f"Tabela gerada com sucesso!")