#!/usr/bin/env python3
"""
Script para testar o endpoint de contagem de tokens via upload de arquivo.
"""
import requests
import tempfile
import os

# URL da API (ajuste conforme necessário)
API_URL = "http://localhost:8000"

def criar_arquivo_texto_teste():
    """
    Cria um arquivo de texto temporário para teste.
    """
    texto_teste = """Este é um arquivo de teste para contagem de tokens via upload.
    O Gemini e outros modelos de IA generativa processam entradas e saídas em uma granularidade chamada token.
    Para modelos do Gemini, um token equivale a cerca de quatro caracteres.
    100 tokens equivalem a cerca de 60 a 80 palavras em inglês.
    
    Este arquivo contém várias linhas de texto para simular um documento real.
    Vamos adicionar mais conteúdo para ter uma contagem interessante de tokens.
    
    O endpoint deve conseguir processar este arquivo e retornar:
    - O número total de tokens
    - O status "OK" (já que é um arquivo pequeno)
    - O tipo de arquivo como "text"
    - O nome do arquivo
    - O tamanho do arquivo em bytes
    
    Este é um teste completo do sistema de contagem de tokens.
    """
    
    # Cria arquivo temporário
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
    temp_file.write(texto_teste)
    temp_file.close()
    
    return temp_file.name

def testar_upload_arquivo_texto():
    """
    Testa o endpoint de contagem de tokens com upload de arquivo de texto.
    """
    print("🧪 Testando endpoint de contagem de tokens via upload (arquivo de texto)...")
    
    # Cria arquivo de teste
    arquivo_teste = criar_arquivo_texto_teste()
    
    try:
        # Abre o arquivo para upload
        with open(arquivo_teste, 'rb') as f:
            files = {
                'file': ('teste.txt', f, 'text/plain')
            }
            
            # Faz a requisição para o endpoint
            response = requests.post(
                f"{API_URL}/contar-tokens-upload/",
                files=files,
                timeout=30
            )
        
        print(f"📊 Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Sucesso! Resultado:")
            print(f"   • Total de tokens: {result.get('total_tokens')}")
            print(f"   • Status: {result.get('status')}")
            print(f"   • Tipo de arquivo: {result.get('file_type')}")
            print(f"   • Nome do arquivo: {result.get('filename')}")
            print(f"   • Tamanho do arquivo: {result.get('file_size')} bytes")
            print(f"   • Content-Type: {result.get('content_type')}")
            
            # Verifica se o status está correto (deve ser "OK" para arquivo pequeno)
            if result.get('status') == 'OK':
                print("✅ Status correto: arquivo pequeno retornou 'OK'")
            else:
                print("⚠️  Status inesperado para arquivo pequeno")
                
        else:
            print("❌ Erro na requisição:")
            try:
                error_data = response.json()
                print(f"   • Erro: {error_data.get('error_message', 'Erro desconhecido')}")
            except:
                print(f"   • Resposta: {response.text}")
                
    except requests.exceptions.ConnectionError:
        print("❌ Erro: Não foi possível conectar à API. Verifique se o servidor está rodando em http://localhost:8000")
    except requests.exceptions.Timeout:
        print("❌ Erro: Timeout na requisição")
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
    finally:
        # Remove arquivo temporário
        try:
            os.unlink(arquivo_teste)
        except:
            pass

def testar_upload_arquivo_vazio():
    """
    Testa o endpoint com um arquivo vazio.
    """
    print("\n🧪 Testando com arquivo vazio...")
    
    # Cria arquivo vazio
    temp_file = tempfile.NamedTemporaryFile(suffix='.txt', delete=False)
    temp_file.close()  # Arquivo vazio
    
    try:
        with open(temp_file.name, 'rb') as f:
            files = {
                'file': ('vazio.txt', f, 'text/plain')
            }
            
            response = requests.post(
                f"{API_URL}/contar-tokens-upload/",
                files=files,
                timeout=30
            )
        
        print(f"📊 Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print("✅ Esperado: erro para arquivo vazio")
            try:
                error_data = response.json()
                print(f"   • Erro: {error_data.get('error_message')}")
            except:
                print(f"   • Resposta: {response.text}")
        else:
            print("⚠️  Inesperado: sucesso com arquivo vazio")
            
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
    finally:
        # Remove arquivo temporário
        try:
            os.unlink(temp_file.name)
        except:
            pass

def testar_upload_arquivo_grande():
    """
    Testa com um arquivo maior (mas ainda razoável para o teste).
    """
    print("\n🧪 Testando com arquivo de texto maior...")
    
    # Cria um arquivo maior repetindo o texto
    texto_base = """Este é um texto base que será repetido muitas vezes para criar um arquivo maior.
    Cada repetição adiciona mais tokens ao total. O objetivo é ver como o sistema se comporta
    com arquivos maiores, mas ainda dentro de limites razoáveis para teste.
    """
    
    # Repete o texto para criar um arquivo maior
    texto_grande = texto_base * 100  # Repete 100 vezes
    
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
    temp_file.write(texto_grande)
    temp_file.close()
    
    try:
        with open(temp_file.name, 'rb') as f:
            files = {
                'file': ('texto_grande.txt', f, 'text/plain')
            }
            
            response = requests.post(
                f"{API_URL}/contar-tokens-upload/",
                files=files,
                timeout=30
            )
        
        print(f"📊 Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Sucesso! Resultado:")
            print(f"   • Total de tokens: {result.get('total_tokens')}")
            print(f"   • Status: {result.get('status')}")
            print(f"   • Tamanho do arquivo: {result.get('file_size')} bytes")
            
            # Para este arquivo maior, esperamos mais tokens, mas ainda "OK"
            if result.get('status') == 'OK':
                print("✅ Status 'OK' - arquivo ainda está abaixo do limite de 100k tokens")
            else:
                print("⚠️  Status 'Exceeded' - arquivo ultrapassou 100k tokens")
                
        else:
            print("❌ Erro na requisição:")
            try:
                error_data = response.json()
                print(f"   • Erro: {error_data.get('error_message')}")
            except:
                print(f"   • Resposta: {response.text}")
                
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
    finally:
        # Remove arquivo temporário
        try:
            os.unlink(temp_file.name)
        except:
            pass

if __name__ == "__main__":
    print("🚀 Iniciando testes do endpoint de contagem de tokens via upload\n")
    
    # Teste 1: Arquivo de texto normal
    testar_upload_arquivo_texto()
    
    # Teste 2: Arquivo vazio
    testar_upload_arquivo_vazio()
    
    # Teste 3: Arquivo maior
    testar_upload_arquivo_grande()
    
    print("\n✨ Testes concluídos!")