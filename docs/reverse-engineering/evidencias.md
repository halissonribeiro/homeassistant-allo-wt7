# Registro de evidências

Fonte: Allo Plus 2.4.77.17 (APK base `a37bd9a6…0488`). Caminhos de classe são
os do código descompilado (`com.quvii…`). `ev_…` são os `evidence_id` das
execuções do REA 6.7.0 (ver [README.md](README.md)); "JADX" indica busca no
código descompilado completo.

Níveis: **Confirmada** (observada e reproduzível), **Fortemente sustentada**
(várias evidências estáticas consistentes, sem teste no aparelho),
**Hipótese**, **Não investigada**, **Inviável no cenário analisado**.

> Nenhuma conclusão abaixo é "Confirmada": não houve teste no wT7 nem captura
> de tráfego. O comportamento já existente da integração (abrir porta e
> detectar campainha) foi confirmado pelo autor original no `IDS9478AW`, e o
> que se diz aqui sobre ele só confere que o app faz igual.

## Visão geral do app

- O Allo Plus é uma versão com a marca Intelbras do SDK **Quvii/QvFun**
  (atividades `com.quvii.qvfun.*` no manifesto; `ev_57048cd3…`).
- Toda conversa de comando com o monitor é **HTTP(S) POST em `/tdkcgi`** com
  um envelope XML ou JSON. Constante `CGI_ADDRESS = "/tdkcgi"` em
  `com.quvii.qvweb.device.common.HttpDeviceConst` (`ev_bbcb3e99…`).
- Fora de casa, o app chega ao mesmo `/tdkcgi` por um túnel P2P
  (`libqv-p2p-v2.so`, `QvJniApi.addPortByP2P`), que publica o monitor em
  `127.0.0.1:<porta>` no celular. Em casa (`isLanConnect()`/`isLocalMode()`),
  fala direto com o IP do monitor.
- Foram encontrados **181 nomes de comando** (`get.*`, `set.*`, `update.*`, `delete.*`) em
  `com.quvii.qvweb.device.DeviceRequestHelp` (XML) e
  `DeviceJsonRequestHelp` (JSON). Lista completa no fim deste arquivo.

---

## A. Autenticação e sessão

**Comportamento no app.** Login na nuvem QvCloud
(`/auth/user;jus_duplex=up|down`, constantes em `HttpDeviceConst`) e lista de
dispositivos com `out-auth-code` / `default-out-auth-code`
(`com.quvii.qvweb.userauth.bean.response.DevBindResp`).

**Cabeçalho LAN.** `DeviceRequestHelp.initHeader(QvDevice, int)`
(`ev_abbbb1f3…`): em modo LAN, usa `security` do dispositivo, usuário
`adminapp2` (`SDKConst.DEVICE_USER_NAME`), senha
`QvEncrypt.EncodeDevicePassword(authCode)` e `passwordencode = 1`.
`EncodeDevicePassword` (`ev_b57145ac…`) devolve o valor como está se tiver 64
caracteres ou mais, e senão o SHA-256 em hexadecimal. O cabeçalho JSON
(`DeviceJsonRequestHelp.initHeader`) segue a mesma regra.

- **Fortemente sustentada:** a integração atual monta o mesmo cabeçalho
  (`client._build_lan_envelope`).

**O que é o OAC.** O `authCode` do cabeçalho é o "código de verificação" do
monitor. O app permite trocá-lo com `set.seurity.verifycode`
(`DeviceRequestHelp.modifyDevOuterAuthCode`, `ev_c5e6f325…`; conteúdo
`<old>`, `<new>`, `<acountid>`, `<bencode>` em `ModifyDevOuterAuthCode`), e
depois disso chama `setAuthCode(novo)` (`HttpDeviceManager`, lambda
`modifyDevOuterAuthCode$88`). Existe também `default-out-auth-code` vindo da
nuvem e a flag `isDefaultOutAuthcode`.

- **Hipótese (forte):** o OAC é uma credencial **fixa do aparelho**, que só
  muda quando alguém troca o código de verificação no app, e **não** um token
  de sessão que expira em 12 h. Se isso se confirmar, a nuvem só é necessária
  na configuração inicial, e a integração pode funcionar 100% local depois.
  O TTL de 12 h atual é uma escolha do autor original, não algo visto no app.
- Contra-evidência a checar: `QvDevice` tem `pwdExpiredTime`/`passwordExpired`,
  mas ligado à senha `tdc`/`dataEncodeKey` do fluxo de vídeo, não ao OAC.
