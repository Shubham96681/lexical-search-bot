# Ranger knowledge-base chatbot

A local chatbot over public Apache Ranger policies and documentation. Retrieval mixes lexical BM25 search with OpenAI embeddings stored in an in-memory vector index. Passages are fused with reciprocal rank fusion, then sent to a chat model.

The OpenAI key is optional at startup. Lexical search works immediately. Paste a key in the sidebar, or set `OPENAI_API_KEY` in `.env`, to build embeddings and generate answers. The key stays in the server process and is not written back to disk.

## Run

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\python run.py
```

Open http://127.0.0.1:8000.

Put your key in `.env` before starting, or paste it into the page and choose **Save key and embed**. Chat and embedding model names can be changed with `OPENAI_CHAT_MODEL` and `OPENAI_EMBEDDING_MODEL`.

## Your documents

Use **Your documents** in the sidebar to upload text, Markdown, CSV, JSON, HTML, PDF, or Word files, up to 10 MB each. They are indexed with the Ranger corpus. Lexical search includes them immediately. If an OpenAI key is already saved, their embeddings are rebuilt too. Uploaded files stay in `data/uploads` and are not committed.

## Corpus

Sample policies are Apache Ranger test fixtures (HDFS, Hive, HBase, Knox, Kafka, KMS, plus Hive policy-engine and tag-policy cases). The other documents are the project README, FAQ, policy model, dynamic expressions, attribute-based access control, application integration notes, and the quick start guide. Files are cached in `data/raw`. Missing files are downloaded on startup from the Apache Ranger repository and ranger.apache.org.
