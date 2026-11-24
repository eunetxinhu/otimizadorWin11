# -*- mode: python ; coding: utf-8 -*-
#
# Build:  pyinstaller --noconfirm eunetxinhu-otimizacoes.spec
# Saída:  dist\eunetxinhu-otimizacoes.exe
#
# - app_icon.ico vai junto no .exe (ícone da janela, não só do arquivo).
# - Arquivos de tema/fontes do customtkinter são incluídos explicitamente.
# - UPX desligado: .exe comprimido com UPX dispara MUITO mais falso positivo
#   em antivírus.
# - uac_admin: o Windows pede elevação (UAC) antes de abrir o app.

from PyInstaller.utils.hooks import collect_data_files

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('app_icon.ico', '.')] + collect_data_files('customtkinter'),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'tests'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='eunetxinhu-otimizacoes',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=['app_icon.ico'],
)
