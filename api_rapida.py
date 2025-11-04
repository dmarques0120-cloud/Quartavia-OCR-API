# 1 - Importa módulos para diferentes funcionalidades
import os
import uvicorn
import asyncio
import io
import time
import json
import base64
import re
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from google import genai
import pdfplumber
import fitz
import httpx
from prompt_e_schema import PROMPT_SISTEMA, CATEGORIAS_COMPLETAS
from supabase import create_client, Client

# 2 - Carrega variáveis de ambiente do arquivo .env
load_dotenv()

# 3 - Configura aplicação FastAPI
app = FastAPI(
    title="Quartavia OCR API",
    description="v2.0 - Processamento com Paralelismo por Página"
)

# 4 - Verifica se a chave do Gemini existe
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    print("ERRO CRÍTICO: Variável de ambiente GEMINI_API_KEY não definida.")

MODEL_GEMINI = os.getenv("MODEL_GEMINI", "gemini-2.5-flash-lite")

# 5 - Configura conexão com Supabase (opcional)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("AVISO: Variáveis do Supabase não configuradas. Funcionalidade de categorização personalizada desabilitada.")
    supabase = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 6 - Inicializa clientes HTTP e Gemini
http_client = httpx.AsyncClient(timeout=30.0)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)


# 7 - Função para desbloquear PDF com senha
def desbloquear_pdf_com_senha(pdf_bytes: bytes, senha: str | None) -> bytes:
    """
    Tenta desbloquear um PDF protegido por senha.
    Se não há senha ou o PDF não está protegido, retorna os bytes originais.
    """
    if not senha:
        print("DEBUG: Nenhuma senha fornecida, processando PDF normalmente.")
        return pdf_bytes
    
    try:
        # Tenta abrir com PyMuPDF (fitz) primeiro
        print("DEBUG: Tentando desbloquear PDF com a senha fornecida...")
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        if doc.is_encrypted:
            print("DEBUG: PDF está criptografado, aplicando senha...")
            if doc.authenticate(senha):
                print("DEBUG: Senha correta! PDF desbloqueado com sucesso.")
                # Salva o PDF desbloqueado em bytes
                pdf_desbloqueado = doc.write()
                doc.close()
                return pdf_desbloqueado
            else:
                doc.close()
                print("ERRO: Senha incorreta para o PDF.")
                raise HTTPException(status_code=400, detail="Senha incorreta para o PDF protegido.")
        else:
            print("DEBUG: PDF não está criptografado, processando normalmente.")
            doc.close()
            return pdf_bytes
            
    except fitz.FileDataError:
        print("ERRO: Arquivo PDF corrompido ou inválido.")
        raise HTTPException(status_code=400, detail="Arquivo PDF corrompido ou inválido.")
    except Exception as e:
        print(f"ERRO inesperado ao desbloquear PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar PDF protegido: {e}")

# 7.1 - Função para decodificar base64
def decodificar_base64_para_bytes(base64_string: str) -> bytes:
    """
    Decodifica uma string base64 para bytes.
    Remove prefixos como 'data:application/pdf;base64,' se presentes.
    """
    try:
        # Remove prefixo de data URL se existir
        if ',' in base64_string and base64_string.startswith('data:'):
            base64_string = base64_string.split(',', 1)[1]
        
        # Remove espaços em branco
        base64_string = base64_string.strip()
        
        # Decodifica base64
        pdf_bytes = base64.b64decode(base64_string)
        
        # Verifica se é um PDF válido (deve começar com %PDF)
        if not pdf_bytes.startswith(b'%PDF'):
            raise ValueError("Arquivo decodificado não é um PDF válido")
        
        return pdf_bytes
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao decodificar base64: {e}")

