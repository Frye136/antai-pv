# -*- mode: python ; coding: utf-8 -*-
# Construction :  .\build.ps1   (ou  pyinstaller AntaiPV.spec)
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("winrt") + ["win32crypt", "win32com.client", "pythoncom"]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/icon.ico", "assets"), ("assets/icon.png", "assets")],
    hiddenimports=hidden,
    excludes=[
        "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSql", "PySide6.QtTest",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AntaiPV",
    icon="assets/icon.ico",
    console=False,
    upx=False,
    version=None,
)
