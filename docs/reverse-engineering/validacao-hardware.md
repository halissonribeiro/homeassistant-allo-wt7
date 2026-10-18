# Roteiro de validação no aparelho

Tudo abaixo é **somente leitura**, salvo onde indicado. Nenhum teste abre a
porta.

## 1. Sondagem somente leitura

No computador que roda o Home Assistant (ou em qualquer máquina da mesma
rede, com Python 3):

```sh
python3 tools/probe_readonly.py --ip <IP do monitor> \
  --oac-file /config/.storage/allo_wt7_<entry_id>_oac
```

O script envia só comandos `get.*` (XML: `get.system.info`,
`get.product.info`, `get.device.status`, `get.system.status`,
`get.tfcard.info`; JSON: `get.audio.outvolume`, `get.lock.status`,
`get.call.time`) e oculta MAC, SSID, IPs, IDs e chaves na saída. Revise a
saída antes de compartilhar.

O que observar: o código `<error>` (ou `"error"`) de cada comando. `0` quer
dizer suportado; `-1`/`-10`, não suportado; `401`, credencial recusada.

## 2. O OAC expira?

1. Copie o valor de `oac` em `.storage/allo_wt7_<entry_id>_oac` para um lugar
   seguro.
2. Depois de alguns dias, force uma renovação (recarregar a integração depois
   de passar das 12 h basta) e compare o novo `oac` com o anotado.
3. Iguais → a hipótese "OAC fixo" se confirma.

Alternativa mais rápida: com a internet do Home Assistant desligada por mais
de 12 h, aperte o botão da porta. Se abrir, o OAC antigo continua válido.

## 3. Dialeto JSON

Resultado do teste 1 para os três comandos JSON. Se vierem com `error: 0`,
volume e tempo de abertura podem virar entidades.

## 4. ONVIF/RTSP

Com o app, veja se existe opção de senha ONVIF no monitor. Na rede, teste se
as portas 80/554/8000 respondem (`nc -zv <IP> 554`). Qualquer resposta em 554
merece um teste com `ffprobe rtsp://<IP>:554/`.

## 5. IDS9478W (se houver acesso a um)

Rodar o teste 1 nele e anexar a saída a uma issue.
