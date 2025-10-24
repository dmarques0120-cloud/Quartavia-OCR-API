import os
import uvicorn
import asyncio
import io
import time
import json
import base64
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel # Para aceitar a URL
from openai import AsyncOpenAI # Importa o cliente Async da OpenAI

# --- Bibliotecas de Extração ---
import pdfplumber
import fitz  # PyMuPDF

# --- Módulos de Prompt e API ---
import httpx # Biblioteca HTTP assíncrona moderna (ainda necessária para baixar a URL)
from prompt_e_schema import PROMPT_SISTEMA, CATEGORIAS_COMPLETAS

load_dotenv()

# --- Configuração ---
app = FastAPI(
    title="API Rápida de Extratos (Versão OpenAI c/ Webhook)",
    description="Substitui o CrewAI por um pipeline otimizado para < 15s."
)

# --- Configuração OpenAI ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("ERRO CRÍTICO: Variável de ambiente OPENAI_API_KEY não definida.")
    # A aplicação irá falhar ao tentar inicializar o cliente, o que é o esperado.

MODEL_OPENAI = os.getenv("MODEL_OPENAI") # gpt-4o é o mais rápido e eficiente para visão e texto

# Cliente HTTP assíncrono (para baixar PDFs da URL e enviar webhooks)
http_client = httpx.AsyncClient(timeout=30.0)
# Cliente Async da OpenAI
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=30.0)


# --- Modelo Pydantic para o Payload da URL ---
class URLPayload(BaseModel):
    file_url: str
    webhook_url: str # NOVO: URL para enviar o resultado final


# --- ETAPA 1: Extração Nativa (Inalterada) ---
async def extrair_texto_nativo(pdf_bytes: bytes) -> str | None:
    """
    Tenta extrair texto nativo do PDF. Rápido.
    Retorna o texto bruto ou None se for uma imagem/vazio.
    """
    print("DEBUG: Iniciando Tentativa 1: Extração Nativa...")
    texto_completo = ""
    try:
        # Abre o PDF diretamente dos bytes em memória
        with io.BytesIO(pdf_bytes) as f:
            with pdfplumber.open(f) as pdf:
                if not pdf.pages:
                    print("DEBUG: PDF sem páginas.")
                    return None
                    
                for page in pdf.pages:
                    # Tenta apenas a extração simples. É mais rápida.
                    texto_pagina = page.extract_text(x_tolerance=2)
                    if texto_pagina:
                        texto_completo += texto_pagina + "\n\n--- NOVA PÁGINA ---\n\n"
        
        # Limite de sanidade: Se extraiu menos de 100 caracteres,
        # provavelmente é um PDF de imagem ou protegido.
        if len(texto_completo.strip()) < 100:
            print("DEBUG: Extração nativa falhou (texto muito curto).")
            return None
            
        print(f"DEBUG: Extração nativa SUCESSO ({len(texto_completo)} caracteres).")
        return texto_completo
        
    except Exception as e:
        print(f"ERRO na extração nativa: {e}. Tentando OCR.")
        return None

# --- ETAPA 2: Extração OCR (Otimizada para OpenAI) ---
def pdf_para_imagens_b64(pdf_bytes: bytes) -> list[dict]:
    """
    Converte *todas* as páginas do PDF em uma lista de imagens base64
    no formato esperado pela API da OpenAI.
    """
    imagens_parts = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) # 2x zoom
            img_bytes = pix.tobytes("png")
            b64_data = base64.b64encode(img_bytes).decode('utf-8')
            # Formato específico da OpenAI para imagens
            imagens_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64_data}"
                }
            })
        doc.close()
        return imagens_parts
    except Exception as e:
        print(f"ERRO ao converter PDF para imagens: {e}")
        return []

async def extrair_texto_ocr(pdf_bytes: bytes) -> str | None:
    """
    Envia *todas* as imagens do PDF para a OpenAI em UMA ÚNICA CHAMADA.
    """
    print("DEBUG: Iniciando Tentativa 2: Extração OCR...")
    
    # Executa a conversão de imagem (pesada) em uma thread separada
    imagens_parts = await asyncio.to_thread(pdf_para_imagens_b64, pdf_bytes)
    
    if not imagens_parts:
        print("ERRO: OCR falhou na conversão de imagem.")
        return None

    print(f"DEBUG: Convertidas {len(imagens_parts)} páginas para OCR. Enviando UMA chamada para OpenAI...")

    # Constrói o payload com múltiplas imagens
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Extraia todo o texto visível de cada uma destas páginas de extrato bancário, em ordem. Retorne apenas o texto bruto."},
                *imagens_parts # Desempacota a lista de imagens aqui
            ]
        }
    ]
    
    try:
        response = await openai_client.chat.completions.create(
            model=MODEL_OPENAI,
            messages=messages,
            max_tokens=4096,
            temperature=0.0
        )
        
        texto_ocr = response.choices[0].message.content
        
        if not texto_ocr:
             print(f"DEBUG: OCR SUCESSO (texto vazio).")
             return None

        print(f"DEBUG: OCR SUCESSO ({len(texto_ocr)} caracteres).")
        return texto_ocr
        
    except Exception as e:
        print(f"ERRO na API de Visão (OpenAI OCR): {e}")
        return None