- **Próximo experimento:** anotar o OAC em `.storage/allo_wt7_*_oac`, forçar
  uma renovação dias depois e comparar (ver validação, teste 2).

**Modelos com autenticação HTTP Digest.** `RetrofitUtil.getDirectDeviceApi`
e `DeviceAuthHeaderInterceptor` (`ev_a6b923ca…`): quando o bit de capacidade
124 está ativo (`QvDeviceAbility.isSupportDeviceHttpAuth`) o app manda
`security = "httpauthen"` com usuário e senha vazios no envelope, e autentica
por **HTTP Digest (MD5)** no cabeçalho `Authorization`.

- **Hipótese:** variantes que respondem diferente (como o `IDS9478W`, que hoje
  devolve `-1`) podem estar nesse modo ou usar o dialeto JSON abaixo. Não há
  evidência direta ligando o modelo a um dos dois.

## B. Campainha e notificações

**No app.** A chamada chega por **push da nuvem**: `FcmPushService`
(Firebase), `PushHelper` → `PushCallActivity`, e MQTT na nuvem
(`com.quvii.shadow.mqtt.QvMqttManager.initMqttClient`, `ev_b2659979…`;
tópicos por conta `…/<ACCOUNT_ID>/<ALARM_CLIENT_ID>#`). O push traz
`alarmEvent`, `alarmTime`, `cid`, `channel` e `RecordResUrl`
(`QvPushInfo`). Não há servidor ou socket local no código Java (nenhum
`ServerSocket`/`DatagramSocket` em `com.quvii`; JADX).

- **Fortemente sustentada:** não existe um canal local de "toque" que o
  monitor envie ao app. Receber o evento sem nuvem continua dependendo de
  consultar o monitor.
- **Fortemente sustentada:** a detecção atual (fotos novas via
  `get.record.session` + `get.record.message`) usa os mesmos comandos e
  campos que o app usa para listar gravações (`Record`, `RecordSessionRes`).
- `get.record.search` (dias com gravação, `daymask`) e
  `get.record.alarmrecord` existem e podem servir para histórico.
- `get.device.status` tem os campos `calling` e `lockstatus`, mas o app os lê
  como **capacidades** (`setSupportCallConfig`, `setSupportLockTime` em
  `HttpDeviceManager`), não como estado ao vivo. **Não servem** para detectar
  toque.

## C. Vídeo e snapshots

**No app.** `QvPlayerCore.startPlay(String, String, String, int, String,
ConnectTypeCallback)` (`ev_16c346de…`) monta uma URL proprietária
`quii://<usuário>:<senha>@<ip>:<porta>/mode=real&idc=<canal>&ids=<stream>…`
e entrega ao código nativo (`GLFrameRenderer.playVideoEx`), junto com o
`dataEncodeKey` obtido por `get.device.streamkey`. Fotos e gravações usam o
mesmo esquema com `/mode=file&type=pic&idx=…&filename=…`
(`QvDeviceXmlParsing.generateRecordUrl`; string idêntica em
`liblive_player.so`).

- **Fortemente sustentada:** vídeo ao vivo e download das fotos usam o
  protocolo binário proprietário **QUII** dentro de `liblive_player.so`, com
  os dados cifrados por uma chave do aparelho. Não é RTSP nem HTTP simples.
- **Hipótese:** o monitor também tem configuração ONVIF
  (`get.onvif.pwd`/`set.onvif.pwd` no app). Se o wT7 expuser ONVIF/RTSP,
  bastaria a integração ONVIF nativa do Home Assistant. Não há evidência de
  que o wT7 tenha esse recurso.
- Implementar QUII exigiria engenharia reversa nativa (Ghidra) e captura de
  tráfego. Complexidade muito alta.

## D. Áudio bidirecional

Mesma pilha nativa (`quiitalk.cpp`, caminho `/talk`), URL montada em
`QvPlayerCore` (`talkUrl`) e `AudioPlayerManager.startTalking`; áudio com
`libWebrtcAudio.so`. Comandos de configuração `get/set.audio.session` e
`get/set.audio.outvolume`.

- **Fortemente sustentada:** depende do mesmo protocolo QUII do vídeo.
  **Inviável no curto prazo** sem o protocolo nativo.

## E. Acionamento das saídas