# 7.2 - Função para contar tokens de arquivo base64
async def contar_tokens_base64(base64_string: str) -> dict:
    """
    Conta tokens de um arquivo em base64 usando a API Gemini.
    Retorna um dicionário com o resultado da contagem.
    """
    try:
        # Decodifica o base64
        file_bytes = decodificar_base64_para_bytes(base64_string)
        
        # Verifica se é um arquivo de imagem válido (PNG, JPEG, etc.)
        is_image = False
        if file_bytes.startswith(b'\x89PNG') or file_bytes.startswith(b'\xff\xd8\xff'):
            is_image = True
        elif file_bytes.startswith(b'%PDF'):
            # Para PDFs, precisamos converter para imagens primeiro
            # Neste caso, vamos tratar como conteúdo multimodal
            is_image = False
        
        if is_image:
            # Converte bytes da imagem para PIL Image
            import PIL.Image
            image = PIL.Image.open(io.BytesIO(file_bytes))
            
            # Conta tokens para a imagem
            result = gemini_client.models.count_tokens(
                model=MODEL_GEMINI,
                contents=[image]
            )
            
            return {
                "total_tokens": result.total_tokens,
                "type": "image",
                "status": "Exceeded" if result.total_tokens > 100000 else "OK"
            }
        else:
            # Para outros tipos de arquivo (como PDF), tenta processar como documento
            # Neste caso, vamos extrair texto primeiro e depois contar tokens
            if file_bytes.startswith(b'%PDF'):
                # Extrai texto do PDF
                texto_extraido = await extrair_texto_pdf_bytes(file_bytes)
                
                # Conta tokens do texto extraído
                result = gemini_client.models.count_tokens(
                    model=MODEL_GEMINI,
                    contents=texto_extraido
                )
                
                return {
                    "total_tokens": result.total_tokens,
                    "type": "pdf_text",
                    "status": "Exceeded" if result.total_tokens > 100000 else "OK"
                }
            else:
                # Tenta como texto simples
                try:
                    texto = file_bytes.decode('utf-8')
                    result = gemini_client.models.count_tokens(
                        model=MODEL_GEMINI,
                        contents=texto
                    )
                    
                    return {
                        "total_tokens": result.total_tokens,
                        "type": "text",
                        "status": "Exceeded" if result.total_tokens > 100000 else "OK"
                    }
                except UnicodeDecodeError:
                    raise HTTPException(status_code=400, detail="Formato de arquivo não suportado para contagem de tokens")
                
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERRO ao contar tokens: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao contar tokens: {e}")

# 7.3 - Função auxiliar para extrair texto de PDF
async def extrair_texto_pdf_bytes(pdf_bytes: bytes) -> str:
    """
    Extrai texto de um PDF em bytes para contagem de tokens.
    """
    try:
        texto_extraido = ""
        
        # Usa pdfplumber para extrair texto
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for pagina in pdf.pages:
                texto_pagina = pagina.extract_text()
                if texto_pagina:
                    texto_extraido += texto_pagina + "\n"
        
        return texto_extraido.strip()
        
    except Exception as e:
        print(f"ERRO ao extrair texto do PDF: {e}")
        # Se falhar com pdfplumber, tenta com PyMuPDF
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            texto_extraido = ""
            for page_num in range(len(doc)):
                page = doc[page_num]
                texto_extraido += page.get_text() + "\n"
            doc.close()
            return texto_extraido.strip()
        except Exception as e2:
            print(f"ERRO ao extrair texto com PyMuPDF: {e2}")
            raise HTTPException(status_code=500, detail="Erro ao extrair texto do PDF para contagem de tokens")

# 7.4 - Função para contar tokens de UploadFile
async def contar_tokens_upload_file(file: UploadFile) -> dict:
    """
    Conta tokens de um UploadFile usando a API Gemini.
    Retorna um dicionário com o resultado da contagem.
    """
    try:
        # Lê o conteúdo do arquivo
        file_content = await file.read()
        
        # Detecta o tipo de arquivo baseado no content type e extensão
        content_type = file.content_type or ""
        filename = file.filename or ""
        
        print(f"DEBUG: Processando arquivo - Nome: {filename}, Tipo: {content_type}, Tamanho: {len(file_content)} bytes")
        
        # Verifica se é uma imagem
        is_image = False
        if (content_type.startswith("image/") or 
            filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')) or
            file_content.startswith(b'\x89PNG') or 
            file_content.startswith(b'\xff\xd8\xff')):
            is_image = True
        
        if is_image:
            # Converte bytes da imagem para PIL Image
            import PIL.Image
            image = PIL.Image.open(io.BytesIO(file_content))
            
            # Conta tokens para a imagem
            result = gemini_client.models.count_tokens(
                model=MODEL_GEMINI,
                contents=[image]
            )
            
            return {
                "total_tokens": result.total_tokens,
                "type": "image",
                "status": "Exceeded" if result.total_tokens > 100000 else "OK"
            }
            
        # Verifica se é um PDF
        elif (content_type == "application/pdf" or 
              filename.lower().endswith('.pdf') or
              file_content.startswith(b'%PDF')):
            
            # Extrai texto do PDF
            texto_extraido = await extrair_texto_pdf_bytes(file_content)
            
            # Conta tokens do texto extraído
            result = gemini_client.models.count_tokens(
                model=MODEL_GEMINI,
                contents=texto_extraido
            )
            
            return {
                "total_tokens": result.total_tokens,
                "type": "pdf_text",
                "status": "Exceeded" if result.total_tokens > 100000 else "OK"
            }
            
        # Tenta como arquivo de texto
        else:
            try:
                # Tenta decodificar como texto UTF-8
                texto = file_content.decode('utf-8')
                
                result = gemini_client.models.count_tokens(
                    model=MODEL_GEMINI,
                    contents=texto
                )
                
                return {
                    "total_tokens": result.total_tokens,
                    "type": "text",
                    "status": "Exceeded" if result.total_tokens > 100000 else "OK"
                }
                
            except UnicodeDecodeError:
                # Se não conseguir decodificar como texto, tenta outras codificações
                for encoding in ['latin-1', 'cp1252', 'iso-8859-1']:
                    try:
                        texto = file_content.decode(encoding)
                        result = gemini_client.models.count_tokens(
                            model=MODEL_GEMINI,
                            contents=texto
                        )
                        
                        return {
                            "total_tokens": result.total_tokens,
                            "type": f"text_{encoding}",
                            "status": "Exceeded" if result.total_tokens > 100000 else "OK"
                        }
                    except:
                        continue
                
                # Se nenhuma codificação funcionar
                raise HTTPException(
                    status_code=400, 
                    detail=f"Formato de arquivo não suportado para contagem de tokens. Tipo: {content_type}, Nome: {filename}"
                )
                
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERRO ao contar tokens do upload: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao contar tokens: {e}")
    finally:
        # Reseta o ponteiro do arquivo para o início (boa prática)
        await file.seek(0)