# --- FUNÇÃO AUXILIAR: Divisão de Texto ---
def dividir_texto_em_chunks(texto: str, max_chars: int = 500) -> list[str]:
    """
    Divide um texto grande em chunks menores, preservando linhas completas.
    """
    if len(texto) <= max_chars:
        return [texto]
    
    chunks = []
    linhas = texto.split('\n')
    chunk_atual = ""
    
    for linha in linhas:
        # Se adicionar esta linha não ultrapassar o limite, adiciona
        if len(chunk_atual + linha + '\n') <= max_chars:
            chunk_atual += linha + '\n'
        else:
            # Se o chunk atual não está vazio, salva ele
            if chunk_atual.strip():
                chunks.append(chunk_atual.strip())
            # Inicia novo chunk com a linha atual
            chunk_atual = linha + '\n'
    
    # Adiciona o último chunk se não estiver vazio
    if chunk_atual.strip():
        chunks.append(chunk_atual.strip())
    
    return chunks

# --- FUNÇÃO AUXILIAR: Processar Chunk Individual ---
async def processar_chunk_individual(chunk: str, chunk_index: int) -> dict:
    """
    Processa um chunk individual de texto e retorna as transações encontradas.
    """
    print(f"DEBUG: Processando chunk {chunk_index + 1} ({len(chunk)} caracteres)...")
    
    prompt_chunk = f"""
Analise este fragmento de extrato financeiro e extraia TODAS as transações.
Este é o chunk {chunk_index + 1} de um documento maior.

**REGRAS DE CATEGORIZAÇÃO:**
{CATEGORIAS_COMPLETAS}

**FRAGMENTO DO TEXTO:**
{chunk}
"""

    messages = [
        {"role": "system", "content": PROMPT_SISTEMA},
        {"role": "user", "content": prompt_chunk}
    ]
    
    try:
        response = await openai_client.chat.completions.create(
            model=MODEL_OPENAI,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0
        )
        
        json_text = response.choices[0].message.content
        resultado = json.loads(json_text)
        
        print(f"DEBUG: Chunk {chunk_index + 1} processado: {len(resultado.get('transactions', []))} transações encontradas.")
        return resultado
        
    except Exception as e:
        print(f"ERRO no processamento do chunk {chunk_index + 1}: {e}")
        return {
            "success": False,
            "transactions": [],
            "error_message": f"Erro no chunk {chunk_index + 1}: {str(e)}"
        }

# --- FUNÇÃO AUXILIAR: Consolidar Resultados ---
def consolidar_resultados_chunks(resultados_chunks: list[dict]) -> dict:
    """
    Consolida os resultados de múltiplos chunks em um resultado final.
    """
    todas_transacoes = []
    bank_name = "TBD"
    document_type = "unknown"
    erros_reais = []  # Apenas erros de processamento, não de "nenhuma transação"
    
    for resultado in resultados_chunks:
        if resultado.get("success", False):
            transacoes = resultado.get("transactions", [])
            todas_transacoes.extend(transacoes)
            
            # Pega o bank_name e document_type do primeiro chunk bem-sucedido
            if bank_name == "TBD" and resultado.get("bank_name"):
                bank_name = resultado["bank_name"]
            if document_type == "unknown" and resultado.get("document_type"):
                document_type = resultado["document_type"]
        else:
            # Só inclui erros que NÃO são "Nenhuma transação encontrada"
            erro = resultado.get("error_message", "Erro desconhecido")
            if "Nenhuma transação encontrada" not in erro:
                erros_reais.append(erro)
    
    # Remove transações duplicadas baseado em data, descrição e valor
    transacoes_unicas = []
    transacoes_vistas = set()
    
    for transacao in todas_transacoes:
        chave = (transacao.get('data', ''), 
                transacao.get('descricao', ''), 
                transacao.get('valor', 0))
        if chave not in transacoes_vistas:
            transacoes_vistas.add(chave)
            transacoes_unicas.append(transacao)
    
    # Define error_message apenas se não há transações E há erros reais
    error_message = None
    if len(transacoes_unicas) == 0:
        if erros_reais:
            error_message = "; ".join(erros_reais)
        else:
            error_message = "Nenhuma transação encontrada no documento"
    elif erros_reais:
        # Se há transações mas também erros reais, inclui os erros
        error_message = "; ".join(erros_reais)
    
    resultado_final = {
        "success": len(transacoes_unicas) > 0,
        "bank_name": bank_name,
        "document_type": document_type,
        "transactions_count": len(transacoes_unicas),
        "transactions": transacoes_unicas,
        "error_message": error_message
    }
    
    return resultado_final