`DeviceRequestHelp.deviceUnlock(QvDevice, int, int, String)` (`ev_4b082bee…`;
chamado só por `HttpDeviceManager`, `ev_9d2642ca…`) envia
`set.device.opendoor` com `<door>` = canal, `<locknumber>` = fechadura e
`<password>` opcional (`DeviceUnlockContent`, todos `required = false`).
Existe uma segunda forma, `openLock`, com `<door>` = fechadura e
`<password>` obrigatório (`OpenLockContent`). `set.opendoor.checkpassword`
valida o PIN sem abrir.

- **Fortemente sustentada:** a integração atual envia exatamente o formato de
  `deviceUnlock` (`<door>1</door><locknumber>N</locknumber>[<password>]`).
- Outros comandos ligados a portas, **não implementados e sem teste**:
  `set.hold.unlock` (manter aberta), `get/set.lock.status` (JSON: lista de
  fechaduras com tempo `min/max/value`, provavelmente o tempo de abertura),
  `get/set.auto.unlock`, senhas temporárias (`get/set/update/delete.temp.pwd`)
  e QR de abertura (`get/set.qrcode.*`).
- A resposta só confirma que o comando foi aceito. Nada no app indica um
  sensor de porta aberta.

## F. Configuração e estado

Comandos de leitura com resposta mapeada em classes do app:

| Comando | Formato | Campos (classe de resposta) |
|---|---|---|
| `get.system.info` | XML | `system/info/{model, version, mac, releasedate, channelnum, …}` (`GetSystemInfoResp`) |
| `get.product.info` | XML | `info/{model, version, mac, releasedate}` (`DeviceInfoResp`) |
| `get.device.status` | XML | rede, Wi-Fi (`ssid`, `rssi`), cartão SD, fuso, versão, capacidades (`DeviceAllInfoResp`, `ev_594703a1…`) |
| `get.tfcard.info` | XML | cartão SD (`TfCardInfoResp`) |
| `get.audio.outvolume` | JSON | `prompt` e `talk` com `level/min_level/max_level` (`GetVolumeContent`) |
| `get.lock.status` | JSON | `lock[]` com `id`, `name`, `time{min,max,value}` (`GetLockInfoContent`) |
| `get.call.time` | JSON | duração da chamada |
| `get.system.upgradeversion` | XML | versão de firmware disponível |

- **Fortemente sustentada:** esses comandos existem no app e o formato da
  resposta é o das classes citadas.
- **Hipótese:** o wT7 responde a eles. `get.system.info` foi implementado
  nesta etapa como leitura opcional, que se desliga sozinha se o aparelho
  responder `-1`/`-10`.
- O dialeto **JSON** usa o mesmo `/tdkcgi`, `Content-Type: application/json`,
  corpo `{"header": {security, username, password, passwordencode},
  "body": {"command": …}}` e resposta `{"body": {"error", "content"}}`
  (`QvCommonJsonRequest`, `QvBaseJsonRespond`).

## G. Compatibilidade entre variantes

O app escolhe a implementação por tipo de aparelho em
`QvDeviceSDK.getDeviceApi(QvDevice, int)`: `QvDeviceLtApi` (tipo 1),
`QvDeviceIotControlApi` (tipo 2, comandos por um `IIotControl`
injetável), `QvDeviceOldApi` (`isUseOldApi()`) ou `QvDeviceApi`. Somam-se a
isso a autenticação Digest (bit 124) e o dialeto JSON.

- **Hipótese:** o `IDS9478W` cai em um desses caminhos alternativos. Para
  saber qual, o próximo passo é rodar o script de sondagem nele e comparar
  com um `IDS9478AW`.
- **Critério seguro de incompatibilidade** (já usado pela integração): erro
  LAN `-1` ou `-10` é permanente; o comando é desativado e não é repetido.

---

## Lista de comandos encontrados

XML (`DeviceRequestHelp`) e JSON (`DeviceJsonRequestHelp`), extraídos por
busca textual no código descompilado:

