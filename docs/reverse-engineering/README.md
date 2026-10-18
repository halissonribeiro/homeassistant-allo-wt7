# Engenharia reversa do Intelbras Allo Plus

Investigação estática do aplicativo oficial **Allo Plus 2.4.77.17** para
descobrir o que pode ser integrado ao Home Assistant, de forma local, no
videoporteiro **Intelbras Allo wT7**.

| Documento | Conteúdo |
|---|---|
| [evidencias.md](evidencias.md) | Registro por funcionalidade, com classes, métodos e nível de confiança |
| [matriz.md](matriz.md) | Matriz de viabilidade, arquitetura proposta e plano incremental |
| [validacao-hardware.md](validacao-hardware.md) | Roteiro de testes no aparelho real, incluindo o script somente leitura |

Nada aqui foi testado em um wT7 real ainda. Toda conclusão é **estática**
(código descompilado) e está marcada com o nível de confiança.

## Artefato analisado

O XAPK não faz parte do repositório (software proprietário). Hashes para
reprodução:

| Arquivo | Tamanho | SHA-256 |
|---|---|---|
| `Allo+Plus_2.4.77.17_APKPure.xapk` (ZIP, origem APKPure) | 107 170 324 B | `fa3b29f1864c759fa434dd0086862ccfc64a23a5d5e85a45f404e2d29472b082` |
| `com.intelbras.alloplus.apk` (base, DEX + recursos) | 48 049 362 B | `a37bd9a610b224176e6dbf2742f379995607bf30990655dbcf9fec46634b0488` |
| `config.arm64_v8a.apk` (bibliotecas nativas) | 58 947 012 B | `1d94c31ebc59371f249228e7715fdca9df466b7b6e2d86619629f9750d789200` |
| `config.en.apk` (idioma) | 74 137 B | `becb6957ba0b8cf8dbd8a040c7ba111b36e7aecbdb4be5dc392afabe8b219278` |
| `config.mdpi.apk` (densidade) | 79 484 B | `c6aef559a51e010e34647d54ac58ca04508254022d1bd01b00efe46f0de8f8c1` |

O `manifest.json` do XAPK declara pacote `com.intelbras.alloplus`, versão
`2.4.77.17` (código 19), SDK mínimo 23, alvo 34 e os quatro splits acima, o
que confere com o conteúdo. O APK base sozinho tem todo o código Java/Kotlin;
o split `arm64_v8a` traz as bibliotecas nativas usadas para vídeo, áudio e
P2P. **Assinaturas dos APKs não foram verificadas** (não havia `apksigner`
no ambiente); a autenticidade se apoia apenas na origem e nos hashes acima.

### Bibliotecas nativas relevantes (split arm64)

| Biblioteca | Papel provável (inferido pelos símbolos) |
|---|---|
| `liblive_player.so` | SDK "QVNetSDK": protocolo proprietário **QUII** de vídeo ao vivo, reprodução, snapshot, conversa (`quiistream.cpp`, `quiisnapshot.cpp`, `quiitalk.cpp`) |
| `libqv-p2p-v2.so` | P2P da nuvem QvCloud (túnel até o monitor fora da rede local) |
| `libWebrtcAudio.so` | Processamento de áudio (cancelamento de eco) para a conversa |
| `libavcodec.so` etc. | FFmpeg para decodificar o vídeo |
| `libpairipcore.so` | Proteção PairIP do Google Play (anti-adulteração) |

## Ferramentas

- **REA 6.7.0** (`rea-agents` no npm) com o provedor Android
  `jadx-headless-mcp 0.7.1` (SHA-256 do JAR conferido com o valor fixado pelo
  REA: `6e5eacf5…ff75`), em JDK 21 no Linux. Comandos usados:
  `inspect-android-package`, `inspect-android-class`,
  `inspect-android-method`, `search-android-classes` e
  `trace-android-references`. Os `evidence_id` citados em
  [evidencias.md](evidencias.md) vêm dessas execuções.
- **JADX 1.5.1** (CLI) para descompilar o APK inteiro (8 875 classes, 2 erros
  de descompilação sem relação com as classes citadas) e permitir busca
  textual. O REA consulta uma classe por vez, então a busca ampla foi feita
  no código gerado pelo JADX e as conclusões principais foram conferidas com
  o REA.
- `strings` nas bibliotecas nativas, apenas para identificar módulos. Nenhuma
  análise nativa (Ghidra/Hopper) foi feita.

O aplicativo **não foi instalado nem executado**, e nenhum tráfego foi
capturado.

## Como reproduzir

```sh
unzip Allo+Plus_2.4.77.17_APKPure.xapk -d apk
export REA_JADX_MCP_JAR=/caminho/jadx-headless-mcp-0.7.1-all.jar
npx rea-agents@6.7.0 inspect-android-package apk/com.intelbras.alloplus.apk --json
npx rea-agents@6.7.0 inspect-android-method apk/com.intelbras.alloplus.apk \
  com.quvii.qvweb.device.DeviceRequestHelp deviceUnlock --json
jadx -d decomp apk/com.intelbras.alloplus.apk   # busca textual
```

## Limitações

- Análise estática apenas: o que o app *faz* em tempo de execução, e quais
  comandos o firmware do seu wT7 aceita, ainda precisa ser confirmado no
  aparelho (ver [validacao-hardware.md](validacao-hardware.md)).
- O app é um SDK genérico da Quvii (pacote `com.quvii.qvfun`) usado por vários
  produtos. A existência de um comando no app **não prova** que o wT7 o
  implementa.
- Partes do código usam nomes ofuscados e uma constante criptográfica embutida
  no app; esses valores não são reproduzidos aqui.
