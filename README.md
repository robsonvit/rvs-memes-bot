# 🤣 RVS MEMES — Bot Reddit → Facebook

Automação que busca posts aleatórios de memes brasileiros no Reddit e publica automaticamente na página do Facebook **RVS** via Meta Graph API.

## 🚀 Como funciona

```
Reddit (r/MemesBR, r/ComentariosMelhores, r/MEMEBRASIL)
           ↓ (OAuth2 API)
    Seleção aleatória de post com mídia
           ↓
    Download (imagem ou vídeo)
           ↓
    Processamento (remove metadados + melhora qualidade)
           ↓
    Publicação no Facebook (Meta Graph API v20.0)
           ↓
    Salva estado anti-duplicata (state.json)
```

## ⚙️ Configuração (GitHub Secrets)

Acesse: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Onde obter |
|--------|-----------|
| `REDDIT_CLIENT_ID` | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → Criar app "script" |
| `REDDIT_CLIENT_SECRET` | Mesmo painel acima |
| `FB_PAGE_ID` | ID numérico da sua página do Facebook |
| `FB_ACCESS_TOKEN` | Token permanente com `pages_manage_posts` |

### Como criar o App do Reddit

1. Acesse [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)
2. Clique em **"create another app"**
3. Preencha:
   - **Name:** `RVS Memes Bot`
   - **Type:** `script` ← importante!
   - **redirect uri:** `http://localhost`
4. Copie o **Client ID** (abaixo do nome do app) e o **Client Secret**

### Como obter o FB_ACCESS_TOKEN permanente

Use o mesmo app Meta e token que já usa no projeto "Ctarina Santos".  
O token deve ter as permissões:
- `pages_show_list`
- `pages_read_engagement`  
- `pages_manage_posts`
- `publish_video` (para vídeos)

## ⏰ Agendamento

O bot roda automaticamente **3x por dia**:
- 🕘 09:00 BRT (horário de pico matinal)
- 🕒 15:00 BRT (horário de pico tarde)
- 🕗 20:00 BRT (horário de pico noturno)

Também pode ser acionado manualmente em **Actions → Run workflow**.

## 🛡️ Anti-Duplicatas

O sistema mantém em `state.json`:
- **IDs dos posts** do Reddit (evita repostar o mesmo post)
- **Hashes MD5 das mídias** (detecta duplicatas mesmo com IDs diferentes)
- Histórico de até **2.000 entradas** (rotativo)

O `state.json` é commitado automaticamente no repositório após cada post.

## 🎨 Processamento de Mídia

### Imagens
- Remove metadados EXIF completamente
- Converte para RGB (remove transparência)
- Aplica nitidez suave (UnsharpMask)
- Salva como JPEG qualidade 92% (otimizado + progressivo)
- Limite máximo: 4096px (mantém proporção)

### Vídeos
- Remove TODOS os metadados (tags, streams, capítulos)
- Recodifica com H.264 CRF 20 (alta qualidade)
- Áudio AAC 192kbps
- Otimizado para streaming (`faststart`)
- Formato MP4 compatível com Meta API

## 📁 Estrutura do projeto

```
RVS MEMES/
├── .github/
│   └── workflows/
│       └── post_reddit_facebook.yml   ← GitHub Actions
├── scripts/
│   └── post_reddit_facebook.py        ← Bot principal
├── requirements.txt
├── state.json                         ← Anti-duplicatas (auto-atualizado)
└── README.md
```