`delete.temp.pwd` `get.alarm.alarmin` `get.alarm.alarmin.schedule`
`get.alarm.alarmout` `get.alarm.crydetection` `get.alarm.motiondetection`
`get.alarm.motiondetection.schedule` `get.alarm.videolost`
`get.alarm.videolost.schedule` `get.alarm.videoshelter`
`get.alarm.videoshelter.schedule` `get.audio.outvolume` `get.audio.session`
`get.auto.unlock` `get.babysitter` `get.call.time`
`get.channelmanagement.config` `get.custom.ring` `get.device.qrcode`
`get.device.status` `get.device.streamkey` `get.encode` `get.encode.audio`
`get.encode.bitratelist` `get.encode.channelname` `get.encode.fps`
`get.encode.resolution` `get.enhance.ptz.range` `get.facepic.delete`
`get.facepic.info` `get.fisheye.setting` `get.floodlight.switch`
`get.fps.mode` `get.hdd.base` `get.hdr.config` `get.header.content`
`get.humantrace.info` `get.image_setting.ability` `get.light.info`
`get.lock.status` `get.motiondetection.info` `get.movedetection.info`
`get.network.base` `get.network.cloud` `get.network.config`
`get.network.workmode` `get.onvif.pwd` `get.private.pwd` `get.product.info`
`get.product.time` `get.ptz.position` `get.ptz.preset` `get.qrcode.delete`
`get.qrcode.info` `get.record.alarmrecord` `get.record.config`
`get.record.message` `get.record.search` `get.record.session`
`get.reset.code` `get.rfid.create` `get.rfid.info` `get.rrpc.commandlist`
`get.shape.mirror` `get.sip.list` `get.smart.lightinfo`
`get.smartswitch.info` `get.soundandlight.state` `get.system.ability`
`get.system.automaintenance` `get.system.general` `get.system.info`
`get.system.status` `get.system.upgradeprocess` `get.system.upgradestatus`
`get.system.upgradeversion` `get.temp.pwd` `get.tfcard.info`
`get.thirdpartypush.info` `get.tip.sound` `get.video.timetitle`
`get.videoswitch.vionoff` `get.voice.message` `get.whistle.list`
`get.wifi.list` `set.alarm.alarmin` `set.alarm.alarmin.schedule`
`set.alarm.alarmout.switch` `set.alarm.crydetection`
`set.alarm.humandetection` `set.alarm.mode` `set.alarm.motiondetection`
`set.alarm.motiondetection.schedule` `set.alarm.videolost`
`set.alarm.videolost.schedule` `set.alarm.videoshelter`
`set.alarm.videoshelter.schedule` `set.audio.outvolume` `set.audio.session`
`set.auto.unlock` `set.babysitter` `set.call.time` `set.channel.device`
`set.channelmanagement.config` `set.custom.ring` `set.custom.ringdel`
`set.custom.ringset` `set.debug.synctime` `set.device.f1function.enable`
`set.device.opendoor` `set.elevator.summonl` `set.encode`
`set.encode.audio` `set.encode.channelname` `set.encode.fps`
`set.enhance.ptz.range` `set.facepic.create` `set.facepic.info`
`set.fisheye.setting` `set.floodlight.switch` `set.fps.mode`
`set.hdd.base.format` `set.hdr.config` `set.hold.unlock`
`set.humantrace.info` `set.light.mode` `set.light.name`
`set.light.roomname` `set.lock.status` `set.motiondetection.info`
`set.movedetection.info` `set.network.base` `set.network.config`
`set.network.workmode` `set.onvif.pwd` `set.opendoor.checkpassword`
`set.opendoor.password` `set.private.pwd` `set.product.time`
`set.ptz.position` `set.ptz.preset` `set.ptz.preset.clear`
`set.ptz.tour.start` `set.ptz.tour.stop` `set.qrcode.create`
`set.qrcode.name` `set.record.config` `set.rfid.create` `set.rfid.delete`
`set.rfid.update` `set.seurity.verifycode` `set.shape.mirror`
`set.sip.create` `set.sip.delete` `set.sip.modify` `set.sip.use`
`set.smart.lightinfo` `set.smart.lightmode` `set.smartswitch.rename`
`set.smartswitch.roommode` `set.smartswitch.switch`
`set.smartswitch.switchadd` `set.smartswitch.switchdel`
`set.soundandlight.state` `set.subdevice.name`
`set.system.automaintenance` `set.system.general` `set.system.summertime`
`set.system.upgrade` `set.system.whistle` `set.temp.pwd` `set.tfcard.format`
`set.thirdpartypush.info` `set.tip.sound` `set.videoswitch.vionoff`
`set.voice.message` `set.voice.message.clear` `set.voice.message.name`
`set.whistle.list` `set.wifi.info` `update.temp.pwd`

Muitos são de câmeras e NVRs do mesmo SDK (PTZ, olho de peixe, iluminação),
não do wT7.