# --- ETAPA 3: Análise e Categorização (Com Processamento Paralelo) ---
async def categorizar_com_llm(texto_bruto: str) -> dict:
    """
    Recebe o texto bruto e processa usando chunks paralelos para melhor performance
    e captura mais completa de transações.
    """
    print("DEBUG: Iniciando Etapa 3: Análise e Categorização (Processamento Paralelo)...")
    
    # Verifica se o texto é pequeno o suficiente para processamento direto
    if len(texto_bruto) <= 400:
        print("DEBUG: Texto pequeno, processamento direto...")
        
        prompt_usuario = f"""
Aqui está o texto bruto extraído de um documento financeiro.
Analise-o, extraia TODAS as transações, categorize-as e retorne o JSON formatado.

**REGRAS DE CATEGORIZAÇÃO:**
{CATEGORIAS_COMPLETAS}

**TEXTO BRUTO PARA ANÁLISE:**
{texto_bruto}
"""

        messages = [
            {"role": "system", "content": PROMPT_SISTEMA},
            {"role": "user", "content": prompt_usuario}
        ]
        
        try:
            response = await openai_client.chat.completions.create(
                model=MODEL_OPENAI,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0
            )
            
            json_text = response.choices[0].message.content
            json_output = json.loads(json_text) 
            
            print("DEBUG: Análise direta concluída com SUCESSO.")
            return json_output
            
        except Exception as e:
            print(f"ERRO na análise direta: {e}")
            raise HTTPException(status_code=500, detail=f"Erro na LLM: {e}")
    
    else:
        print(f"DEBUG: Texto extenso ({len(texto_bruto)} chars), usando processamento paralelo...")
        
        # Divide o texto em chunks
        chunks = dividir_texto_em_chunks(texto_bruto, max_chars=500)
        print(f"DEBUG: Texto dividido em {len(chunks)} chunks.")
        
        # Processa todos os chunks em paralelo
        tasks = [
            processar_chunk_individual(chunk, i) 
            for i, chunk in enumerate(chunks)
        ]
        
        resultados_chunks = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filtra exceções e mantém apenas resultados válidos
        resultados_validos = []
        for i, resultado in enumerate(resultados_chunks):
            if isinstance(resultado, Exception):
                print(f"ERRO no chunk {i + 1}: {resultado}")
                resultados_validos.append({
                    "success": False,
                    "transactions": [],
                    "error_message": f"Erro no chunk {i + 1}: {str(resultado)}"
                })
            else:
                resultados_validos.append(resultado)
        
        # Consolida todos os resultados
        resultado_final = consolidar_resultados_chunks(resultados_validos)
        
        print(f"DEBUG: Processamento paralelo concluído. Total de transações: {resultado_final['transactions_count']}")
        return resultado_final


# --- Refatoração: Lógica de Processamento Principal (Síncrono) ---
async def _processar_bytes_sync(pdf_bytes: bytes) -> JSONResponse:
    """
    Função interna que executa o pipeline principal e retorna o resultado.
    Usada pelo endpoint de upload de arquivo (síncrono).
    """
    start_time = time.time()
    
    # ETAPA 1: Tentar extração nativa
    texto_bruto = await extrair_texto_nativo(pdf_bytes)
    
    # ETAPA 2: Se falhar, tentar OCR
    if texto_bruto is None:
        texto_bruto = await extrair_texto_ocr(pdf_bytes)
        
    if texto_bruto is None:
        raise HTTPException(status_code=400, detail="Falha ao extrair texto do PDF (Nativo e OCR).")
        
    # ETAPA 3: Análise e Formatação (Chamada Única)
    try:
        json_final = await categorizar_com_llm(texto_bruto)
        
        end_time = time.time()
        print(f"SUCESSO: Processamento concluído em {end_time - start_time:.2f} segundos.")
        
        # Atualiza a contagem de transações com base no que foi extraído
        if "transactions" in json_final and isinstance(json_final["transactions"], list):
            json_final["transactions_count"] = len(json_final["transactions"])
            
        return JSONResponse(content=json_final)
        
    except HTTPException as e:
        # Repassa o erro da LLM
        return JSONResponse(status_code=e.status_code, content={"success": False, "error_message": e.detail})
    except Exception as e:
        print(f"ERRO Inesperado no pipeline: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error_message": f"Erro inesperado: {e}"})

