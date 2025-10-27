import uvicorn
import httpx
import sys
import json
import asyncio # Importar asyncio para CancelledError
from fastapi import FastAPI, Request, HTTPException

# --- Parte 1: O Receptor do Webhook ---

# Este é um mini-servidor que você roda na SUA máquina
# para receber o JSON final da API principal.
app_cliente = FastAPI()

@app_cliente.post("/webhook-receiver")
async def receber_resultado(request: Request):
    """
    Este endpoint recebe o JSON final da API de processamento.
    """
    try:
        data = await request.json()
        
        print("\n--- !!! RESULTADO DO WEBHOOK RECEBIDO !!! ---")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print("-------------------------------------------------")
        
        if data.get("success"):
            print(f"Sucesso: {data.get('transactions_count')} transações processadas.")
        else:
            print(f"Erro: {data.get('error_message')}")
            
        return {"status": "recebido"}
        
    except Exception as e:
        print(f"ERRO ao processar webhook recebido: {e}")
        return {"status": "erro_no_receiver"}

# --- Parte 2: O Script de Chamada ---

async def chamar_api_com_webhook(pdf_url: str, webhook_url: str):
    """
    Função que faz o POST para a sua API principal.
    """
    api_principal_url = "http://127.0.0.1:8000/processar-extrato-url/"
    
    payload = {
        "file_url": pdf_url,
        "webhook_url": webhook_url
    }
    
    print(f"Chamando API em {api_principal_url} com:")
    print(f" - PDF URL: {pdf_url}")
    print(f" - Webhook URL: {webhook_url}\n")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(api_principal_url, json=payload, timeout=10.0)
            
            response.raise_for_status() # Lança erro se a API falhar (ex: 4xx, 5xx)
            
            print("Resposta da API (Síncrona):")
            print(response.json())
            print("\n>>> Processamento iniciado em background. Aguardando webhook...")
            
    except httpx.RequestError as e:
        print(f"\nERRO ao chamar a API principal: {e}")
        print("Verifique se a 'api_rapida.py' está rodando em http://127.0.0.1:8000")
    except Exception as e:
        print(f"\nERRO inesperado ao chamar API: {e}")

# --- Parte 3: Execução (CORRIGIDA) ---

async def rodar_servidor_receptor_async():
    """
    Roda o servidor FastAPI que recebe o webhook, de forma assíncrona,
    usando o loop de eventos já existente.
    """
    print("Iniciando servidor receptor de webhook em http://127.0.0.1:8001")
    print("Pressione CTRL+C para parar O SERVIDOR RECEPTOR (não o script de chamada).")
    
    config = uvicorn.Config(app_cliente, host="127.0.0.1", port=8001, log_level="warning")
    server = uvicorn.Server(config)
    
    try:
        # uvicorn.run() é síncrono e cria seu próprio loop.
        # server.serve() é assíncrono e usa o loop existente.
        await server.serve()
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nServidor receptor parado.")
        server.should_exit = True
        # Aguarda o servidor desligar graciosamente
        await server.shutdown()


async def main():
    """
    Função principal para executar o script.
    """
    print("----------------------------------------------------------------------")
    print("Este script fará duas coisas:")
    print("1. [Em 5 segundos] Fará uma chamada de API para iniciar o processamento.")
    print("2. [Imediatamente] Iniciará um servidor na porta 8001 para RECEBER o resultado.")
    print("----------------------------------------------------------------------")
    
    # --- !!! IMPORTANTE !!! ---
    # A API (rodando na porta 8000) precisa conseguir acessar este script (porta 8001).
    # Se ambos estiverem no 'localhost', talvez não funcione.
    #
    # SOLUÇÃO: Use 'ngrok' para expor sua porta 8001 publicamente.
    # 1. Baixe o ngrok
    # 2. Rode: ./ngrok http 8001
    # 3. Pegue a URL "Forwarding" (ex: https://abcd-1234.ngrok.io)
    # 4. Cole essa URL pública abaixo:
    
    # Substitua pela sua URL pública do ngrok
    # Ex: "https://seu-dominio-publico.ngrok.io/webhook-receiver"
    WEBHOOK_URL_PUBLICA = "https://stephaine-hyperbolic-intelligibly.ngrok-free.dev/webhook-receiver"

    # Substitua por uma URL de um PDF de teste online
    PDF_DE_TESTE_URL = "https://uugjjiacxcqcpayzpthl.supabase.co/storage/v1/object/public/quartavia/uploads/1761229557_Picpay.pdf" 
    # (Use um dos seus extratos em um S3 ou link público)

    if "COLE-SUA-URL" in WEBHOOK_URL_PUBLICA:
        print("ERRO: Edite o script 'cliente_webhook.py' e defina a WEBHOOK_URL_PUBLICA.")
        sys.exit(1)
        
    if "dummy.pdf" in PDF_DE_TESTE_URL:
        print("AVISO: Usando um PDF dummy. Edite o script para usar um extrato real.")
        
    # Inicia a chamada da API (após um pequeno delay)
    # (Não queremos que a chamada bloqueie o início do servidor)
    async def task_chamar_api():
        await asyncio.sleep(5) # Dá 5 segundos para o servidor Uvicorn abaixo iniciar
        await chamar_api_com_webhook(PDF_DE_TESTE_URL, WEBHOOK_URL_PUBLICA)
    
    # Cria a tarefa de chamada
    api_task = asyncio.create_task(task_chamar_api())
    
    # Roda o servidor receptor (bloqueia o main aqui, mas é async)
    server_task = rodar_servidor_receptor_async()

    # Espera ambas as tarefas. A server_task rodará "para sempre"
    # até ser interrompida (Ctrl+C).
    await asyncio.gather(server_task, api_task)


if __name__ == "__main__":
    # Nota: O uvicorn.run() deve estar na thread principal.
    # A chamada de API será lançada como uma tarefa asyncio.
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScript principal encerrado.")

