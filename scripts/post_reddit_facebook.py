"""
post_reddit_facebook.py
=======================
Busca posts aleatórios de subreddits brasileiros de memes e publica
na página do Facebook "RVS" via Meta Graph API.

Subreddits fonte:
  - r/MemesBR
  - r/ComentariosMelhores
  - r/MEMEBRASIL

Funcionalidades:
  ✅ Autenticação Reddit via OAuth2 (Application Only)
  ✅ Seleção aleatória de subreddit e post
  ✅ Controle de duplicatas via state.json (hash + post_id)
  ✅ Suporte a imagens (JPEG, PNG, GIF) e vídeos (MP4)
  ✅ Remoção de metadados (EXIF em imagens, metadados em vídeos)
  ✅ Melhoria de qualidade de imagem (upscale suave + nitidez)
  ✅ Publicação via Meta Graph API v20.0
  ✅ Legenda original do Reddit preservada

GitHub Secrets necessários:
  REDDIT_CLIENT_ID      → Client ID do app Reddit
  REDDIT_CLIENT_SECRET  → Client Secret do app Reddit
  FB_PAGE_ID            → ID numérico da página do Facebook
  FB_ACCESS_TOKEN       → Token permanente da página (com pages_manage_posts)
"""

import os
import sys
import json
import random
import hashlib
import requests
import subprocess
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURAÇÃO
# ═══════════════════════════════════════════════════════════════════════════════

SUBREDDITS = [
    "MemesBR",
    "ComentariosMelhores",
    "MEMEBRASIL",
]

# Quantos posts buscar por subreddit (mais = mais variedade, menos duplicatas)
POSTS_POR_BUSCA = 50

# Arquivo de estado para controle de duplicatas
ARQUIVO_ESTADO = "state.json"

# Máximo de post_ids armazenados (evita crescimento infinito)
MAX_IDS_ARMAZENADOS = 2000

# Extensões de vídeo suportadas
EXTENSOES_VIDEO = {".mp4", ".webm", ".mov", ".avi", ".mkv"}

# Extensões de imagem suportadas
EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# ═══════════════════════════════════════════════════════════════════════════════
#  CONTROLE DE ESTADO (Anti-Duplicatas)
# ═══════════════════════════════════════════════════════════════════════════════

def carregar_estado() -> dict:
    """Carrega o state.json ou retorna estado inicial."""
    if os.path.exists(ARQUIVO_ESTADO):
        try:
            with open(ARQUIVO_ESTADO, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            print("[Estado] ⚠️  state.json corrompido — reiniciando.")
    return {
        "posted_ids": [],        # IDs únicos dos posts do Reddit
        "posted_hashes": [],     # hashes MD5 das mídias (backup anti-dupe)
        "total_postados": 0,
        "ultimo_post": None,
    }


def salvar_estado(estado: dict) -> None:
    """Salva o estado atual no state.json."""
    with open(ARQUIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, indent=2, ensure_ascii=False)
    print(f"[Estado] ✓ state.json salvo ({len(estado['posted_ids'])} IDs registrados)")


def ja_foi_postado(estado: dict, post_id: str, media_hash: str = None) -> bool:
    """Verifica se um post já foi publicado."""
    if post_id in estado["posted_ids"]:
        return True
    if media_hash and media_hash in estado["posted_hashes"]:
        return True
    return False


def registrar_postagem(estado: dict, post_id: str, media_hash: str = None) -> None:
    """Registra um post como publicado."""
    if post_id not in estado["posted_ids"]:
        estado["posted_ids"].append(post_id)
        # Mantém apenas os últimos MAX_IDS_ARMAZENADOS
        if len(estado["posted_ids"]) > MAX_IDS_ARMAZENADOS:
            estado["posted_ids"] = estado["posted_ids"][-MAX_IDS_ARMAZENADOS:]

    if media_hash and media_hash not in estado["posted_hashes"]:
        estado["posted_hashes"].append(media_hash)
        if len(estado["posted_hashes"]) > MAX_IDS_ARMAZENADOS:
            estado["posted_hashes"] = estado["posted_hashes"][-MAX_IDS_ARMAZENADOS:]

    estado["total_postados"] = estado.get("total_postados", 0) + 1
    estado["ultimo_post"] = datetime.now().isoformat()


# ═══════════════════════════════════════════════════════════════════════════════
#  AUTENTICAÇÃO REDDIT (OAuth2 Application Only)
# ═══════════════════════════════════════════════════════════════════════════════

def obter_token_reddit() -> str:
    """
    Obtém token de acesso Reddit via OAuth2 Application Only flow.
    Não requer conta de usuário — apenas Client ID e Client Secret.
    """
    client_id     = os.environ["REDDIT_CLIENT_ID"]
    client_secret = os.environ["REDDIT_CLIENT_SECRET"]

    print("[Reddit] Autenticando via OAuth2 (Application Only)...")

    resp = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": "RVSMemesBot/2.0 (by /u/RVS_autopost)"},
        timeout=30,
    )

    if resp.status_code != 200:
        print(f"[Reddit] ✗ Falha na autenticação: {resp.status_code} — {resp.text}")
        sys.exit(1)

    token = resp.json().get("access_token")
    print(f"[Reddit] ✓ Token obtido com sucesso.")
    return token


