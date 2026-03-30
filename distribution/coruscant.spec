# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec file for Coruscant
# Handles Windows, macOS, and Linux from a single file.
#
# Usage (run from the project root):
#   pyinstaller distribution/coruscant.spec
#
import sys
import os

project_root = os.path.abspath(os.path.join(SPECPATH, '..'))

a = Analysis(
    [os.path.join(project_root, 'main.py')],
    pathex=[project_root],
    binaries=[],
    datas=[],
    hiddenimports=[
        'psycopg2',
        'psycopg2._psycopg',
        'sqlparse',
        'sqlparse.compat',
        'sqlparse.filters',
        'sqlparse.lexer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', '_tkinter', 'matplotlib', 'numpy', 'scipy', 'PIL'],
    noarchive=False,
)

pyz = PYZ(a.pure)


if sys.platform == 'darwin':
    # macOS: directory-based .app bundle (required for proper macOS apps).
    # The build script zips this into Coruscant-macOS.zip for distribution.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='Coruscant',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        argv_emulation=True,
        target_arch=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='Coruscant',
    )
    app = BUNDLE(
        coll,
        name='Coruscant.app',
        bundle_identifier='com.marwatrust.coruscant',
        info_plist={
            'CFBundleName':             'Coruscant',
            'CFBundleDisplayName':      'Coruscant',
            'CFBundleShortVersionString': '0.9.0',
            'CFBundleVersion':          '0.9.0',
            'NSHighResolutionCapable':  True,
            'NSPrincipalClass':         'NSApplication',
            'NSRequiresAquaSystemAppearance': False,
        },
    )

else:
    # Windows and Linux: single executable file.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='Coruscant',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
