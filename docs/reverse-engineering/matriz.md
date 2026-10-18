# Matriz de viabilidade, arquitetura e plano

Base: [evidencias.md](evidencias.md). "Situação atual" se refere ao branch
`engenharia-reversa` (sobre a versão 0.4.0 do PR #1).

## Matriz

| Funcionalidade | Evidência | Situação atual | Nuvem | Viabilidade | Complexidade | Prioridade |
|---|---|---|---|---|---|---|
| Abrir porta social | `set.device.opendoor`, formato idêntico ao `deviceUnlock` do app (fortemente sustentada) | Implementado (`button`, serviço) | Só para obter o OAC | Já funciona no IDS9478AW | — | Manter |
| Acionar portão | Mesmo comando, `<locknumber>2</locknumber>` | Implementado | Idem | Já funciona | — | Manter |
| Detectar campainha | App usa push da nuvem (FCM/MQTT); localmente só há a lista de fotos | Implementado por consulta de fotos a cada 2 s | Não | Já funciona; não há canal local melhor no app | — | Manter |
| Funcionar sem nuvem | OAC parece ser um código fixo do aparelho (hipótese forte) | Nuvem a cada 12 h; tolera nuvem fora (0.4.0) | Hoje sim | Alta se a hipótese se confirmar | Baixa | **Alta** (teste 2) |
| Estado de disponibilidade | Resultado das próprias chamadas LAN | **Novo:** `binary_sensor` de conexão (diagnóstico) | Não | Feito, testado com mocks | Baixa | Feito |
| Modelo e firmware | `get.system.info` → `GetSystemInfoResp` | **Novo:** lido na LAN e gravado no registro de dispositivos | Não | Hipótese até testar no aparelho | Baixa | Feito (opcional) |
| Diagnóstico | Convenção do HA | **Novo:** download de diagnóstico com segredos ocultos | Não | Feito | Baixa | Feito |
| Histórico de chamadas | `get.record.search`, `get.record.message` (fotos com data) | Só a última foto | Não | Média | Média | Média |
| Volume (aviso/conversa) | `get/set.audio.outvolume` (JSON) | Não | Não | Hipótese; depende do dialeto JSON no wT7 | Baixa | Média (teste 3) |
| Tempo de abertura da fechadura | `get/set.lock.status` (JSON) | Não | Não | Hipótese | Baixa | Média (teste 3) |
| Manter porta aberta | `set.hold.unlock` | Não | Não | Hipótese; comando físico | Média | Baixa (exige teste autorizado) |
| Cartão SD | `get.tfcard.info` | Não | Não | Hipótese | Baixa | Baixa |
| Atualização de firmware disponível | `get.system.upgradeversion` | Não | Talvez | Hipótese | Baixa | Baixa |
| Snapshot da câmera | Fotos e quadros só pelo protocolo nativo QUII | Não | Não | Baixa sem RE nativa | Muito alta | Baixa |
| Vídeo ao vivo | Protocolo QUII cifrado em `liblive_player.so`; ONVIF não confirmado | Não | Não (LAN) / P2P fora | Baixa; alta só se o wT7 expuser ONVIF | Muito alta (QUII) | Investigar ONVIF primeiro |
| Áudio bidirecional | `quiitalk` na mesma pilha nativa | Não | Idem | Inviável no curto prazo | Muito alta | Baixa |
| Notificações | Push da nuvem com URL da foto (`QvPushInfo`) | Evento local `allo_wt7_doorbell_ring` | O app depende da nuvem | O HA já cobre localmente | — | Manter |
| Variantes (IDS9478W) | Caminhos alternativos: Digest (bit 124), JSON, `QvDeviceLtApi`/`IotControl` | Erro limpo e desativação | — | Hipótese; precisa de captura no IDS9478W | Média a alta | Média |
| Reconexão automática | Já tratada no cliente | Implementado (0.4.0 + sensor) | — | Feito | — | Feito |

## Arquitetura proposta

A estrutura atual já separa bem as camadas; não há motivo para reescrever.

```
custom_components/allo_wt7/
  client.py        protocolo: nuvem (login/OAC) + LAN (/tdkcgi XML; JSON a seguir)
  coordinator.py   OAC e cache, campainha, alcance da LAN, info do sistema
  entity.py        base comum (dispositivo)
  button.py        portas (pulso)            [existente]
  event.py         campainha                 [existente]
  binary_sensor.py conexão LAN               [novo]
  diagnostics.py   diagnóstico com redação   [novo]
  number.py        volume, tempo de abertura [proposto, após teste 3]
  sensor.py        cartão SD, firmware disp. [proposto]
tools/probe_readonly.py  sondagem somente leitura para validar hipóteses [novo]
```

Decisões:

- **Sem `DataUpdateCoordinator`** para estado: não há dado periódico barato
  além da campainha. Leituras raras (info do sistema a cada 12 h) usam um
  temporizador e um sinal do dispatcher.
- **Dialeto JSON** entra no `client.py` como um segundo método de envio
  (`_post_lan_json`) somente quando o teste 3 mostrar resposta do wT7.
- **Vídeo/áudio:** não implementar QUII agora. Primeiro verificar se o wT7
  responde a ONVIF/RTSP (teste 4); se sim, documentar o uso da integração
  ONVIF do HA. Se não, a alternativa é um serviço auxiliar separado, que só
  vale a pena com captura de tráfego e engenharia reversa nativa.
- Nenhum comando físico novo (`set.hold.unlock`, abrir com outras portas)
  entra sem teste autorizado e sem o limitador de frequência atual.

## Plano incremental

1. **Feito neste branch:** sensor de conexão LAN, leitura de modelo/firmware,
   diagnóstico redigido, script de sondagem. 21 testes passando (todos com
   mocks).
2. **Teste no aparelho** (você, ~10 min): roteiro em
   [validacao-hardware.md](validacao-hardware.md).
3. Se o OAC for fixo: trocar o TTL padrão para "nunca expira, renova só ao
   receber 401" e permitir configurar sem nuvem informando o código.
4. Se o JSON responder: `number` de volume e de tempo de abertura.
5. Histórico: últimas N fotos/chamadas como atributos do evento.
6. Investigar ONVIF; vídeo só depois.
