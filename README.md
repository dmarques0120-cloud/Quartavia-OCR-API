# Quartavia OCR API

API rápida para processamento de extratos bancários e faturas de cartão de crédito usando OCR e análise automática com IA.

## 🚀 Funcionalidades

- **Extração Inteligente**: Extração nativa de texto + OCR como fallback
- **Processamento Paralelo**: Para documentos extensos, divisão em chunks processados em paralelo
- **Categorização Automática**: Classificação automática de transações em categorias predefinidas
- **API Assíncrona**: Processamento em background com webhook para resultados
- **Filtragem Inteligente**: Remove totalizadores e mantém apenas transações reais com data

## 📋 Requisitos

- Python 3.8+
- OpenAI API Key
- Dependências listadas em `requirements.txt`

## ⚙️ Configuração

1. Clone o repositório:
```bash
git clone https://github.com/dmarques0120-cloud/Quartavia-OCR-API.git
cd Quartavia-OCR-API
```

2. Crie um ambiente virtual:
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# ou
.venv\Scripts\activate     # Windows
```

3. Instale as dependências:
```bash
pip install -r requirements.txt
```

4. Configure as variáveis de ambiente criando um arquivo `.env`:
```env
MODEL_OPENAI="gpt-4o-mini"
OPENAI_API_KEY="sua_chave_openai_aqui"
```

## 🏃‍♂️ Como Usar

1. Inicie o servidor:
```bash
python api_rapida.py
```

2. Acesse a documentação da API:
```
http://127.0.0.1:8000/docs
```

## 📡 Endpoints

### POST `/processar-extrato/`
Upload direto de arquivo PDF (resposta síncrona)

### POST `/processar-extrato-url/`
Processamento via URL com webhook (resposta assíncrona)

```json
{
  "file_url": "https://exemplo.com/extrato.pdf",
  "webhook_url": "https://seu-webhook.com/receiver"
}
```

## 📊 Resposta

```json
{
  "success": true,
  "bank_name": "Bradesco",
  "document_type": "credit-card-statement",
  "transactions_count": 15,
  "transactions": [
    {
      "uuid": "1",
      "data": "2023-08-08",
      "descricao": "Spotify",
      "valor": 11.90,
      "categoria": "COMUNICACAO",
      "tipo": "despesa",
      "subcategoria": "Apps",
      "parcelado": false
    }
  ],
  "error_message": null
}
```

## 🏗️ Arquitetura

- **api_rapida.py**: Servidor FastAPI principal
- **prompt_e_schema.py**: Prompts e regras de categorização
- **client_webhook.py**: Cliente de teste para webhooks

## 📈 Performance

- **Documentos pequenos**: ~3-5 segundos
- **Documentos extensos**: ~8-15 segundos (processamento paralelo)
- **Precisão**: >95% na identificação de transações reais

## 🛠️ Tecnologias

- **FastAPI**: Framework web assíncrono
- **OpenAI GPT-4**: Análise e categorização de transações
- **PyMuPDF**: Processamento de PDFs
- **pdfplumber**: Extração de texto nativa
- **httpx**: Cliente HTTP assíncrono

## 📝 Licença

MIT License
