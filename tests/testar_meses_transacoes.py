#!/usr/bin/env python3
"""
Teste unitário para a função extrair_meses_transacoes.
"""
import sys
import os

# Adiciona o diretório pai ao path para importar a função
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Simula a função extrair_meses_transacoes (cópia da implementação)
from datetime import datetime

def extrair_meses_transacoes(transacoes: list[dict]) -> tuple[str, str]:
    """
    Extrai o mês da transação mais antiga (start_month) e mais nova (end_month).
    Retorna uma tupla (start_month, end_month) no formato "YYYY-MM".
    """
    if not transacoes:
        return None, None
    
    datas_validas = []
    
    for transacao in transacoes:
        data_str = transacao.get('data', '')
        if not data_str:
            continue
            
        try:
            # Tenta diferentes formatos de data
            formatos = [
                '%Y-%m-%d',    # 2024-01-15
                '%d/%m/%Y',    # 15/01/2024
                '%d-%m-%Y',    # 15-01-2024
                '%m/%d/%Y',    # 01/15/2024
                '%Y/%m/%d',    # 2024/01/15
                '%d/%m/%y',    # 15/01/24
                '%m/%d/%y',    # 01/15/24
                '%y-%m-%d',    # 24-01-15
            ]
            
            data_parseada = None
            for formato in formatos:
                try:
                    data_parseada = datetime.strptime(data_str, formato)
                    break
                except ValueError:
                    continue
            
            if data_parseada:
                datas_validas.append(data_parseada)
                
        except Exception as e:
            print(f"DEBUG: Erro ao parsear data '{data_str}': {e}")
            continue
    
    if not datas_validas:
        return None, None
    
    # Ordena as datas para encontrar a mais antiga e mais nova
    datas_validas.sort()
    
    data_mais_antiga = datas_validas[0]
    data_mais_nova = datas_validas[-1]
    
    start_month = data_mais_antiga.strftime('%Y-%m')
    end_month = data_mais_nova.strftime('%Y-%m')
    
    print(f"DEBUG: Período das transações: {start_month} até {end_month}")
    
    return start_month, end_month

def testar_casos():
    """
    Testa diferentes casos da função extrair_meses_transacoes.
    """
    print("🧪 TESTANDO FUNÇÃO extrair_meses_transacoes\n")
    
    # Teste 1: Lista vazia
    print("Teste 1: Lista vazia")
    resultado = extrair_meses_transacoes([])
    print(f"Resultado: {resultado}")
    assert resultado == (None, None), "Lista vazia deveria retornar (None, None)"
    print("✅ Passou\n")
    
    # Teste 2: Transações sem campo data
    print("Teste 2: Transações sem campo data")
    transacoes_sem_data = [
        {"descricao": "Teste", "valor": 100},
        {"descricao": "Teste 2", "valor": 200}
    ]
    resultado = extrair_meses_transacoes(transacoes_sem_data)
    print(f"Resultado: {resultado}")
    assert resultado == (None, None), "Transações sem data deveriam retornar (None, None)"
    print("✅ Passou\n")
    
    # Teste 3: Uma única transação
    print("Teste 3: Uma única transação")
    transacoes_uma = [
        {"data": "2024-02-15", "descricao": "Teste", "valor": 100}
    ]
    resultado = extrair_meses_transacoes(transacoes_uma)
    print(f"Resultado: {resultado}")
    assert resultado == ("2024-02", "2024-02"), "Uma transação deveria ter start_month = end_month"
    print("✅ Passou\n")
    
    # Teste 4: Transações do mesmo mês
    print("Teste 4: Transações do mesmo mês")
    transacoes_mesmo_mes = [
        {"data": "2024-02-01", "descricao": "Teste 1", "valor": 100},
        {"data": "2024-02-15", "descricao": "Teste 2", "valor": 200},
        {"data": "2024-02-28", "descricao": "Teste 3", "valor": 300}
    ]
    resultado = extrair_meses_transacoes(transacoes_mesmo_mes)
    print(f"Resultado: {resultado}")
    assert resultado == ("2024-02", "2024-02"), "Transações do mesmo mês deveriam ter start_month = end_month"
    print("✅ Passou\n")
    
    # Teste 5: Transações de meses diferentes
    print("Teste 5: Transações de meses diferentes")
    transacoes_meses_diferentes = [
        {"data": "2024-01-15", "descricao": "Janeiro", "valor": 100},
        {"data": "2024-03-10", "descricao": "Março", "valor": 200},
        {"data": "2024-02-05", "descricao": "Fevereiro", "valor": 300}
    ]
    resultado = extrair_meses_transacoes(transacoes_meses_diferentes)
    print(f"Resultado: {resultado}")
    assert resultado == ("2024-01", "2024-03"), "Deveria retornar janeiro (mais antigo) até março (mais novo)"
    print("✅ Passou\n")
    
    # Teste 6: Diferentes formatos de data
    print("Teste 6: Diferentes formatos de data")
    transacoes_formatos_diferentes = [
        {"data": "15/01/2024", "descricao": "DD/MM/YYYY", "valor": 100},
        {"data": "2024-03-10", "descricao": "YYYY-MM-DD", "valor": 200},
        {"data": "05-02-2024", "descricao": "DD-MM-YYYY", "valor": 300}
    ]
    resultado = extrair_meses_transacoes(transacoes_formatos_diferentes)
    print(f"Resultado: {resultado}")
    assert resultado == ("2024-01", "2024-03"), "Deveria parsear diferentes formatos corretamente"
    print("✅ Passou\n")
    
    # Teste 7: Datas inválidas misturadas com válidas
    print("Teste 7: Datas inválidas misturadas com válidas")
    transacoes_mistas = [
        {"data": "2024-01-15", "descricao": "Válida", "valor": 100},
        {"data": "data_inválida", "descricao": "Inválida", "valor": 200},
        {"data": "2024-02-10", "descricao": "Válida", "valor": 300},
        {"data": "", "descricao": "Vazia", "valor": 400}
    ]
    resultado = extrair_meses_transacoes(transacoes_mistas)
    print(f"Resultado: {resultado}")
    assert resultado == ("2024-01", "2024-02"), "Deveria ignorar datas inválidas e processar apenas as válidas"
    print("✅ Passou\n")
    
    # Teste 8: Anos diferentes
    print("Teste 8: Anos diferentes")
    transacoes_anos_diferentes = [
        {"data": "2023-12-25", "descricao": "Dezembro 2023", "valor": 100},
        {"data": "2024-01-15", "descricao": "Janeiro 2024", "valor": 200},
        {"data": "2024-06-10", "descricao": "Junho 2024", "valor": 300}
    ]
    resultado = extrair_meses_transacoes(transacoes_anos_diferentes)
    print(f"Resultado: {resultado}")
    assert resultado == ("2023-12", "2024-06"), "Deveria funcionar com anos diferentes"
    print("✅ Passou\n")
    
    print("🎉 TODOS OS TESTES PASSARAM!")

if __name__ == "__main__":
    testar_casos()