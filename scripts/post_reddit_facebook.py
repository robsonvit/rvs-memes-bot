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
  ✅ Busca via API Pública (meme-api.com) — NÃO precisa de App no Reddit!
  ✅ Seleção aleatória de subreddit e post
  ✅ Controle de duplicatas via state.json (hash + post_id)
  ✅ Suporte a imagens (JPEG, PNG, GIF) e vídeos (MP4)
  ✅ Remoção de metadados (EXIF em imagens, metadados em vídeos)
  ✅ Melhoria de qualidade de imagem (upscale suave + nitidez)
  ✅ Publicação via Meta Graph API v20.0
  ✅ Legenda original preservada

GitHub Secrets necessários:
  FB_PAGE_ID            → ID numérico da página do Facebook
  FB_ACCESS_TOKEN       → Token permanente da página (com pages_manage_posts)
"""

import os
import sys
import time
import json
import random
import hashlib
import requests
import subprocess
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

# Quantos posts buscar por subreddit
POSTS_POR_BUSCA = 30

# Arquivo de estado para controle de duplicatas
ARQUIVO_ESTADO = "state.json"

# Máximo de post_ids armazenados
MAX_IDS_ARMAZENADOS = 2000

# Extensões de vídeo e imagem suportadas
EXTENSOES_VIDEO = {".mp4", ".webm", ".mov", ".avi", ".mkv"}
EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# ═══════════════════════════════════════════════════════════════════════════════
#  CONTROLE DE ESTADO (Anti-Duplicatas)
# ═══════════════════════════════════════════════════════════════════════════════

def carregar_estado() -> dict:
    if os.path.exists(ARQUIVO_ESTADO):
        try:
            with open(ARQUIVO_ESTADO, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            print("[Estado] ⚠️  state.json corrompido — reiniciando.")
    return {
        "posted_ids": [],
        "posted_hashes": [],
        "total_postados": 0,
        "ultimo_post": None,
    }

def salvar_estado(estado: dict) -> None:
    with open(ARQUIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, indent=2, ensure_ascii=False)
    print(f"[Estado] ✓ state.json salvo ({len(estado['posted_ids'])} IDs registrados)")

def ja_foi_postado(estado: dict, post_id: str, media_hash: str = None) -> bool:
    if post_id in estado["posted_ids"]:
        return True
    if media_hash and media_hash in estado["posted_hashes"]:
        return True
    return False

def registrar_postagem(estado: dict, post_id: str, media_hash: str = None) -> None:
    if post_id not in estado["posted_ids"]:
        estado["posted_ids"].append(post_id)
        if len(estado["posted_ids"]) > MAX_IDS_ARMAZENADOS:
            estado["posted_ids"] = estado["posted_ids"][-MAX_IDS_ARMAZENADOS:]

    if media_hash and media_hash not in estado["posted_hashes"]:
        estado["posted_hashes"].append(media_hash)
        if len(estado["posted_hashes"]) > MAX_IDS_ARMAZENADOS:
            estado["posted_hashes"] = estado["posted_hashes"][-MAX_IDS_ARMAZENADOS:]

    estado["total_postados"] = estado.get("total_postados", 0) + 1
    estado["ultimo_post"] = datetime.now().isoformat()

# ═══════════════════════════════════════════════════════════════════════════════
#  BUSCA DE POSTS VIA MEME-API
# ═══════════════════════════════════════════════════════════════════════════════

def buscar_posts(subreddit: str, quantidade: int = 30) -> list:
    """
    Busca memes usando a API pública gratuita (não requer App do Reddit).
    """
    print(f"[Meme-API] Buscando posts de r/{subreddit}...")
    url = f"https://meme-api.com/gimme/{subreddit}/{quantidade}"
    
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[Meme-API] ✗ Erro ao buscar r/{subreddit}: {e}")
        return []

    memes = resp.json().get("memes", [])
    posts_com_midia = []

    for meme in memes:
        # Pega a URL do preview com melhor resolução se disponível, senão a URL direta
        url_midia = meme.get("url")
        previews = meme.get("preview", [])
        if previews:
            url_midia = previews[-1] # último geralmente é a maior resolução
            
        extensao = Path(url_midia.split("?")[0]).suffix.lower()
        tipo = "video" if extensao in EXTENSOES_VIDEO else "imagem"

        # Extrai ID do permalink
        post_id = meme.get("postLink", "").rstrip("/").split("/")[-1]
        if not post_id:
            post_id = url_midia.split("/")[-1]

        posts_com_midia.append({
            "id": post_id,
            "titulo": meme.get("title", ""),
            "autor": meme.get("author", ""),
            "subreddit": meme.get("subreddit", subreddit),
            "midia": {"tipo": tipo, "url": url_midia},
            "score": meme.get("ups", 0),
        })

    print(f"[Meme-API] ✓ {len(posts_com_midia)} posts processados de r/{subreddit}")
    return posts_com_midia

def escolher_post_valido(posts: list, estado: dict) -> dict | None:
    # Ordena por score para pegar os melhores memes
    posts_ordenados = sorted(posts, key=lambda x: x["score"], reverse=True)
    for post in posts_ordenados:
        if not ja_foi_postado(estado, post["id"]):
            return post
    return None

# ═══════════════════════════════════════════════════════════════════════════════
#  DOWNLOAD E PROCESSAMENTO DE MÍDIA
# ═══════════════════════════════════════════════════════════════════════════════

def baixar_midia(url: str, destino: str) -> bool:
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
    h = hashlib.md5()
    with open(caminho, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def processar_imagem(entrada: str, saida: str) -> bool:
    try:
        from PIL import Image, ImageFilter
        print(f"[Imagem] Processando '{entrada}'...")
        img = Image.open(entrada)

        if img.mode in ("RGBA", "LA", "P"):
            fundo = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            fundo.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = fundo
        else:
            img = img.convert("RGB")

        MAX_DIM = 4096
        w, h = img.size
        if max(w, h) > MAX_DIM:
            ratio = MAX_DIM / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=80, threshold=3))
        img.save(saida, "JPEG", quality=92, optimize=True, progressive=True)
        tamanho = os.path.getsize(saida) // 1024
        print(f"[Imagem] ✓ Processada: {img.size[0]}x{img.size[1]}px, {tamanho} KB")
        return True
    except Exception as e:
        print(f"[Imagem] ✗ Erro no processamento: {e}")
        shutil.copy(entrada, saida)
        return True

def processar_video(entrada: str, saida: str) -> bool:
    print(f"[Vídeo] Processando '{entrada}' com FFmpeg...")
    cmd = [
        "ffmpeg", "-y", "-i", entrada,
        "-map_metadata", "-1", "-map_chapters", "-1",
        "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", saida,
    ]
    try:
        resultado = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if resultado.returncode == 0:
            tamanho = os.path.getsize(saida) // 1024
            print(f"[Vídeo] ✓ Processado: {tamanho} KB")
            return True
        else:
            print(f"[Vídeo] ✗ FFmpeg erro:\n{resultado.stderr[-1000:]}")
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
#  PUBLICAÇÃO (FACEBOOK E INSTAGRAM)
# ═══════════════════════════════════════════════════════════════════════════════

def publicar_imagem_facebook(caminho: str, legenda: str) -> bool:
    page_id = os.environ["FB_PAGE_ID"]
    token   = os.environ["FB_ACCESS_TOKEN"]
    print(f"[Facebook] 📸 Publicando imagem na página {page_id}...")
    url = f"https://graph.facebook.com/v20.0/{page_id}/photos"
    
    with open(caminho, "rb") as f:
        resp = requests.post(url, data={"message": legenda, "access_token": token}, files={"source": (Path(caminho).name, f, "image/jpeg")}, timeout=120)

    if resp.status_code == 200:
        print(f"[Facebook] ✓ Imagem publicada! Post ID: {resp.json().get('id')}")
        return True
    print(f"[Facebook] ✗ Erro {resp.status_code}: {resp.text}")
    return False

def publicar_video_facebook(caminho: str, legenda: str) -> bool:
    page_id = os.environ["FB_PAGE_ID"]
    token   = os.environ["FB_ACCESS_TOKEN"]
    tamanho = os.path.getsize(caminho)
    print(f"[Facebook] 🎬 Iniciando upload de vídeo ({tamanho // 1024} KB)...")

    resp_init = requests.post(f"https://graph.facebook.com/v20.0/{page_id}/videos", data={"upload_phase": "start", "file_size": tamanho, "access_token": token}, timeout=60)
    if resp_init.status_code != 200:
        print(f"[Facebook] ✗ Erro ao iniciar upload: {resp_init.text}")
        return False

    dados_init = resp_init.json()
    video_id = dados_init.get("video_id")
    start_offset, end_offset = int(dados_init.get("start_offset", 0)), int(dados_init.get("end_offset", tamanho))

    print(f"[Facebook] ⬆️  Fazendo upload do vídeo...")
    with open(caminho, "rb") as f:
        while start_offset < tamanho:
            f.seek(start_offset)
            chunk = f.read(end_offset - start_offset)
            resp_upload = requests.post(f"https://graph.facebook.com/v20.0/{page_id}/videos", data={"upload_phase": "transfer", "start_offset": start_offset, "upload_session_id": video_id, "access_token": token}, files={"video_file_chunk": ("chunk", chunk, "application/octet-stream")}, timeout=300)
            if resp_upload.status_code != 200:
                print(f"[Facebook] ✗ Erro no upload chunk: {resp_upload.text}")
                return False
            dados_upload = resp_upload.json()
            start_offset, end_offset = int(dados_upload.get("start_offset", tamanho)), int(dados_upload.get("end_offset", tamanho))

    print(f"[Facebook] 📤 Publicando vídeo...")
    resp_pub = requests.post(f"https://graph.facebook.com/v20.0/{page_id}/videos", data={"upload_phase": "finish", "video_id": video_id, "upload_session_id": video_id, "description": legenda, "access_token": token}, timeout=120)
    
    if resp_pub.status_code == 200:
        print(f"[Facebook] ✓ Vídeo publicado! Resposta: {resp_pub.json()}")
        return True
    print(f"[Facebook] ✗ Erro ao publicar vídeo: {resp_pub.text}")
    return False

def formatar_legenda(post: dict) -> str:
    titulo = post.get("titulo", "").strip()
    hashtags = "\n\n#memes #meme #memesbrasil #humor #zueira #risos #comedia #memesengracados #piada #tudum"
    return (titulo + hashtags).strip()

def obter_instagram_id() -> str | None:
    page_id = os.environ.get("FB_PAGE_ID")
    token = os.environ.get("FB_ACCESS_TOKEN")
    if not page_id or not token:
        return None
    
    url = f"https://graph.facebook.com/v20.0/{page_id}?fields=instagram_business_account&access_token={token}"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if "instagram_business_account" in data:
                return data["instagram_business_account"]["id"]
    except Exception as e:
        print(f"[Facebook] ✗ Erro ao obter Instagram ID: {e}")
    return None

def publicar_instagram(ig_user_id: str, url_midia: str, tipo_midia: str, legenda: str) -> bool:
    token = os.environ.get("FB_ACCESS_TOKEN")
    print(f"[Instagram] 📸 Iniciando publicação no Instagram ID {ig_user_id}...")
    
    url_criar_container = f"https://graph.facebook.com/v20.0/{ig_user_id}/media"
    payload = {
        "caption": legenda,
        "access_token": token
    }
    
    if tipo_midia == "video":
        payload["media_type"] = "REELS"
        payload["video_url"] = url_midia
    else:
        payload["image_url"] = url_midia
        
    try:
        resp_container = requests.post(url_criar_container, data=payload, timeout=60)
        if resp_container.status_code != 200:
            print(f"[Instagram] ✗ Erro ao criar container: {resp_container.text}")
            return False
            
        container_id = resp_container.json().get("id")
        print(f"[Instagram] ✓ Container criado: {container_id}")
        
        if tipo_midia == "video":
            print(f"[Instagram] ⏳ Aguardando processamento do vídeo no Meta...")
            max_tentativas = 12
            for i in range(max_tentativas):
                time.sleep(10)
                url_status = f"https://graph.facebook.com/v20.0/{container_id}?fields=status_code&access_token={token}"
                resp_status = requests.get(url_status, timeout=30)
                if resp_status.status_code == 200:
                    status = resp_status.json().get("status_code")
                    if status == "FINISHED":
                        print("[Instagram] ✓ Processamento do vídeo concluído!")
                        break
                    elif status == "ERROR":
                        print("[Instagram] ✗ Erro no processamento do vídeo no Meta.")
                        return False
                print(f"[Instagram]   ... ainda processando ({i+1}/{max_tentativas})")
        else:
            time.sleep(2)
            
        print(f"[Instagram] 📤 Publicando post...")
        url_publish = f"https://graph.facebook.com/v20.0/{ig_user_id}/media_publish"
        resp_publish = requests.post(url_publish, data={"creation_id": container_id, "access_token": token}, timeout=60)
        
        if resp_publish.status_code == 200:
            print(f"[Instagram] ✓ Post publicado! Post ID: {resp_publish.json().get('id')}")
            return True
            
        print(f"[Instagram] ✗ Erro ao publicar: {resp_publish.text}")
        return False
        
    except Exception as e:
        print(f"[Instagram] ✗ Erro na requisição: {e}")
        return False

# ═══════════════════════════════════════════════════════════════════════════════
#  FLUXO PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"\n{'═'*60}")
    print(f"  🤣 RVS MEMES — Bot Reddit → Facebook (via Meme-API)")
    print(f"  ⏰ {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}")
    print(f"{'═'*60}\n")

    estado = carregar_estado()
    print(f"[Estado] {len(estado.get('posted_ids', []))} posts já postados no histórico.")

    random.shuffle(SUBREDDITS)
    post_escolhido = None

    for subreddit in SUBREDDITS:
        posts = buscar_posts(subreddit, POSTS_POR_BUSCA)
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
        sys.exit(1)

    tipo_midia = post_escolhido["midia"]["tipo"]
    url_midia = post_escolhido["midia"]["url"]

    ext_raw = ".mp4" if tipo_midia == "video" else Path(url_midia.split("?")[0]).suffix.lower()
    if ext_raw not in EXTENSOES_IMAGEM and tipo_midia == "imagem": ext_raw = ".jpg"
    ext_final = ".mp4" if tipo_midia == "video" else ".jpg"

    caminho_raw = f"media_raw{ext_raw}"
    caminho_final = f"media_final{ext_final}"

    if not baixar_midia(url_midia, caminho_raw):
        print("[ERRO] Falha no download da mídia.")
        sys.exit(1)

    media_hash = calcular_hash(caminho_raw)
    if ja_foi_postado(estado, post_escolhido["id"], media_hash):
        print("[AVISO] Mídia duplicada detectada pelo hash. Abortando.")
        sys.exit(0)

    if tipo_midia == "video":
        sucesso_proc = processar_video(caminho_raw, caminho_final)
    else:
        sucesso_proc = processar_imagem(caminho_raw, caminho_final)

    if not sucesso_proc: caminho_final = caminho_raw

    legenda = formatar_legenda(post_escolhido)
    print(f"\n[Legenda]\n{legenda[:200]}{'...' if len(legenda) > 200 else ''}")

    if tipo_midia == "video":
        sucesso_fb = publicar_video_facebook(caminho_final, legenda)
    else:
        sucesso_fb = publicar_imagem_facebook(caminho_final, legenda)

    if not sucesso_fb:
        print("\n[ERRO] Publicação no Facebook falhou.")
        sys.exit(1)

    # ════════════════════════════════════════════════════════════════════
    #  INSTAGRAM
    # ════════════════════════════════════════════════════════════════════
    ig_user_id = obter_instagram_id()
    if ig_user_id:
        print(f"\n[Instagram] Conta conectada encontrada ({ig_user_id})")
        sucesso_ig = publicar_instagram(ig_user_id, url_midia, tipo_midia, legenda)
        if not sucesso_ig:
            print("[AVISO] Publicação no Instagram falhou, mas o Facebook funcionou.")
    else:
        print("\n[Instagram] Nenhuma conta Business conectada à Página encontrada (ou falha na API). Pulando IG.")

    registrar_postagem(estado, post_escolhido["id"], media_hash)
    salvar_estado(estado)

    for arquivo in [caminho_raw, caminho_final]:
        if os.path.exists(arquivo) and arquivo != caminho_final:
            os.remove(arquivo)

    print(f"\n{'═'*60}")
    print(f"  ✅ Post publicado com sucesso!")
    print(f"  📊 Total publicados: {estado['total_postados']}")
    print(f"{'═'*60}\n")

if __name__ == "__main__":
    main()
