# eunetxinhu otimizações

App desktop para Windows 11 focado em melhorar o desempenho de **PCs com hardware modesto**.
Feito em **Python 3.11+ com customtkinter**, usando `winreg` (stdlib) e `pywin32`
para acessar Registro e Serviços do Windows de forma nativa.

## Funcionalidades

| Módulo | O que faz | Arquivo |
|---|---|---|
| Inicialização | Lista programas em `HKCU`/`HKLM \Run` e permite desativar (com backup automático) | `services/startup_manager.py` |
| Limpeza de temporários | Remove `%TEMP%`, cache do Explorer e Prefetch, com preview de espaço | `services/temp_cleaner.py` |
| Serviços do Windows | Lista **apenas** serviços de uma whitelist curada, nunca serviços críticos | `services/service_manager.py` |

## Decisões de segurança

1. **Whitelist de serviços, não blacklist** (`WHITELIST` em `service_manager.py`) — só uma
   lista pequena e testada aparece pra desativar. Qualquer coisa fora dela é ignorada,
   mesmo que alguém tente chamar `disable_service()` diretamente com outro nome.
2. **Backup antes de desativar** — o valor original do item de inicialização é salvo em
   `HKCU\SOFTWARE\EunetxinhuOtimizacoes\StartupBackup` antes de ser removido.
3. **Falhas nunca derrubam o app** — toda operação de arquivo/registro/serviço tem
   tratamento de exceção específico (`PermissionError`, arquivo em uso, etc.).
4. **Exige administrador automaticamente** — `main.py` verifica com `ctypes` e relança
   o próprio script pedindo elevação (equivalente a "Executar como administrador"),
   antes mesmo de abrir a janela.

## Como rodar

```bash
cd eunetxinhu_otimizacoes
pip install -r requirements.txt
python main.py
```

Na primeira execução, o Windows vai pedir confirmação de elevação (UAC) — é esperado,
o app precisa disso pra funcionar.

## Como gerar um .exe (opcional, com PyInstaller)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name eunetxinhu-otimizacoes main.py
```

⚠️ **Atenção:** executáveis gerados com PyInstaller são frequentemente sinalizados
por antivírus/Windows Defender como suspeitos (falso positivo comum, não é exclusivo
deste projeto). Se isso acontecer no seu PC de testes, adicione uma exceção no Defender
ou assine o executável digitalmente para distribuição real.

## Limitações conhecidas

- `pywin32` precisa estar instalado e às vezes exige rodar
  `python Scripts/pywin32_postinstall.py -install` depois do `pip install` em alguns setups.
- `customtkinter` roda sobre o Tkinter do sistema — em instalações muito antigas do Python,
  pode ser necessário instalar o pacote `tk` separadamente (raro no Windows moderno).

## Próximos passos sugeridos

- Tela de "restaurar tudo" lendo o backup do registro
- Expandir a whitelist de serviços com mais itens testados
- Modo "relatório" que só mostra o que seria feito, sem aplicar nada
