# eunetxinhu otimizações

App desktop para Windows 11 focado em melhorar o desempenho de **PCs com hardware modesto**.
Feito em **Python 3.11+ com customtkinter**, usando `winreg` (stdlib), `ctypes` e `pywin32`
para acessar Registro, Serviços e o Shell do Windows de forma nativa.

> ## ⚠️ Usou a versão 1.0? Leia isto
>
> A versão 1.0 tinha um bug grave no botão **Desativar** da tela de Serviços: ela usava
> `win32serviceutil.ChangeServiceConfig`, uma função feita para serviços *escritos em Python*.
> Além de desativar, ela **trocava o executável do serviço** pelo próprio `.exe` do otimizador
> (ou pelo `pythonservice.exe`, rodando pelo código-fonte) e mudava o tipo do serviço.
> Resultado: o serviço ficava quebrado, e reativá-lo pelo Windows não funcionava.
>
> A versão 2.0 **detecta e repara** isso: abra **Serviços** — os danificados aparecem em
> vermelho, com o botão **Reparar todos**. O reparo devolve o executável e o tipo padrão do
> Windows 11 (o serviço continua desativado até você clicar em **Reativar**).
>
> A v1.0 também **apagava** itens da inicialização. Eles aparecem em **Inicialização →
> Removidos pela versão anterior**, com botão **Restaurar**.

## Funcionalidades

| Tela | O que faz | Código |
|---|---|---|
| Visão geral | Windows, CPU, uso de RAM e disco, tempo ligado, recomendações e botão para criar **ponto de restauração** | `services/system_info.py`, `services/restore_point.py` |
| Inicialização | Lista `HKCU`/`HKLM` `Run` (incluindo apps 32 bits em `WOW6432Node`) e as pastas *Inicializar*. Liga/desliga **do mesmo jeito que o Gerenciador de Tarefas** (nada é apagado). Mostra itens cujo programa não existe mais | `services/startup_manager.py` |
| Limpeza | Categorias com prévia de espaço: temporários do usuário e do Windows, relatórios de erro, miniaturas, downloads do Windows Update, Lixeira e Prefetch (este último desmarcado e com aviso) | `services/temp_cleaner.py` |
| Serviços | Só uma **whitelist** curada; desativar guarda o estado original, **Reativar** devolve exatamente como estava; **Reparar** corrige serviços danificados pela v1.0 | `services/service_manager.py` |

## Decisões de segurança

1. **Whitelist de serviços, não blacklist** (`WHITELIST` em `service_manager.py`). Qualquer nome
   fora dela é recusado pelo próprio manager, mesmo que alguém chame `disable_service()` direto.
2. **Só o tipo de inicialização do serviço é alterado.** Executável, tipo de processo, conta e
   dependências vão como "sem alteração" para a API do Windows — e o código confere depois.
3. **Inicialização sem apagar nada**: usa as chaves `Explorer\StartupApproved` (as mesmas do
   Gerenciador de Tarefas), então dá para religar aqui ou no próprio Windows.
4. **Limpeza nunca segue links/junctions** (uma junction no `%TEMP%` apontando para Documentos
   não leva o app a apagar seus documentos), ignora por padrão arquivos mexidos nas últimas
   24 h (instaladores em andamento) e pula arquivos em uso. A pasta temporária do próprio `.exe`
   é sempre ignorada.
5. **Prefetch não é limpo por padrão**: apagar o Prefetch deixa o boot e a abertura de programas
   *mais lentos* — o contrário do que um otimizador deve fazer.
6. **Backups**: estado original dos serviços em `%LOCALAPPDATA%\EunetxinhuOtimizacoes\backup.json`.
7. **Falhas nunca derrubam o app**: tarefas demoradas rodam em segundo plano (a janela não
   trava), erros viram mensagens claras e tudo vai para o log.
8. **Exige administrador automaticamente** — `main.py` relança o app pedindo elevação (UAC).

## Como rodar

```bash
cd otimizadorWin11
pip install -r requirements.txt
python main.py
```