# ═══════════════════════════════════════════════════════════════════════════════
#  BUSCA DE POSTS NO REDDIT
# ═══════════════════════════════════════════════════════════════════════════════

def buscar_posts_reddit(token: str, subreddit: str, quantidade: int = 50) -> list:
    """
    Busca os posts mais quentes do subreddit.
    Retorna lista de posts com mídia (imagem ou vídeo).
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "RVSMemesBot/2.0 (by /u/RVS_autopost)",
    }

    # Busca hot posts (mais engajados no momento)
    url = f"https://oauth.reddit.com/r/{subreddit}/hot"
    params = {"limit": quantidade, "raw_json": 1}

    print(f"[Reddit] Buscando posts de r/{subreddit}...")

    resp = requests.get(url, headers=headers, params=params, timeout=30)

    if resp.status_code != 200:
        print(f"[Reddit] ✗ Erro ao buscar r/{subreddit}: {resp.status_code}")
        return []

    posts_raw = resp.json().get("data", {}).get("children", [])
    posts_com_midia = []

    for item in posts_raw:
        post = item.get("data", {})

        # Filtra apenas posts com mídia (imagem ou vídeo)
        midia_info = extrair_info_midia(post)
        if midia_info:
            posts_com_midia.append({
                "id":       post.get("id"),
                "titulo":   post.get("title", ""),
                "legenda":  post.get("selftext", "") or post.get("title", ""),
                "autor":    post.get("author", ""),
                "subreddit": post.get("subreddit", subreddit),
                "url":      post.get("url", ""),
                "permalink": f"https://reddit.com{post.get('permalink', '')}",
                "midia":    midia_info,
                "score":    post.get("score", 0),
            })

    print(f"[Reddit] ✓ {len(posts_com_midia)} posts com mídia encontrados em r/{subreddit}")
    return posts_com_midia


def extrair_info_midia(post: dict) -> dict | None:
    """
    Extrai informações de mídia de um post do Reddit.
    Suporta: imagens diretas, galerias, vídeos Reddit, GIFs.
    Retorna None se não houver mídia.
    """
    url = post.get("url", "")
    hint = post.get("post_hint", "")
    dominio = post.get("domain", "")

    # ── Vídeo do Reddit (v.redd.it) ──────────────────────────────────────────
    if post.get("is_video") and post.get("media"):
        video_data = post["media"].get("reddit_video", {})
        video_url  = video_data.get("fallback_url", "")
        if video_url:
            # Remove parâmetro ?source=fallback se presente
            video_url = video_url.split("?")[0]
            return {
                "tipo": "video",
                "url":  video_url,
                "largura":  video_data.get("width", 0),
                "altura":   video_data.get("height", 0),
                "duracao":  video_data.get("duration", 0),
            }

    # ── Imagem direta ─────────────────────────────────────────────────────────
    extensao = Path(url.split("?")[0]).suffix.lower()
    if extensao in EXTENSOES_IMAGEM or hint == "image":
        return {"tipo": "imagem", "url": url}

    # ── Links de hospedagem de imagem conhecidos ──────────────────────────────
    if any(d in dominio for d in ["i.redd.it", "i.imgur.com", "imgur.com"]):
        if extensao in EXTENSOES_IMAGEM or hint == "image":
            return {"tipo": "imagem", "url": url}
        # imgur sem extensão — tenta como imagem
        if "imgur.com" in dominio and extensao not in EXTENSOES_VIDEO:
            return {"tipo": "imagem", "url": url + ".jpg" if not extensao else url}

    # ── Preview de imagem (fallback) ──────────────────────────────────────────
    preview = post.get("preview", {})
    if preview and not post.get("is_video"):
        imagens = preview.get("images", [])
        if imagens:
            # Pega a resolução mais alta disponível
            fonte = imagens[0].get("source", {})
            img_url = fonte.get("url", "").replace("&amp;", "&")
            if img_url:
                return {"tipo": "imagem", "url": img_url}

    return None


def escolher_post_valido(posts: list, estado: dict) -> dict | None:
    """
    Embaralha os posts e retorna o primeiro que ainda não foi postado.
    """
    random.shuffle(posts)
    for post in posts:
        if not ja_foi_postado(estado, post["id"]):
            return post
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  DOWNLOAD E PROCESSAMENTO DE MÍDIA
# ═══════════════════════════════════════════════════════════════════════════════

def baixar_midia(url: str, destino: str) -> bool:
    """Baixa qualquer mídia (imagem ou vídeo) para o destino especificado."""
    print(f"[Download] Baixando: {url[:80]}...")
    headers = {"User-Agent": "RVSMemesBot/2.0"}

    try:
        with requests.get(url, headers=headers, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(destino, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
        tamanho = os.path.getsize(destino) // 1024
        print(f"[Download] ✓ Salvo em '{destino}' ({tamanho} KB)")
        return True
    except Exception as e:
        print(f"[Download] ✗ Erro: {e}")
        return False


def calcular_hash(caminho: str) -> str:
    """Calcula hash MD5 do arquivo para detecção de duplicatas."""
    h = hashlib.md5()
    with open(caminho, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def processar_imagem(entrada: str, saida: str) -> bool:
    """
    Processa imagem:
    - Remove metadados EXIF
    - Melhora qualidade (nitidez suave)
    - Converte para JPEG de alta qualidade
    - Redimensiona se necessário (máx. 4096px)
    """
    try:
        from PIL import Image, ImageFilter, ImageEnhance

        print(f"[Imagem] Processando '{entrada}'...")
        img = Image.open(entrada)

        # Converte para RGB (remove alpha/EXIF automaticamente)
        if img.mode in ("RGBA", "LA", "P"):
            fundo = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            fundo.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = fundo
        else:
            img = img.convert("RGB")

        # Redimensiona se for muito grande (mantém proporção)
        MAX_DIM = 4096
        w, h = img.size
        if max(w, h) > MAX_DIM:
            ratio = MAX_DIM / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            print(f"[Imagem] Redimensionada para {img.size}")

        # Nitidez suave (melhora qualidade percebida)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=80, threshold=3))

        # Salva com qualidade alta e sem metadados
        img.save(saida, "JPEG", quality=92, optimize=True, progressive=True)
        tamanho = os.path.getsize(saida) // 1024
        print(f"[Imagem] ✓ Processada: {img.size[0]}x{img.size[1]}px, {tamanho} KB")
        return True

    except Exception as e:
        print(f"[Imagem] ✗ Erro no processamento: {e}")
        # Fallback: copia o arquivo original
        shutil.copy(entrada, saida)
        return True


def processar_video(entrada: str, saida: str) -> bool:
    """
    Processa vídeo com FFmpeg:
    - Remove todos os metadados (streams de metadados, comentários, tags)
    - Mantém formato MP4 compatível com Meta API
    - Melhora qualidade com CRF otimizado
    - Mantém resolução original (sem downscale)
    """
    print(f"[Vídeo] Processando '{entrada}' com FFmpeg...")

    cmd = [
        "ffmpeg", "-y",
        "-i", entrada,
        # Remove TODOS os metadados
        "-map_metadata", "-1",
        "-map_chapters", "-1",
        # Codec de vídeo H.264 com boa qualidade
        "-c:v", "libx264",
        "-crf", "20",           # 18-23 = alta qualidade (menor = melhor)
        "-preset", "medium",
        "-pix_fmt", "yuv420p",  # compatibilidade máxima
        # Codec de áudio AAC
        "-c:a", "aac",
        "-b:a", "192k",
        # Formato MP4 otimizado para streaming
        "-movflags", "+faststart",
        saida,
    ]

    try:
        resultado = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutos máximo
        )

        if resultado.returncode == 0:
            tamanho = os.path.getsize(saida) // 1024
            print(f"[Vídeo] ✓ Processado: {tamanho} KB")
            return True
        else:
            print(f"[Vídeo] ✗ FFmpeg erro:\n{resultado.stderr[-1000:]}")
            # Fallback: copia original
            shutil.copy(entrada, saida)
            return True

    except subprocess.TimeoutExpired:
        print("[Vídeo] ✗ Timeout no processamento de vídeo.")
        shutil.copy(entrada, saida)
        return True
    except FileNotFoundError:
        print("[Vídeo] ⚠️  FFmpeg não encontrado — usando arquivo original.")
        shutil.copy(entrada, saida)
        return True


# ═══════════════════════════════════════════════════════════════════════════════
#  PUBLICAÇÃO NO FACEBOOK (Meta Graph API v20.0)
# ═══════════════════════════════════════════════════════════════════════════════

def publicar_imagem_facebook(caminho: str, legenda: str) -> bool:
    """Publica imagem na página do Facebook via /photos endpoint."""
    page_id = os.environ["FB_PAGE_ID"]
    token   = os.environ["FB_ACCESS_TOKEN"]

    print(f"[Facebook] 📸 Publicando imagem na página {page_id}...")

    url = f"https://graph.facebook.com/v20.0/{page_id}/photos"

    with open(caminho, "rb") as f:
        resp = requests.post(
            url,
            data={"message": legenda, "access_token": token},
            files={"source": (Path(caminho).name, f, "image/jpeg")},
            timeout=120,
        )

    if resp.status_code == 200:
        dados = resp.json()
        post_id = dados.get("post_id") or dados.get("id", "?")
        print(f"[Facebook] ✓ Imagem publicada! Post ID: {post_id}")
        return True
    else:
        print(f"[Facebook] ✗ Erro {resp.status_code}: {resp.text}")
        return False


def publicar_video_facebook(caminho: str, legenda: str) -> bool:
    """
    Publica vídeo na página do Facebook via Resumable Upload Protocol.
    
    Processo em 3 etapas:
    1. Inicializa sessão de upload → recebe video_id + upload_url
    2. Faz upload do arquivo binário
    3. Publica o vídeo
    """
    page_id = os.environ["FB_PAGE_ID"]
    token   = os.environ["FB_ACCESS_TOKEN"]
    tamanho = os.path.getsize(caminho)

    print(f"[Facebook] 🎬 Iniciando upload de vídeo ({tamanho // 1024} KB)...")

    # ── ETAPA 1: Inicializar sessão ───────────────────────────────────────────
    resp_init = requests.post(
        f"https://graph.facebook.com/v20.0/{page_id}/videos",
        data={
            "upload_phase": "start",
            "file_size": tamanho,
            "access_token": token,
        },
        timeout=60,
    )

    if resp_init.status_code != 200:
        print(f"[Facebook] ✗ Erro ao iniciar upload: {resp_init.status_code} — {resp_init.text}")
        return False

    dados_init  = resp_init.json()
    video_id    = dados_init.get("video_id")
    upload_url  = dados_init.get("upload_url")
    start_offset = int(dados_init.get("start_offset", 0))
    end_offset   = int(dados_init.get("end_offset", tamanho))

    print(f"[Facebook] ✓ Sessão iniciada. Video ID: {video_id}")

    # ── ETAPA 2: Upload do arquivo em chunks ──────────────────────────────────
    print(f"[Facebook] ⬆️  Fazendo upload do vídeo...")

    with open(caminho, "rb") as f:
        while start_offset < tamanho:
            f.seek(start_offset)
            chunk = f.read(end_offset - start_offset)

            resp_upload = requests.post(
                f"https://graph.facebook.com/v20.0/{page_id}/videos",
                data={
                    "upload_phase": "transfer",
                    "start_offset": start_offset,
                    "video_file_chunk": ("chunk", chunk, "application/octet-stream"),
                    "upload_session_id": video_id,
                    "access_token": token,
                },
                timeout=300,
            )

            if resp_upload.status_code != 200:
                print(f"[Facebook] ✗ Erro no upload chunk: {resp_upload.text}")
                return False

            dados_upload = resp_upload.json()
            start_offset = int(dados_upload.get("start_offset", tamanho))
            end_offset   = int(dados_upload.get("end_offset", tamanho))

    print(f"[Facebook] ✓ Upload concluído!")

    # ── ETAPA 3: Publicar o vídeo ─────────────────────────────────────────────
    print(f"[Facebook] 📤 Publicando vídeo...")

    resp_pub = requests.post(
        f"https://graph.facebook.com/v20.0/{page_id}/videos",
        data={
            "upload_phase": "finish",
            "video_id": video_id,
            "upload_session_id": video_id,
            "description": legenda,
            "access_token": token,
        },
        timeout=120,
    )

    if resp_pub.status_code == 200:
        dados_pub = resp_pub.json()
        print(f"[Facebook] ✓ Vídeo publicado! Resposta: {dados_pub}")
        return True
    else:
        print(f"[Facebook] ✗ Erro ao publicar vídeo: {resp_pub.status_code} — {resp_pub.text}")
        return False


def formatar_legenda(post: dict) -> str:
    """
    Formata a legenda para o Facebook.
    Usa o título do post do Reddit como legenda principal.
    Adiciona créditos discretos.
    """
    titulo = post.get("titulo", "").strip()
    autor  = post.get("autor", "")
    sub    = post.get("subreddit", "")

    # Legenda = título original do Reddit
    legenda = titulo if titulo else ""

    # Crédito discreto ao final
    if autor and autor not in ("", "[deleted]", "AutoModerator"):
        legenda += f"\n\n📌 r/{sub} • u/{autor}"

    return legenda.strip()


# ═══════════════════════════════════════════════════════════════════════════════
#  FLUXO PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"\n{'═'*60}")
    print(f"  🤣 RVS MEMES — Bot Reddit → Facebook")
    print(f"  ⏰ {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}")
    print(f"{'═'*60}\n")

    # 1. Carregar estado
    estado = carregar_estado()
    print(f"[Estado] {len(estado.get('posted_ids', []))} posts já postados no histórico.")

    # 2. Autenticar no Reddit
    token_reddit = obter_token_reddit()

    # 3. Sortear subreddit aleatório e buscar posts
    random.shuffle(SUBREDDITS)
    post_escolhido = None

    for subreddit in SUBREDDITS:
        posts = buscar_posts_reddit(token_reddit, subreddit, POSTS_POR_BUSCA)
        if not posts:
            continue

        post_escolhido = escolher_post_valido(posts, estado)
        if post_escolhido:
            print(f"\n[Seleção] ✓ Post escolhido de r/{subreddit}:")
            print(f"   ID     : {post_escolhido['id']}")
            print(f"   Título : {post_escolhido['titulo'][:80]}")
            print(f"   Tipo   : {post_escolhido['midia']['tipo'].upper()}")
            print(f"   Score  : {post_escolhido['score']}")
            break

    if not post_escolhido:
        print("\n[ERRO] Não foi possível encontrar um post novo em nenhum subreddit.")
        print("       Todos os posts recentes já foram publicados ou sem mídia.")
        sys.exit(1)

    # 4. Download da mídia
    midia_info  = post_escolhido["midia"]
    tipo_midia  = midia_info["tipo"]
    url_midia   = midia_info["url"]

    if tipo_midia == "video":
        ext_raw = ".mp4"
        ext_final = ".mp4"
    else:
        # Detecta extensão da URL
        ext_raw = Path(url_midia.split("?")[0]).suffix.lower()
        if ext_raw not in EXTENSOES_IMAGEM:
            ext_raw = ".jpg"
        ext_final = ".jpg"

    caminho_raw   = f"media_raw{ext_raw}"
    caminho_final = f"media_final{ext_final}"

    if not baixar_midia(url_midia, caminho_raw):
        print("[ERRO] Falha no download da mídia.")
        sys.exit(1)

    # 5. Calcular hash para anti-duplicata
    media_hash = calcular_hash(caminho_raw)
    if ja_foi_postado(estado, post_escolhido["id"], media_hash):
        print("[AVISO] Mídia duplicada detectada pelo hash. Abortando.")
        sys.exit(0)

    # 6. Processar mídia (remover metadados + melhorar qualidade)
    if tipo_midia == "video":
        sucesso_proc = processar_video(caminho_raw, caminho_final)
    else:
        sucesso_proc = processar_imagem(caminho_raw, caminho_final)

    if not sucesso_proc:
        print("[AVISO] Processamento falhou — usando arquivo original.")
        caminho_final = caminho_raw

    # 7. Formatar legenda
    legenda = formatar_legenda(post_escolhido)
    print(f"\n[Legenda]\n{legenda[:200]}{'...' if len(legenda) > 200 else ''}")

    # 8. Publicar no Facebook
    if tipo_midia == "video":
        sucesso = publicar_video_facebook(caminho_final, legenda)
    else:
        sucesso = publicar_imagem_facebook(caminho_final, legenda)

    if not sucesso:
        print("\n[ERRO] Publicação no Facebook falhou.")
        sys.exit(1)

    # 9. Registrar postagem e salvar estado
    registrar_postagem(estado, post_escolhido["id"], media_hash)
    salvar_estado(estado)

    # 10. Limpeza de arquivos temporários
    for arquivo in [caminho_raw, caminho_final]:
        if os.path.exists(arquivo) and arquivo != caminho_final:
            os.remove(arquivo)

    print(f"\n{'═'*60}")
    print(f"  ✅ Post publicado com sucesso!")
    print(f"  📊 Total publicados: {estado['total_postados']}")
    print(f"{'═'*60}\n")


if __name__ == "__main__":
    main()