# --- NOVO: Lógica de Processamento em Background (Assíncrono com Webhook) ---
async def processar_e_enviar_webhook(file_url: str, webhook_url: str):
    """
    Worker de background: baixa, processa e envia o resultado para o webhook.
    """
    start_time = time.time()  # Início do cronômetro
    print(f"INFO [BG]: Iniciando processamento para: {file_url}")
    print(f"INFO [BG]: Webhook de destino: {webhook_url}")
    json_resultado = {}
    
    try:
        # 1. Baixar o PDF da URL
        try:
            response = await http_client.get(file_url)
            response.raise_for_status()
            pdf_bytes = await response.aread()
        except httpx.RequestError as e:
            print(f"ERRO [BG]: Falha ao baixar a URL: {e}")
            raise HTTPException(status_code=400, detail=f"Falha ao baixar o PDF da URL: {e}")

        # 2. Tentar extração nativa
        texto_bruto = await extrair_texto_nativo(pdf_bytes)
        
        # 3. Se falhar, tentar OCR
        if texto_bruto is None:
            texto_bruto = await extrair_texto_ocr(pdf_bytes)
            
        if texto_bruto is None:
            raise HTTPException(status_code=400, detail="Falha ao extrair texto do PDF (Nativo e OCR).")
        
        # 4. Análise e Formatação (Chamada Única)
        json_resultado = await categorizar_com_llm(texto_bruto)
        
        # 5. Atualiza a contagem de transações
        if "transactions" in json_resultado and isinstance(json_resultado["transactions"], list):
            json_resultado["transactions_count"] = len(json_resultado["transactions"])

        print(f"SUCESSO [BG]: Processamento concluído para: {file_url}")

    except Exception as e:
        print(f"ERRO [BG]: Falha no pipeline: {e}")
        detail = e.detail if isinstance(e, HTTPException) else str(e)
        json_resultado = {
            "success": False,
            "bank_name": "TBD",
            "document_type": "unknown",
            "transactions_count": 0,
            "transactions": [],
            "error_message": f"Erro no processamento em background: {detail}"
        }
    
    # 6. Enviar resultado para o Webhook (acontece sempre, com sucesso ou erro)
    try:
        print(f"INFO [BG]: Enviando resultado para o webhook: {webhook_url}")
        await http_client.post(webhook_url, json=json_resultado, timeout=10.0)
        
        # Calcular tempo total de processamento
        end_time = time.time()
        tempo_total = end_time - start_time
        
        print(f"INFO [BG]: Webhook enviado com sucesso.")
        print(f"INFO [BG]: ⏱️  TEMPO TOTAL DE PROCESSAMENTO: {tempo_total:.2f} segundos")
        
    except httpx.RequestError as e:
        print(f"ERRO [BG]: Falha ao enviar o POST para o webhook: {e}")
        # A tarefa termina aqui, mas o processamento foi concluído.
        # Em um sistema de produção, você adicionaria isso a uma fila de retentativa.


# --- O Endpoint Principal (Upload de Arquivo - Síncrono) ---
@app.post("/processar-extrato/")
async def processar_extrato_endpoint(file: UploadFile = File(...)):
    """
    Recebe um PDF via upload de arquivo (form-data), 
    executa o pipeline otimizado e retorna o JSON (SÍNCRONO).
    """
    print(f"INFO: Recebido arquivo: {file.filename}")
    pdf_bytes = await file.read()
    return await _processar_bytes_sync(pdf_bytes)


# --- Endpoint de URL (Assíncrono com Webhook) ---
@app.post("/processar-extrato-url/")
async def processar_extrato_url_endpoint(payload: URLPayload, background_tasks: BackgroundTasks):
    """
    Recebe um JSON com uma 'file_url' e 'webhook_url',
    inicia o processamento em background e retorna resposta imediata (ASSÍNCRONO).
    """
    print(f"INFO: Recebida requisição de URL: {payload.file_url}")
    print(f"INFO: Webhook será enviado para: {payload.webhook_url}")
    
    # Adiciona a tarefa pesada (baixar, processar, enviar webhook) ao background
    background_tasks.add_task(
        processar_e_enviar_webhook, 
        file_url=payload.file_url, 
        webhook_url=payload.webhook_url
    )
    
    # Retorna imediatamente
    return JSONResponse(
        status_code=202, # 202 Accepted
        content={"status": "processamento_iniciado", "file_url": payload.file_url}
    )


# --- Para executar localmente ---
if __name__ == "__main__":
    print("Iniciando servidor FastAPI em http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)