# 8 - Define modelos Pydantic para validação
class URLPayload(BaseModel):
    file_url: str
    webhook_url: str
    user_id: int
    senha_do_pdf: str | None = None

class FilePayload(BaseModel):
    user_id: int
    senha_do_pdf: str | None = None

class Base64Payload(BaseModel):
    file_base64: str
    filename: str | None = None
    user_id: int
    senha_do_pdf: str | None = None

class TokenCountPayload(BaseModel):
    file_base64: str
    filename: str | None = None


# 8 - Busca categorizações salvas do usuário
async def buscar_categorizacoes_usuario(user_id: int) -> dict[str, dict]:
    """
    Busca todas as categorizações personalizadas do usuário no Supabase.
    Retorna um dicionário com treated_name como chave e {category, subcategory} como valor.
    """
    if not supabase:
        return {}
    
    try:
        print(f"DEBUG: Buscando categorizações para usuário {user_id}...")
        
        response = supabase.table("Transactions").select("treated_name, category, subcategory").eq("id", user_id).execute()
        
        categorizacoes = {}
        for item in response.data:
            treated_name = item.get("treated_name", "").strip().lower()
            if treated_name:
                categorizacoes[treated_name] = {
                    "categoria": item.get("category", ""),
                    "subcategoria": item.get("subcategory", "")
                }
        
        print(f"DEBUG: Encontradas {len(categorizacoes)} categorizações personalizadas.")
        return categorizacoes
        
    except Exception as e:
        print(f"ERRO ao buscar categorizações do usuário: {e}")
        return {}