Na primeira execução, o Windows vai pedir confirmação de elevação (UAC) — é esperado,
o app precisa disso para mexer em serviços e na inicialização de todos os usuários.

**Logs** (para diagnosticar problemas): `%LOCALAPPDATA%\EunetxinhuOtimizacoes\logs\app.log`
— ou clique em **Abrir pasta de logs** no canto inferior esquerdo do app.

## Como gerar o .exe (PyInstaller)

```bash
pip install -r requirements-dev.txt
pyinstaller --noconfirm eunetxinhu-otimizacoes.spec
```

O executável fica em `dist\eunetxinhu-otimizacoes.exe`. O `.spec` já cuida de:

- ícone do arquivo **e** da janela (`app_icon.ico` vai embutido);
- arquivos de tema do customtkinter;
- pedido de administrador no manifesto (`uac_admin`);
- **sem UPX**, que aumenta muito os falsos positivos de antivírus.

Para validar o `.exe` sem abrir a janela: `dist\eunetxinhu-otimizacoes.exe --self-test`
(sai com código 0 se todas as telas carregarem; detalhes no log).

⚠️ Executáveis gerados com PyInstaller às vezes são sinalizados pelo Windows Defender
(falso positivo comum). Para distribuir, o ideal é assinar o executável digitalmente.

O **CI do GitHub** gera o `.exe` a cada push: veja a aba *Actions* → execução → artefato
`eunetxinhu-otimizacoes-exe`.

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest            # no Windows: inclui integração com Registro/Serviços reais
xvfb-run -a python -m pytest   # no Linux, para incluir os testes de interface
ruff check .
```

- `tests/fakes.py` tem versões em memória de `winreg` e `win32service` (que conferem até os
  direitos de acesso pedidos), então a lógica é testada em qualquer sistema.
- `tests/test_gui.py` abre a janela de verdade e executa os fluxos (reparar, desativar,
  reativar, alternar inicialização, limpar).
- `tests/test_windows_integration.py` roda **só no Windows** (no CI, numa máquina descartável):
  desativa/reativa um serviço real conferindo que o executável não muda, **reproduz o bug da
  v1.0 num serviço de teste e comprova o reparo**, testa junctions NTFS, arquivos travados e
  somente-leitura, Lixeira e leitura do sistema.

## Estrutura

```
main.py                 entrada: log, elevação, tratamento de erro fatal, --self-test
elevation.py            UAC e caixas de mensagem nativas
app_info.py             nome/versão, pastas de dados, log
models.py               dataclasses e enums
services/
  service_manager.py    serviços (whitelist, desativar/reativar/reparar)
  startup_manager.py    inicialização (StartupApproved, Run, Run32, pastas)
  temp_cleaner.py       limpeza por categorias
  recycle_bin.py        Lixeira (Shell API)
  system_info.py        dados do PC + recomendações
  restore_point.py      ponto de restauração (PowerShell)
  backup_store.py       backup.json
  cmdline.py            leitura de linhas de comando do Windows
gui/
  app.py                janela, menu lateral, injeção de dependências
  background.py         tarefas em segundo plano sem travar a interface
  theme.py              paleta, fontes, botões
  pages/                uma tela por arquivo
tests/                  pytest (unitários, interface e integração Windows)
```

## Limitações conhecidas

- `pywin32` às vezes exige `python Scripts/pywin32_postinstall.py -install` depois do
  `pip install`. Se ele não carregar, o app abre mesmo assim e a tela de Serviços explica o problema.
- O Windows só cria **um ponto de restauração a cada 24 h** e exige a *Proteção do Sistema*
  ligada no disco C:; o app avisa quando não conseguir.
- O cache de miniaturas costuma estar em uso pelo Explorer; esses arquivos são pulados.

## Próximos passos sugeridos

- Ajuste de efeitos visuais ("melhor desempenho") e do plano de energia
- Expandir a whitelist de serviços com mais itens testados
- Assinatura digital do `.exe`
