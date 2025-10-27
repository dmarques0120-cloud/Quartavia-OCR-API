import requests
import json

# ========================================
# CONFIGURAÇÃO
# ========================================

API_URL = "http://localhost:8000/"
ENDPOINT = "/processar-extrato-url/"

# URLs para teste
FILE_URL = "https://uugjjiacxcqcpayzpthl.supabase.co/storage/v1/object/public/quartavia/uploads/1761229240_Btg.pdf"
WEBHOOK_URL = "https://webhook.site/175bdbcb-1164-4523-a1ed-0374bf059a61"  # Substitua por uma URL real

def chamar_api_assincrona(file_url, webhook_url, user_id=1):
    """
    Chama a API assíncrona do Quartavia OCR
    
    Args:
        file_url (str): URL do arquivo PDF para processar
        webhook_url (str): URL do webhook para receber o resultado
        user_id (int): ID do usuário para categorizações personalizadas
    
    Returns:
        dict: Resposta da API
    """
    
    # URL completa
    url_completa = API_URL + ENDPOINT
    
    # Payload da requisição
    payload = {
        "file_url": file_url,
        "webhook_url": webhook_url,
        "user_id": user_id
    }
    
    # Headers
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    print("🚀 CHAMADA PARA API QUARTAVIA OCR")
    print("=" * 50)
    print(f"🔗 URL: {url_completa}")
    print(f"📄 Arquivo: {file_url}")
    print(f"🎯 Webhook: {webhook_url}")
    print("-" * 50)
    
    try:
        # Fazer a requisição POST
        print("📤 Enviando requisição...")
        
        response = requests.post(
            url_completa,
            json=payload,
            headers=headers,
            timeout=60  # 60 segundos para account cold start
        )
        
        print(f"📨 Status Code: {response.status_code}")
        
        if response.status_code == 202:  # 202 Accepted
            resultado = response.json()
            print("✅ SUCESSO! Processamento iniciado em background")
            print(f"📊 Status: {resultado.get('status', 'N/A')}")
            print(f"📄 File URL: {resultado.get('file_url', 'N/A')}")
            print("\n🔔 O resultado será enviado para o webhook quando concluído.")
            return {
                "success": True,
                "data": resultado
            }
            
        else:
            print(f"❌ ERRO: Status {response.status_code}")
            print(f"📝 Resposta: {response.text}")
            return {
                "success": False,
                "status_code": response.status_code,
                "error": response.text
            }
            
    except requests.exceptions.Timeout:
        print("⏰ TIMEOUT: Requisição demorou mais de 60 segundos")
        print("💡 Render pode estar fazendo cold start. Tente novamente.")
        return {
            "success": False,
            "error": "Timeout - possível cold start"
        }
        
    except requests.exceptions.ConnectionError:
        print("🔌 ERRO DE CONEXÃO: Não foi possível conectar à API")
        print(f"💡 Verifique se a API está online: {API_URL}")
        return {
            "success": False,
            "error": "Erro de conexão"
        }
        
    except Exception as e:
        print(f"❌ ERRO INESPERADO: {e}")
        return {
            "success": False,
            "error": str(e)
        }

def main():
    """Função principal"""
    
    print("🎯 SCRIPT DE CHAMADA - QUARTAVIA OCR API")
    print("=" * 60)
    
    # Fazer a chamada (exemplo com user_id=123)
    resultado = chamar_api_assincrona(FILE_URL, WEBHOOK_URL, user_id=1)
    
    print("\n" + "=" * 60)
    print("📋 RESULTADO FINAL:")
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    
    if resultado["success"]:
        print("\n✨ Processamento iniciado com sucesso!")
        print("🔔 Monitore seu webhook para receber o resultado.")
    else:
        print("\n❌ Falha na chamada da API.")
        print("💡 Verifique os detalhes do erro acima.")

if __name__ == "__main__":
    main()