# 9 - Aplica categorizações personalizadas
def aplicar_categorizacoes_personalizadas(transacoes: list[dict], categorizacoes_usuario: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """
    Aplica categorizações personalizadas às transações e separa as que precisam ser inseridas.
    Retorna: (transacoes_atualizadas, transacoes_para_inserir)
    """
    transacoes_atualizadas = []
    transacoes_para_inserir = []
    
    print(f"DEBUG: Aplicando categorizações personalizadas em {len(transacoes)} transações...")
    print(f"DEBUG: Categorizações encontradas no banco: {len(categorizacoes_usuario)}")
    
    for transacao in transacoes:
        descricao_original = transacao.get("descricao", "").strip()
        descricao_limpa = limpar_descricao_para_match(descricao_original)
        
        # Verifica se existe uma categorização personalizada
        categoria_encontrada = None
        if categorizacoes_usuario:  # Só verifica se há categorizações existentes
            for treated_name, categorias in categorizacoes_usuario.items():
                if treated_name in descricao_limpa or descricao_limpa in treated_name:
                    categoria_encontrada = categorias
                    break
        
        if categoria_encontrada:
            transacao["categoria"] = categoria_encontrada["categoria"]
            transacao["subcategoria"] = categoria_encontrada["subcategoria"]
            print(f"DEBUG: Aplicada categorização personalizada para '{descricao_original}': {categoria_encontrada['categoria']} > {categoria_encontrada['subcategoria']}")
        else:
            # Sempre adiciona para inserção se não encontrou categorização (incluindo quando não há categorizações no banco)
            transacoes_para_inserir.append({
                "treated_name": descricao_limpa,
                "category": transacao.get("categoria", ""),
                "subcategory": transacao.get("subcategoria", "")
            })
        
        transacoes_atualizadas.append(transacao)
    
    print(f"DEBUG: {len(transacoes_para_inserir)} novas categorizações serão inseridas no banco.")
    return transacoes_atualizadas, transacoes_para_inserir

# 10 - Limpa descrições para matching
def limpar_descricao_para_match(descricao: str) -> str:
    """
    Limpa e normaliza a descrição para melhor matching com treated_name.
    """
    descricao = re.sub(r'\d{2}/\d{2}', '', descricao)
    descricao = re.sub(r'\d+/\d+', '', descricao)
    descricao = re.sub(r'[^\w\s]', ' ', descricao)
    descricao = re.sub(r'\s+', ' ', descricao)
    return descricao.strip().lower()

# 11 - Salva novas categorizações
async def inserir_categorizacoes_usuario(user_id: int, transacoes_para_inserir: list[dict]):
    """
    Insere novas categorizações no Supabase de forma assíncrona.
    """
    if not supabase or not transacoes_para_inserir:
        return
    
    try:
        print(f"DEBUG: Inserindo {len(transacoes_para_inserir)} categorizações para usuário {user_id}...")
        
        dados_para_inserir = []
        for item in transacoes_para_inserir:
            dados_para_inserir.append({
                "id": user_id,
                "treated_name": item["treated_name"],
                "category": item["category"],
                "subcategory": item["subcategory"]
            })
        
        await asyncio.to_thread(
            lambda: supabase.table("Transactions").insert(dados_para_inserir).execute()
        )
        
        print(f"DEBUG: Categorizações inseridas com sucesso para usuário {user_id}.")
        
    except Exception as e:
        print(f"ERRO ao inserir categorizações no Supabase: {e}")


# 12 - Extrai texto nativo por página
async def extrair_texto_nativo_por_paginas(pdf_bytes: bytes) -> list[str]:
    """
    Extrai texto nativo de cada página do PDF separadamente.
    Retorna uma lista com o texto de cada página.
    """
    print("DEBUG: Iniciando extração nativa por páginas...")
    paginas_texto = []
    
    try:
        with io.BytesIO(pdf_bytes) as f:
            with pdfplumber.open(f) as pdf:
                if not pdf.pages:
                    print("DEBUG: PDF sem páginas.")
                    return []
                
                for i, page in enumerate(pdf.pages):
                    texto_pagina = page.extract_text(x_tolerance=2)
                    if texto_pagina and len(texto_pagina.strip()) > 50:
                        paginas_texto.append(texto_pagina.strip())
                        print(f"DEBUG: Página {i+1} extraída: {len(texto_pagina)} caracteres")
                    else:
                        print(f"DEBUG: Página {i+1} vazia ou com pouco texto")
        
        print(f"DEBUG: Extração nativa concluída: {len(paginas_texto)} páginas com texto válido")
        return paginas_texto
        
    except Exception as e:
        print(f"ERRO na extração nativa por páginas: {e}")
        return []

# 13 - Tenta extração nativa primeiro (versão antiga - mantida para compatibilidade)
async def extrair_texto_nativo(pdf_bytes: bytes) -> str | None:
    """
    Tenta extrair texto nativo do PDF. 
    Agora usa processamento por páginas em paralelo.
    """
    print("DEBUG: Iniciando Tentativa 1: Extração Nativa...")
    
    paginas_texto = await extrair_texto_nativo_por_paginas(pdf_bytes)
    
    if not paginas_texto:
        print("DEBUG: Extração nativa falhou (nenhuma página com texto válido).")
        return None
    
    # Se temos poucas páginas, processa diretamente
    if len(paginas_texto) <= 2:
        texto_completo = "\n\n--- NOVA PÁGINA ---\n\n".join(paginas_texto)
        print(f"DEBUG: Extração nativa SUCESSO ({len(texto_completo)} caracteres).")
        return texto_completo
    
    # Se temos muitas páginas, vai para processamento paralelo por página
    print(f"DEBUG: Múltiplas páginas detectadas ({len(paginas_texto)}), será usado processamento paralelo por página.")
    return "\n\n--- NOVA PÁGINA ---\n\n".join(paginas_texto)

# 14 - Converte PDF para imagens base64 por página
def pdf_para_imagens_individuais(pdf_bytes: bytes) -> list[dict]:
    """
    Converte cada página do PDF em uma imagem separada
    no formato esperado pela API do Gemini.
    """
    imagens_individuais = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_bytes = pix.tobytes("png")
            b64_data = base64.b64encode(img_bytes).decode('utf-8')
            imagem_part = {
                "inline_data": {
                    "mime_type": "image/png",
                    "data": b64_data
                }
            }
            imagens_individuais.append({
                "pagina": i + 1,
                "imagem": imagem_part
            })
        doc.close()
        return imagens_individuais
    except Exception as e:
        print(f"ERRO ao converter PDF para imagens individuais: {e}")
        return []

# 15 - Processa OCR de uma página individual
async def processar_ocr_pagina_individual(imagem_data: dict, pagina_num: int) -> dict:
    """
    Processa OCR de uma única página e retorna o texto extraído.
    """
    print(f"DEBUG: Processando OCR da página {pagina_num}...")
    
    contents = [
        {"text": f"Extraia todo o texto visível desta página {pagina_num} de extrato bancário. Retorne apenas o texto bruto."},
        imagem_data["imagem"]
    ]
    
    try:
        response = await asyncio.to_thread(
            gemini_client.models.generate_content,
            model=MODEL_GEMINI,
            contents=contents
        )
        
        texto_pagina = response.text
        
        if not texto_pagina or len(texto_pagina.strip()) < 50:
            print(f"DEBUG: OCR página {pagina_num}: texto vazio ou muito curto")
            return {
                "pagina": pagina_num,
                "texto": "",
                "sucesso": False
            }
        
        print(f"DEBUG: OCR página {pagina_num} SUCESSO ({len(texto_pagina)} caracteres)")
        return {
            "pagina": pagina_num,
            "texto": texto_pagina.strip(),
            "sucesso": True
        }
        
    except Exception as e:
        print(f"ERRO no OCR da página {pagina_num}: {e}")
        return {
            "pagina": pagina_num,
            "texto": "",
            "sucesso": False,
            "erro": str(e)
        }

# 16 - Se extração nativa falhar, usa OCR paralelo por página
async def extrair_texto_ocr(pdf_bytes: bytes) -> str | None:
    """
    Processa OCR de cada página em paralelo e junta os resultados.
    """
    print("DEBUG: Iniciando Tentativa 2: Extração OCR por páginas...")
    
    imagens_individuais = await asyncio.to_thread(pdf_para_imagens_individuais, pdf_bytes)
    
    if not imagens_individuais:
        print("ERRO: OCR falhou na conversão de imagem.")
        return None

    print(f"DEBUG: Convertidas {len(imagens_individuais)} páginas para OCR paralelo...")

    # Processa todas as páginas em paralelo
    tasks = [
        processar_ocr_pagina_individual(img_data, img_data["pagina"])
        for img_data in imagens_individuais
    ]
    
    try:
        resultados_ocr = await asyncio.gather(*tasks, return_exceptions=True)
        
        textos_validos = []
        for resultado in resultados_ocr:
            if isinstance(resultado, Exception):
                print(f"ERRO em página durante OCR: {resultado}")
                continue
            
            if resultado.get("sucesso", False) and resultado.get("texto"):
                textos_validos.append(resultado["texto"])
        
        if not textos_validos:
            print("DEBUG: OCR falhou - nenhuma página com texto válido")
            return None
        
        texto_completo = "\n\n--- NOVA PÁGINA ---\n\n".join(textos_validos)
        print(f"DEBUG: OCR SUCESSO - {len(textos_validos)} páginas processadas ({len(texto_completo)} caracteres total)")
        return texto_completo
        
    except Exception as e:
        print(f"ERRO na coordenação do OCR paralelo: {e}")
        return None

# 17 - Processa página individual
async def processar_pagina_individual(texto_pagina: str, pagina_num: int) -> dict:
    """
    Processa uma página individual de texto e retorna as transações encontradas.
    """
    print(f"DEBUG: Processando página {pagina_num} ({len(texto_pagina)} caracteres)...")
    
    prompt_completo = f"""
{PROMPT_SISTEMA}

Analise esta página {pagina_num} de extrato financeiro e extraia TODAS as transações.

**REGRAS DE CATEGORIZAÇÃO:**
{CATEGORIAS_COMPLETAS}

**TEXTO DA PÁGINA {pagina_num}:**
{texto_pagina}

Retorne apenas um JSON válido com o resultado.
"""

    try:
        response = await asyncio.to_thread(
            gemini_client.models.generate_content,
            model=MODEL_GEMINI,
            contents=prompt_completo
        )
        
        json_text = response.text
        # Remove markdown code blocks se existirem
        json_text = re.sub(r'```json\s*', '', json_text)
        json_text = re.sub(r'```\s*$', '', json_text)
        json_text = json_text.strip()
        
        resultado = json.loads(json_text)
        
        print(f"DEBUG: Página {pagina_num} processada: {len(resultado.get('transactions', []))} transações encontradas.")
        return resultado
        
    except Exception as e:
        print(f"ERRO no processamento da página {pagina_num}: {e}")
        return {
            "success": False,
            "transactions": [],
            "error_message": f"Erro na página {pagina_num}: {str(e)}"
        }

# 18 - Consolida resultados das páginas
def consolidar_resultados_paginas(resultados_paginas: list[dict]) -> dict:
    """
    Consolida os resultados de múltiplas páginas em um resultado final.
    """
    todas_transacoes = []
    bank_name = "TBD"
    document_type = "unknown"
    erros_reais = []
    
    for resultado in resultados_paginas:
        if resultado.get("success", False):
            transacoes = resultado.get("transactions", [])
            todas_transacoes.extend(transacoes)
            
            if bank_name == "TBD" and resultado.get("bank_name"):
                bank_name = resultado["bank_name"]
            if document_type == "unknown" and resultado.get("document_type"):
                document_type = resultado["document_type"]
        else:
            erro = resultado.get("error_message", "Erro desconhecido")
            if "Nenhuma transação encontrada" not in erro:
                erros_reais.append(erro)
    
    transacoes_unicas = []
    transacoes_vistas = set()
    
    for transacao in todas_transacoes:
        chave = (transacao.get('data', ''), 
                transacao.get('descricao', ''), 
                transacao.get('valor', 0))
        if chave not in transacoes_vistas:
            transacoes_vistas.add(chave)
            transacoes_unicas.append(transacao)
    
    error_message = None
    if len(transacoes_unicas) == 0:
        if erros_reais:
            error_message = "; ".join(erros_reais)
        else:
            error_message = "Nenhuma transação encontrada no documento"
    elif erros_reais:
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

# 18 - Decide estratégia baseada no tamanho do texto
async def categorizar_com_llm(texto_bruto: str) -> dict:
    """
    Recebe o texto bruto e processa usando páginas paralelas para melhor performance
    e captura mais completa de transações.
    """
    print("DEBUG: Iniciando Etapa 3: Análise e Categorização (Processamento Paralelo por Páginas)...")
    
    # Verifica se o texto contém múltiplas páginas
    paginas = texto_bruto.split("\n\n--- NOVA PÁGINA ---\n\n")
    
    if len(paginas) <= 1:
        print("DEBUG: Texto pequeno ou página única, processamento direto...")
        
        prompt_completo = f"""
{PROMPT_SISTEMA}

Aqui está o texto bruto extraído de um documento financeiro.
Analise-o, extraia TODAS as transações, categorize-as e retorne o JSON formatado.

**REGRAS DE CATEGORIZAÇÃO:**
{CATEGORIAS_COMPLETAS}

**TEXTO BRUTO PARA ANÁLISE:**
{texto_bruto}

Retorne apenas um JSON válido com o resultado.
"""

        try:
            response = await asyncio.to_thread(
                gemini_client.models.generate_content,
                model=MODEL_GEMINI,
                contents=prompt_completo
            )
            
            json_text = response.text
            # Remove markdown code blocks se existirem
            json_text = re.sub(r'```json\s*', '', json_text)
            json_text = re.sub(r'```\s*$', '', json_text)
            json_text = json_text.strip()
            
            json_output = json.loads(json_text) 
            
            print("DEBUG: Análise direta concluída com SUCESSO.")
            return json_output
            
        except Exception as e:
            print(f"ERRO na análise direta: {e}")
            raise HTTPException(status_code=500, detail=f"Erro na LLM: {e}")
    
    else:
        print(f"DEBUG: Múltiplas páginas detectadas ({len(paginas)}), usando processamento paralelo por página...")
        
        tasks = [
            processar_pagina_individual(pagina.strip(), i + 1) 
            for i, pagina in enumerate(paginas) if pagina.strip()
        ]
        
        resultados_paginas = await asyncio.gather(*tasks, return_exceptions=True)
        
        resultados_validos = []
        for i, resultado in enumerate(resultados_paginas):
            if isinstance(resultado, Exception):
                print(f"ERRO na página {i + 1}: {resultado}")
                resultados_validos.append({
                    "success": False,
                    "transactions": [],
                    "error_message": f"Erro na página {i + 1}: {str(resultado)}"
                })
            else:
                resultados_validos.append(resultado)
        
        resultado_final = consolidar_resultados_paginas(resultados_validos)
        
        print(f"DEBUG: Processamento paralelo por páginas concluído. Total de transações: {resultado_final['transactions_count']}")
        return resultado_final

# 19 - Aplica categorização personalizada
async def categorizar_com_llm_personalizado(texto_bruto: str, user_id: int) -> dict:
    """
    Versão atualizada que aplica categorizações personalizadas após o processamento da LLM.
    """
    print("DEBUG: Iniciando categorização com LLM + categorizações personalizadas...")
    
    task_categorizacoes = asyncio.create_task(buscar_categorizacoes_usuario(user_id))
    task_llm = asyncio.create_task(categorizar_com_llm(texto_bruto))
    
    categorizacoes_usuario, resultado_llm = await asyncio.gather(task_categorizacoes, task_llm)
    
    if resultado_llm.get("success", False) and resultado_llm.get("transactions"):
        transacoes_atualizadas, transacoes_para_inserir = aplicar_categorizacoes_personalizadas(
            resultado_llm["transactions"], 
            categorizacoes_usuario
        )
        
        resultado_llm["transactions"] = transacoes_atualizadas
        resultado_llm["transactions_count"] = len(transacoes_atualizadas)
        
        if transacoes_para_inserir:
            asyncio.create_task(inserir_categorizacoes_usuario(user_id, transacoes_para_inserir))
    
    return resultado_llm

# 20 - Pipeline de processamento síncrono
async def _processar_bytes_sync(pdf_bytes: bytes, user_id: int = None, senha_do_pdf: str | None = None) -> JSONResponse:
    """
    Função interna que executa o pipeline principal e retorna o resultado.
    Usada pelo endpoint de upload de arquivo (síncrono).
    """
    start_time = time.time()
    
    # Tenta desbloquear o PDF se uma senha foi fornecida
    try:
        pdf_bytes = desbloquear_pdf_com_senha(pdf_bytes, senha_do_pdf)
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"success": False, "error_message": e.detail})
    
    texto_bruto = await extrair_texto_nativo(pdf_bytes)
    
    if texto_bruto is None:
        texto_bruto = await extrair_texto_ocr(pdf_bytes)
        
    if texto_bruto is None:
        raise HTTPException(status_code=400, detail="Falha ao extrair texto do PDF (Nativo e OCR).")
        
    try:
        if user_id is not None:
            json_final = await categorizar_com_llm_personalizado(texto_bruto, user_id)
        else:
            json_final = await categorizar_com_llm(texto_bruto)
        
        end_time = time.time()
        print(f"SUCESSO: Processamento concluído em {end_time - start_time:.2f} segundos.")
        
        if "transactions" in json_final and isinstance(json_final["transactions"], list):
            json_final["transactions_count"] = len(json_final["transactions"])
            
        return JSONResponse(content=json_final)
        
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"success": False, "error_message": e.detail})
    except Exception as e:
        print(f"ERRO Inesperado no pipeline: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error_message": f"Erro inesperado: {e}"})

# 21 - Pipeline de processamento assíncrono
async def processar_e_enviar_webhook(file_url: str, webhook_url: str, user_id: int, senha_do_pdf: str | None = None):
    """
    Worker de background: baixa, processa e envia o resultado para o webhook.
    """
    start_time = time.time()
    print(f"INFO [BG]: Iniciando processamento para usuário {user_id}: {file_url}")
    print(f"INFO [BG]: Webhook de destino: {webhook_url}")
    if senha_do_pdf:
        print("INFO [BG]: PDF protegido por senha detectado.")
    json_resultado = {}
    
    try:
        try:
            response = await http_client.get(file_url)
            response.raise_for_status()
            pdf_bytes = await response.aread()
        except httpx.RequestError as e:
            print(f"ERRO [BG]: Falha ao baixar a URL: {e}")
            raise HTTPException(status_code=400, detail=f"Falha ao baixar o PDF da URL: {e}")

        # Tenta desbloquear o PDF se uma senha foi fornecida
        try:
            pdf_bytes = desbloquear_pdf_com_senha(pdf_bytes, senha_do_pdf)
        except HTTPException as e:
            print(f"ERRO [BG]: Falha ao desbloquear PDF: {e.detail}")
            raise e

        texto_bruto = await extrair_texto_nativo(pdf_bytes)
        
        if texto_bruto is None:
            texto_bruto = await extrair_texto_ocr(pdf_bytes)
            
        if texto_bruto is None:
            raise HTTPException(status_code=400, detail="Falha ao extrair texto do PDF (Nativo e OCR).")
        
        json_resultado = await categorizar_com_llm_personalizado(texto_bruto, user_id)
        
        if "transactions" in json_resultado and isinstance(json_resultado["transactions"], list):
            json_resultado["transactions_count"] = len(json_resultado["transactions"])

        print(f"SUCESSO [BG]: Processamento concluído para usuário {user_id}")

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
    
    try:
        print(f"INFO [BG]: Enviando resultado para o webhook: {webhook_url}")
        await http_client.post(webhook_url, json=json_resultado, timeout=10.0)
        
        end_time = time.time()
        tempo_total = end_time - start_time
        
        print(f"INFO [BG]: Webhook enviado com sucesso.")
        print(f"INFO [BG]: ⏱️  TEMPO TOTAL DE PROCESSAMENTO: {tempo_total:.2f} segundos")
        
    except httpx.RequestError as e:
        print(f"ERRO [BG]: Falha ao enviar o POST para o webhook: {e}")

# 22 - Endpoint de upload direto
@app.post("/processar-extrato/")
async def processar_extrato_endpoint(file: UploadFile = File(...), user_id: int = 1, senha_do_pdf: str | None = None):
    """
    Recebe um PDF via upload de arquivo (form-data), 
    executa o pipeline otimizado e retorna o JSON.
    Aceita um parâmetro opcional 'senha_do_pdf' para PDFs protegidos.
    """
    print(f"INFO: Recebido arquivo: {file.filename} para usuário {user_id}")
    if senha_do_pdf:
        print("INFO: Senha do PDF fornecida.")
    pdf_bytes = await file.read()
    return await _processar_bytes_sync(pdf_bytes, user_id, senha_do_pdf)

# 23 - Endpoint de URL assíncrona
@app.post("/processar-extrato-url/")
async def processar_extrato_url_endpoint(payload: URLPayload, background_tasks: BackgroundTasks):
    """
    Recebe um JSON com uma 'file_url', 'webhook_url', 'user_id' e opcionalmente 'senha_do_pdf',
    inicia o processamento em background e retorna as transações
    """
    print(f"INFO: Recebida requisição de URL para usuário {payload.user_id}: {payload.file_url}")
    print(f"INFO: Webhook será enviado para: {payload.webhook_url}")
    if payload.senha_do_pdf:
        print("INFO: Senha do PDF fornecida na requisição.")
    
    background_tasks.add_task(
        processar_e_enviar_webhook, 
        file_url=payload.file_url, 
        webhook_url=payload.webhook_url,
        user_id=payload.user_id,
        senha_do_pdf=payload.senha_do_pdf
    )
    
    return JSONResponse(
        status_code=202,
        content={"status": "processamento_iniciado", "user_id": payload.user_id, "file_url": payload.file_url}
    )

# 23.5 - Endpoint para contagem de tokens
@app.post("/contar-tokens-base64/")
async def contar_tokens_base64_endpoint(payload: TokenCountPayload):
    """
    Recebe um arquivo em base64 e retorna a contagem de tokens.
    
    Resposta de sucesso inclui:
    - total_tokens: número total de tokens no arquivo
    - status: "OK" se <= 100k tokens, "Exceeded" se > 100k tokens
    - file_type: tipo do arquivo processado (text, image, pdf_text)
    - filename: nome do arquivo fornecido
    """
    print("INFO: Iniciando contagem de tokens para arquivo base64")
    if payload.filename:
        print(f"INFO: Nome do arquivo: {payload.filename}")
    
    try:
        resultado = await contar_tokens_base64(payload.file_base64)
        print(f"INFO: Contagem concluída - {resultado['total_tokens']} tokens ({resultado['status']})")
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "total_tokens": resultado["total_tokens"],
                "status": resultado["status"],
                "file_type": resultado["type"],
                "filename": payload.filename
            }
        )
        
    except HTTPException as e:
        print(f"ERRO HTTP na contagem de tokens: {e.detail}")
        return JSONResponse(
            status_code=e.status_code, 
            content={
                "success": False, 
                "error_message": e.detail,
                "filename": payload.filename
            }
        )
    except Exception as e:
        print(f"ERRO inesperado na contagem de tokens: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error_message": f"Erro inesperado: {e}",
                "filename": payload.filename
            }
        )

# 23.6 - Endpoint para contagem de tokens via upload
@app.post("/contar-tokens-upload/")
async def contar_tokens_upload_endpoint(file: UploadFile = File(...)):
    """
    Recebe um arquivo via upload e retorna a contagem de tokens.
    
    Suporta:
    - Arquivos de texto (.txt, .md, .py, etc.)
    - Imagens (.png, .jpg, .jpeg, .gif, .bmp, .webp)
    - PDFs (.pdf)
    
    Resposta de sucesso inclui:
    - total_tokens: número total de tokens no arquivo
    - status: "OK" se <= 100k tokens, "Exceeded" se > 100k tokens
    - file_type: tipo do arquivo processado (text, image, pdf_text)
    - filename: nome do arquivo enviado
    - file_size: tamanho do arquivo em bytes
    """
    print(f"INFO: Iniciando contagem de tokens para arquivo upload: {file.filename}")
    print(f"INFO: Tipo de conteúdo: {file.content_type}")
    
    # Verifica se o arquivo não está vazio
    if file.size == 0:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error_message": "Arquivo vazio enviado",
                "filename": file.filename
            }
        )
    
    try:
        resultado = await contar_tokens_upload_file(file)
        print(f"INFO: Contagem concluída - {resultado['total_tokens']} tokens ({resultado['status']})")
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "total_tokens": resultado["total_tokens"],
                "status": resultado["status"],
                "file_type": resultado["type"],
                "filename": file.filename,
                "file_size": file.size,
                "content_type": file.content_type
            }
        )
        
    except HTTPException as e:
        print(f"ERRO HTTP na contagem de tokens do upload: {e.detail}")
        return JSONResponse(
            status_code=e.status_code, 
            content={
                "success": False, 
                "error_message": e.detail,
                "filename": file.filename
            }
        )
    except Exception as e:
        print(f"ERRO inesperado na contagem de tokens do upload: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error_message": f"Erro inesperado: {e}",
                "filename": file.filename
            }
        )

# 24 - Endpoint de base64
@app.post("/processar-extrato-base64/")
async def processar_extrato_base64_endpoint(payload: Base64Payload):
    """
    Recebe um PDF em base64, executa o pipeline otimizado e retorna o JSON.
    Aceita um parâmetro opcional 'senha_do_pdf' para PDFs protegidos.
    """
    print(f"INFO: Recebido arquivo base64 para usuário {payload.user_id}")
    if payload.filename:
        print(f"INFO: Nome do arquivo: {payload.filename}")
    if payload.senha_do_pdf:
        print("INFO: Senha do PDF fornecida.")
    
    try:
        pdf_bytes = decodificar_base64_para_bytes(payload.file_base64)
        return await _processar_bytes_sync(pdf_bytes, payload.user_id, payload.senha_do_pdf)
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"success": False, "error_message": e.detail})

# 25 - Inicia servidor web
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    host = "0.0.0.0"
    
    print(f"Iniciando servidor FastAPI em {host}:{port}")
    uvicorn.run(app, host=host, port=port)




